/* Demand operations extend the existing workbench. No external dependencies. */
window.LedgerUI = (() => {
  'use strict';
  const el = id => document.getElementById(id);
  const h = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const dt = v => v ? new Date(v).toLocaleString('zh-CN',{timeZone:'America/Los_Angeles',hour12:false}) : '未记录';
  const duration = n => n == null ? '未记录' : Math.abs(n)<3600 ? `${(n/60).toFixed(0)} 分钟` : `${(n/3600).toFixed(1)} 小时`;
  const labels = {discovered:'已发现',queued:'待处理',needs_info:'待补信息',executing:'有制作记录',partial:'部分输出',complete:'完整输出',blocked:'受阻'};
  const healthLabels = {recent:'最近有上报',delayed:'心跳延迟',unconfirmed:'状态待确认',unrecorded:'无 Agent 心跳记录'};
  const stages = {created:'已建任务',awaiting_agent_inventory:'解析与清单',needs_planning:'待计划',planned:'按计划制作',awaiting_model:'等待模型',needs_reconciliation:'回执待核对',needs_review:'候选待审',needs_revision:'待修正',ready_to_deliver:'待交付',delivered:'已交付',delivered_with_issues:'带瑕疵输出',not_started:'待开始'};
  const quality = {pass:'质量记录通过',issues:'有瑕疵',hold:'质量异议',not_reviewed:'待审／未记录'};
  const eventLabels = {reconciled:'证据同步',stage_recorded:'脚本阶段',claim:'认领',heartbeat:'Agent 心跳',release:'释放认领',stage:'阶段更新',ready:'信息齐备',block:'登记阻塞',resume:'解除阻塞',eta:'预计调整',link:'任务关联','executor.started':'执行器开始','executor.heartbeat':'执行器心跳','executor.finished':'执行器结束','executor.failed':'执行器失败'};
  const tag = (v,kind='') => `<span class="badge ${kind}">${h(v)}</span>`;
  let currentPage = '', selected = '', data = null, detail = null, loading = false, sequence = 0, filterTimer;
  let filters = {q:'',state:'all',locale:'',owner:'',days:'14'};
  let session = sessionStorage.getItem('ledger-session');
  if (!session) {session=crypto.randomUUID();sessionStorage.setItem('ledger-session',session);}
  let owner = sessionStorage.getItem('ledger-owner') || '';
  const request = async (url, options={}) => {
    const res = await fetch(url,{cache:'no-store',...options});
    const result = await res.json();
    if (!res.ok) throw new Error(result.error || `读取失败 (${res.status})`);
    return result;
  };
  const cards = values => `<div class="ledger-cards">${values.map(([title,value,note])=>`<div class="ledger-card"><span>${h(title)}</span><strong>${h(value)}</strong><small>${h(note)}</small></div>`).join('')}</div>`;
  const eta = value => value ? `${dt(value.lower_at)}<br>至 ${dt(value.upper_at)}<span class="quiet">${value.data.basis==='rule_estimate'?'规则估算 · 未校准':'Agent / 人工评估'}</span>` : '未记录';

  function show(page,id='') {
    currentPage=page;selected=id;
    if (el('ledger-root')?.dataset.page===page) return;
    el('content').innerHTML = `<div id="ledger-root" data-page="${page}"><div id="ledger-health" class="ledger-health">正在同步台账…</div><div class="toolbar ledger-toolbar"><input id="ledger-query" type="search" class="search" aria-label="搜索需求" placeholder="搜索需求编号、标题、原视频" value="${h(filters.q)}"><select id="ledger-state" aria-label="筛选需求状态"><option value="all">全部状态</option>${Object.entries(labels).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}<option value="overdue">预计逾期</option><option value="unlinked">待关联记录</option></select><input id="ledger-locale" class="search" aria-label="筛选语言" placeholder="语言，如 es" value="${h(filters.locale)}"><input id="ledger-owner" class="search" aria-label="筛选执行者" placeholder="执行者或聊天名称" value="${h(filters.owner)}"><select id="ledger-days" aria-label="趋势周期"><option value="7">最近 7 天趋势</option><option value="14">最近 14 天趋势</option><option value="30">最近 30 天趋势</option><option value="90">最近 90 天趋势</option></select></div><div id="ledger-metrics"></div><div id="ledger-body"></div><article id="ledger-detail" class="panel ledger-detail" hidden></article></div>`;
    el('ledger-state').value=filters.state;el('ledger-days').value=filters.days;
    for (const [id,key] of [['ledger-query','q'],['ledger-state','state'],['ledger-locale','locale'],['ledger-owner','owner'],['ledger-days','days']]) {
      el(id).addEventListener(['state','days'].includes(key)?'change':'input',e=>{
        filters[key]=e.target.value;clearTimeout(filterTimer);filterTimer=setTimeout(refresh,200);
      });
    }
    refresh();
  }

  async function refresh() {
    if (loading || !el('ledger-root')) return;
    loading=true;
    try {
      const result = await request('/api/ledger?'+new URLSearchParams(filters));
      if (!el('ledger-root')) return;
      data=result;
      const c=result.collector,s=result.sync,m=result.metrics;
      el('ledger-health').innerHTML=`<span>本地采集 <strong>${c.error?'异常，保留旧数据':c.alive?'运行中':'未运行'}</strong> · ${c.interval_seconds} 秒</span><span>最近成功 <strong>${dt(s.last_success_at)}</strong></span><span>Fireplay 快照 <strong>${dt(s.fireplay_last_snapshot_at)}</strong>（已登记范围）</span><span>同步 <strong>${s.complete?'完整读取本地记录':`部分／待同步 · ${s.warning_count || 0} 项提示`}</strong></span><span>显示时区 America/Los_Angeles</span>`;
      if(currentPage==='ledger') {
        el('ledger-metrics').innerHTML=cards([['已登记需求',m.requirements,`${m.tasks} 个语言任务`],['尚未完整输出',m.open,`${m.blocked} 条有阻塞`],['完整输出',m.complete,'质量与外部提交另列'],['预计逾期',m.overdue,`${m.eta_covered}/${m.requirements} 条有当前范围 ETA`]]);
        renderTable();
        if(selected) await loadDetail(selected);
      } else renderEfficiency();
    } catch(error) {
      if(el('ledger-health'))el('ledger-health').textContent=`台账读取失败：${error.message}。保留最后数据。`;
    } finally { loading=false; }
  }

  function renderTable() {
    const rows=data.requirements;
    const scroll=el('ledger-body').querySelector('.ledger-table')?.scrollLeft || 0;
    el('ledger-body').innerHTML=`${data.unlinked_total?`<p class="ledger-note">${data.unlinked_total} 条制作记录待关联，单独保留，不计入需求完成量。 <button data-show-unlinked>查看待关联</button></p>`:''}<p class="ledger-caption">${rows.length} / ${data.total_rows} 条记录 · 需求数按完整编号去重；历史首次预计缺失时保留“待评估”。</p><div class="ledger-table"><table><thead><tr><th>需求 / 原视频</th><th>进度与质量</th><th>负责聊天 / Agent</th><th>首次预计完成</th><th>最新预计完成</th><th>实际完整输出</th><th>当前情况</th></tr></thead><tbody>${rows.map(r=>`<tr data-selected="${selected===r.id}"><td><button class="table-action" data-requirement="${h(r.id)}">${h(r.code)}</button><span class="quiet">${r.video_count} 原片 · ${r.task_count} 语言任务</span>${!r.countable?tag('待关联','warn'):''}</td><td>${tag(labels[r.state] || r.state,r.state==='complete'?'blue':'')}<span class="quiet">输出 ${r.output_count}/${r.task_count} · 质量通过 ${r.quality_count}/${r.task_count}</span>${r.issue_count?tag(`${r.issue_count} 项瑕疵／异议`,'warn'):''}</td><td>${r.threads.length?r.threads.map(t=>`<span class="quiet">${h(t.title || t.threadId)}</span>`).join(''):'<span class="quiet">聊天未绑定</span>'}${r.claims.map(c=>`<span class="quiet">${h(c.owner)} · ${h(c.data.stage)}</span>`).join('')}<span class="quiet">${h(healthLabels[r.agent_health])}</span>${(r.executors || []).some(e=>e.health==='recent')?'<span class="quiet">本地执行器近期有上报</span>':''}</td><td class="ledger-eta">${r.first_eta?eta(r.first_eta):r.complete_at?'未记录':'待评估'}</td><td class="ledger-eta">${r.latest_eta?eta(r.latest_eta):r.complete_at?'未记录':'待评估'}${r.overdue?tag('已逾期','bad'):''}</td><td>${r.complete_at?dt(r.complete_at):'尚未完整输出'}</td><td>${h(r.block_reason || r.blockers.join('；') || (r.agent_health==='unconfirmed'?'核查执行状态':'查看详情'))}<span class="quiet">${Object.entries(r.stage_counts || {}).map(([stage,n])=>`${stages[stage] || stage} ${n}`).join(' · ')}</span><span class="quiet">最近产物记录 ${dt(r.last_activity_at)}</span></td></tr>`).join('') || '<tr><td colspan="7">没有匹配的需求；可调整筛选条件。</td></tr>'}</tbody></table></div>`;
    el('ledger-body').querySelector('.ledger-table').scrollLeft=scroll;
  }

  async function loadDetail(id,force=false) {
    const n=++sequence;
    const value=await request('/api/ledger/detail?id='+encodeURIComponent(id));
    if(n!==sequence || !el('ledger-detail') || currentPage!=='ledger')return;
    if(!force && detail?.requirement.id===id && detail.requirement.revision===value.requirement.revision && !el('ledger-detail').hidden)return;
    detail=value;const r=value.requirement;
    const node=el('ledger-detail');node.hidden=false;
    node.innerHTML=`<div class="ledger-detail-header"><div><h2>${h(r.code)}</h2><p class="quiet ledger-title">${h(r.title)}</p></div><button data-close-requirement>收起</button></div><div class="ledger-actions">${[['claim','认领'],['heartbeat','上报心跳'],['stage','更新阶段'],['release','释放认领'],['ready','信息齐备'],['block','登记阻塞'],['resume','解除阻塞'],['eta','登记 / 调整预计'],['link','关联已有任务']].map(([a,t])=>`<button data-ledger-action="${a}">${t}</button>`).join('')}</div><div class="info-grid">${[['收件登记',dt(r.received_at)],['平台创建',dt(r.platform_created_at)],['首次发现',dt(r.first_seen_at)],['信息齐备',dt(r.ready_at)],['首次完整输出',dt(r.first_complete_at)],['当前范围输出',dt(r.complete_at)]].map(([k,v])=>`<div class="info"><span>${h(k)}</span><strong>${h(v)}</strong></div>`).join('')}</div>${r.block_reason?`<p class="ledger-note">${h(r.block_reason)}</p>`:''}<div class="section-title"><h3>原视频与负责聊天</h3></div>${r.videos.map(v=>`<p class="ledger-caption">${h(v.title)} · ${h(v.id)} · ${h(v.source_sha256?.slice(0,12) || '原片尚未绑定')} · 预计 ${v.latest_eta?dt(v.latest_eta.lower_at)+' 至 '+dt(v.latest_eta.upper_at):'待评估'}${v.thread?` · ${h(v.thread.title || '已绑定聊天')} (${h((v.thread.threadId || v.thread.id || '').slice(0,8))})`:''}</p>`).join('')}<div class="section-title"><h3>各语言任务与实际成片</h3><span class="quiet">输出、质量和验收分别记录</span></div><div class="table-wrap"><table><thead><tr><th>原视频 / 语言</th><th>执行记录</th><th>当前输出</th><th>质量</th><th>实际版本</th></tr></thead><tbody>${value.tasks.filter(t=>r.scope.some(v=>v.video_id===t.video_id&&v.targets.includes(t.locale))).map(t=>`<tr><td>${h(r.videos.find(v=>v.id===t.video_id)?.title || t.video_id)}<br>${h(t.locale)}</td><td>${t.runs.map(run=>`<a href="#tasks/${encodeURIComponent(run)}">${h(run)}</a>`).join('<br>') || '未开始'}</td><td>${t.complete_at?dt(t.complete_at):t.active_revision?'新版制作中':'未完整输出'}</td><td>${tag(quality[t.quality] || t.quality,t.quality==='hold'?'bad':t.quality==='issues'?'warn':'')}</td><td>${t.current?.url?`<a href="${h(t.current.url)}" target="_blank" rel="noopener">打开视频 ↗</a><br><span class="mono">${h(t.current.sha256.slice(0,12))}</span>`:'无已核验交付包'}<span class="quiet">${t.versions.length} 个输出版本 · 用户未确认</span></td></tr>`).join('')}</tbody></table></div><div class="section-title"><h3>预计完成历史</h3><span class="quiet">当前范围 ${h(r.scope_id.slice(0,10))}</span></div>${value.estimates.length?value.estimates.map(e=>`<p class="ledger-caption">${dt(e.created_at)} · ${dt(e.lower_at)} 至 ${dt(e.upper_at)} · ${h(e.data.reason)}${e.scope_id!==r.scope_id?'（历史范围）':''}</p>`).join(''):'<p class="quiet">尚未记录预测。历史任务不会补造过去的首次预计。</p>'}<details class="ledger-source"><summary>外部提交与采集依据</summary><p>平台状态：${h(r.platform_status || '未记录')}；用户验收：未记录。</p>${r.external.length?`<pre>${h(JSON.stringify(r.external,null,2))}</pre>`:'<p>没有结构化提交回执，不推断已入库、绑定或上传。</p>'}<ul>${r.evidence.map(e=>`<li class="mono">${h(e)}</li>`).join('')}</ul><p>预算引用：${h(r.budget_ids.join('、') || '未绑定')}；范围历史 ${value.scopes.length} 版。</p></details><details class="ledger-source"><summary>阶段、等待与活动时间线（最近 ${value.events.length} 条）</summary>${value.events.map(e=>`<details class="ledger-event"><summary>${h(eventLabels[e.kind] || e.kind)} · ${dt(e.occurred_at || e.recorded_at)}${e.run_id?' · '+h(e.run_id):''}</summary><pre>${h(JSON.stringify(e.data,null,2))}</pre></details>`).join('')}<p class="quiet">脚本时间可能嵌套；执行器心跳不代表 Agent 心跳。未分类时间不计作实际工作。</p></details>`;
  }

  function trend(rows) {
    const width=700,height=240,left=38,top=18,bottom=38,plotH=height-top-bottom,plotW=width-left-12;
    const max=Math.max(1,...rows.flatMap(d=>[d.received,d.completed]));
    const band=plotW/rows.length;
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="最近 ${rows.length} 天需求登记与首次完整输出数量柱状图">${[0,.5,1].map(f=>`<line x1="${left}" y1="${top+plotH*(1-f)}" x2="${width-10}" y2="${top+plotH*(1-f)}"/><text x="3" y="${top+plotH*(1-f)+4}">${(max*f).toFixed(max<2?1:0)}</text>`).join('')}${rows.map((d,i)=>{const x=left+i*band;return `<rect class="trend-received" x="${x+band*.12}" y="${top+plotH*(1-d.received/max)}" width="${band*.33}" height="${plotH*d.received/max}"><title>${d.date} 登记 ${d.received}</title></rect><rect class="trend-completed" x="${x+band*.5}" y="${top+plotH*(1-d.completed/max)}" width="${band*.33}" height="${plotH*d.completed/max}"><title>${d.date} 完整输出 ${d.completed}</title></rect>${i%Math.ceil(rows.length/7)===0?`<text x="${x+band*.4}" y="${height-12}" text-anchor="middle">${d.date.slice(5)}</text>`:''}`;}).join('')}</svg>`;
  }

  function renderEfficiency() {
    const m=data.metrics;
    el('ledger-metrics').innerHTML=cards([['期间首次完整输出',m.completed_in_period,`最近 ${m.days} 个自然日 · 去重需求`],['交付周期中位数',duration(m.cycle_median_seconds),`${m.cycle_samples} 条收件与输出时间齐备`],['首次预计准时率',m.eta_ontime_rate==null?'未记录':`${(m.eta_ontime_rate*100).toFixed(0)}%`,`${m.eta_ontime}/${m.eta_due} 条已到期预测（全部时间）`],['首次预计偏差中位数',duration(m.eta_bias_median_seconds),`${m.eta_error_samples} 条 · 正数为超过预计上限`]]);
    const latest = data.requirements.filter(r=>r.first_complete_at&&r.countable).sort((a,b)=>new Date(b.first_complete_at)-new Date(a.first_complete_at)).slice(0,12);
    el('ledger-body').innerHTML=`<div class="ledger-grid"><section class="panel ledger-chart"><h2>登记与首次完整输出</h2><div class="ledger-legend"><span>收件登记</span><span>完整输出</span></div>${trend(m.daily)}<p class="ledger-caption">按 America/Los_Angeles 自然日；返工完成不重复增加需求完成量。</p><details><summary class="quiet">查看每日数量</summary><div class="table-wrap"><table><thead><tr><th>日期</th><th>登记</th><th>完整输出</th></tr></thead><tbody>${m.daily.map(d=>`<tr><td>${d.date}</td><td>${d.received}</td><td>${d.completed}</td></tr>`).join('')}</tbody></table></div></details></section><section class="panel ledger-chart"><h2>时间与预测覆盖</h2><div class="info-grid"><div class="info"><span>当前范围有首次 ETA</span><strong>${m.eta_covered} / ${m.requirements}</strong></div><div class="info"><span>收件时间未知</span><strong>${m.unknown_received}</strong></div><div class="info"><span>信息齐备至输出中位数</span><strong>${duration(m.ready_cycle_median_seconds)}</strong></div><div class="info"><span>信息齐备周期样本</span><strong>${m.ready_cycle_samples}</strong></div></div><p class="ledger-caption">准时率包含首次预计已到期但仍未完成的需求。首次 ETA 缺失、收件时间未知与没有反馈均保留缺失状态。</p><p class="ledger-caption">筛选应用于所有图表与指标。趋势周期用于期间产出和周期；准时率为筛选需求中全部已到期预测。</p></section></div><section class="panel ledger-detail"><h2>最近完整输出的需求</h2><div class="table-wrap"><table><thead><tr><th>需求</th><th>首次完整输出</th><th>收件至输出</th><th>当前质量通过</th></tr></thead><tbody>${latest.map(r=>`<tr><td><a href="#ledger/${encodeURIComponent(r.id)}">${h(r.code)}</a></td><td>${dt(r.first_complete_at)}</td><td>${r.received_at?duration((new Date(r.first_complete_at)-new Date(r.received_at))/1000):'未记录'}</td><td>${r.quality_count}/${r.task_count}</td></tr>`).join('') || '<tr><td colspan="4">尚无已记录的完整输出。</td></tr>'}</tbody></table></div></section>`;
  }

  function editor(action) {
    if(!detail || !data)return;
    let dialog=el('ledger-editor');
    if(!dialog){dialog=document.createElement('dialog');dialog.id='ledger-editor';dialog.className='ledger-editor';document.body.appendChild(dialog);}
    const r=detail.requirement;
    const name={claim:'认领',heartbeat:'上报心跳',stage:'更新阶段',release:'释放认领',ready:'登记信息齐备',block:'登记阻塞',resume:'解除阻塞',eta:'登记预计完成',link:'关联已有任务'}[action];
    let fields='';
    if(['claim','heartbeat','stage','release'].includes(action))fields=`<label>原视频<select name="video_id"><option value="*">整条需求</option>${r.videos.map(v=>`<option value="${h(v.id)}">${h(v.title)}</option>`).join('')}</select></label><label>执行者<input name="owner" required maxlength="200" value="${h(owner)}" placeholder="Agent 或负责人的名称"></label><label>会话 ID<input name="session" required value="${h(session)}"></label>${action!=='release'?'<label>当前阶段<input name="stage" required placeholder="如 翻译、配音、审核"></label>':''}<p class="quiet">仅在实际工作时上报；此页面不会定时替 Agent 发送心跳。</p>`;
    if(action==='eta')fields=`<label>预测对象<select name="video_id"><option value="*">整条需求完整输出</option>${r.videos.map(v=>`<option value="${h(v.id)}">${h(v.title)}</option>`).join('')}</select></label>`+'<div class="form-row"><label>预计最早完成<input type="datetime-local" name="lower_at" required></label><label>预计最晚完成<input type="datetime-local" name="upper_at" required></label></div><label>估计依据<input name="basis" required value="agent_estimate"></label><label>未确认因素<textarea name="assumptions" placeholder="如模型排队、复杂遮挡、尚待审核"></textarea></label><p class="quiet">输入使用浏览器本地时区，保存为 UTC。预测目标为当前范围完整输出；每次调整保留历史。</p>';
    if(action==='block')fields='<label>等待类型<select name="kind"><option value="user">等待用户／素材</option><option value="model">等待模型</option><option value="resource">等待资源</option><option value="platform">平台异常</option><option value="unknown">待核查</option></select></label>';
    if(action==='link')fields=`<label>原视频<select name="video_id">${r.videos.map(v=>`<option value="${h(v.id)}">${h(v.title)}</option>`).join('')}</select></label><label>语言<input name="locale" required placeholder="如 es"></label><label>已有任务 ID<input name="run_id" required></label><label>原视频完整 SHA256<input name="source_sha256" required pattern="[0-9a-f]{64}"></label><p class="quiet">校验实际任务的源哈希和语言，关联结果在下一次采集中显示。</p>`;
    dialog.innerHTML=`<div class="dialog-head"><h2>${h(name)} · ${h(r.code)}</h2><button type="button" data-close-editor>关闭</button></div><form class="ledger-form" id="ledger-edit-form">${fields}<label>原因 / 证据<textarea name="reason" required placeholder="记录实际依据或恢复说明"></textarea></label><p id="ledger-form-error" class="ledger-warning" role="alert"></p><button type="submit">保存记录</button></form>`;
    dialog.querySelector('[data-close-editor]').onclick=()=>dialog.close();
    const operation=crypto.randomUUID();
    el('ledger-edit-form').onsubmit=async e=>{
      e.preventDefault();const form=e.currentTarget;const spec=Object.fromEntries(new FormData(form));spec.requirement_id=r.id;
      if(action==='eta'){spec.lower_at=new Date(spec.lower_at).toISOString();spec.upper_at=new Date(spec.upper_at).toISOString();}
      if(spec.owner){owner=spec.owner;sessionStorage.setItem('ledger-owner',owner);}
      const button=form.querySelector('[type=submit]');button.disabled=true;
      try{
        await request('/api/ledger/action',{method:'POST',headers:{'Content-Type':'application/json','X-Ledger-Token':data.csrf_token},body:JSON.stringify({action,data:spec,operation_id:operation,expected_revision:r.revision})});
        dialog.close();await refresh();await loadDetail(r.id,true);
      }catch(error){el('ledger-form-error').textContent=error.message;}finally{button.disabled=false;}
    };
    dialog.showModal();
  }

  document.addEventListener('click', e=>{
    const row=e.target.closest('[data-requirement]');
    if(e.target.closest('[data-show-unlinked]')){filters.state='unlinked';el('ledger-state').value='unlinked';refresh();return;}
    if(row){selected=row.dataset.requirement;location.hash='ledger/'+encodeURIComponent(selected);loadDetail(selected,true).then(()=>el('ledger-detail')?.scrollIntoView({block:'start'})).catch(err=>{el('ledger-health').textContent=err.message;});return;}
    if(e.target.closest('[data-close-requirement]')){selected='';el('ledger-detail').hidden=true;location.hash='ledger';return;}
    const action=e.target.closest('[data-ledger-action]');if(action)editor(action.dataset.ledgerAction);
  });
  return {show,refresh};
})();
