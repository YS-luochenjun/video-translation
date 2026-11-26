/* Demand operations extend the existing workbench. No external dependencies. */
window.LedgerUI = (() => {
  'use strict';
  const el = id => document.getElementById(id);
  const h = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const dt = v => v ? new Date(v).toLocaleString('zh-CN',{timeZone:'America/Los_Angeles',hour12:false}) : '未记录';
  const duration = n => n == null ? '未记录' : Math.abs(n)<3600 ? `${(n/60).toFixed(0)} 分钟` : `${(n/3600).toFixed(1)} 小时`;
  const progressLabels = {done:'已完成',active:'进行中',blocked:'阻塞',waiting:'待开始'};
  const queueLabels = {ready:'可派发',waiting:'等名额',preparing:'待准备或核对'};
  const platformLabels = {not_started:'未开始',in_progress:'进行中',pending_upload:'待上传',completed:'已完成',done:'已完成',cancelled:'已取消'};
  const healthLabels = {recent:'最近有上报',delayed:'心跳延迟',unconfirmed:'状态待确认',unrecorded:'无 Agent 心跳记录'};
  const stages = {created:'已建任务',awaiting_agent_inventory:'解析与清单',needs_planning:'待计划',planned:'按计划制作',awaiting_model:'等待模型',needs_reconciliation:'回执待核对',needs_review:'候选待审',needs_revision:'待修正',ready_to_deliver:'待交付',delivered:'已交付',delivered_with_issues:'带瑕疵输出',expired:'本地成片已到期',not_started:'待开始'};
  const eventLabels = {reconciled:'证据同步',stage_recorded:'脚本阶段',claim:'认领',heartbeat:'Agent 心跳',release:'释放认领',stage:'阶段更新',ready:'信息齐备',block:'登记阻塞',resume:'解除阻塞',link:'任务关联','executor.started':'执行器开始','executor.heartbeat':'执行器心跳','executor.finished':'执行器结束','executor.failed':'执行器失败'};
  const tag = (v,kind='') => `<span class="badge ${kind}">${h(v)}</span>`;
  let currentPage = '', selected = '', data = null, detail = null, sequence = 0, listSequence = 0, filterTimer;
  let retries = null;
  const retryServices = {codex:'Codex', kie:'KIE', fireplay:'Fireplay 回传'};
  const filters = {q:'',state:'all',progress:'all',days:'14'};
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
  const uploadProgress = row => {
    if (row.platform?.verified != null) return `${row.platform.verified}/${row.task_count}`;
    return row.platform?.state === 'stale' || ['done','completed'].includes(row.platform_status) ? '待更新核验' : '—';
  };
  const detailState = row => JSON.stringify([row.revision, row.progress_state, row.platform_status,
    row.platform_refreshed_at, row.platform, row.launch]);
  const launchLabel = launch => launch.checked ? `有投放记录 ${launch.launched}/${launch.checked}`
    + (launch.materials>launch.checked ? ` · ${launch.materials-launch.checked} 项待核对` : '') : '投放待核对';

  function renderCapacity(capacity) {
    const panel=el('ledger-capacity');
    if(capacity?.state!=='ready') {
      panel.innerHTML=`<span class="quiet">${capacity?.state==='unconfigured'?'本项目无原片并发配置':'并发记录暂不可读'}</span>`;
      return;
    }
    const {active_source_count:occupied,max_active_sources_global:limit,available_source_slots:available,queue}=capacity;
    let details=panel.querySelector('details');
    if(!details){
      details=document.createElement('details');
      panel.replaceChildren(details);
    }
    const slots=limit==null ? `${occupied} 个已占用 · 无上限` : `已占 ${occupied}/${limit} · 剩余 ${available}`;
    const queueSummary=queue ? `排队 ${queue.waiting} · 可派发 ${queue.ready}` : '排队数据待同步';
    details.innerHTML=`<summary><span class="ledger-capacity-line"><strong>制作并发</strong><span>${slots}</span><span>${queueSummary}</span></span></summary>
      <p class="quiet">每部原片的所有语种共用一个名额。预约和待核对建聊也计入占用。</p>
      ${queue?.preparing?`<p class="quiet">${queue.preparing} 部原片待准备或核对。</p>`:''}
      ${queue?.legacy_requirements?`<p class="quiet">${queue.legacy_requirements} 条旧需求使用共享会话，待按原记录核对。</p>`:''}
      ${queue?.sources.length?`<ul>${queue.sources.map(source=>`<li>${h(source.code)} · 原片 ${source.video_index} · ${queueLabels[source.state]}</li>`).join('')}</ul>`:''}
      <p class="quiet">基于本地名额记录及最近巡检的待派发清单 · ${dt(capacity.observed_at)}</p>`;
  }

  function show(page,id='') {
    if (page !== currentPage) retries = null;
    currentPage=page;selected=id;
    if (el('ledger-root')?.dataset.page===page) {
      if (!selected) el('ledger-detail').hidden=true;
      else if (detail?.requirement.id!==selected) el('ledger-meta-content').parentElement.open=false;
      return;
    }
    const search = `<input id="ledger-query" type="search" class="search" aria-label="搜索需求、语言或会话" placeholder="搜索编号、标题、语言或会话" value="${h(filters.q)}">`;
    const status = `<select id="ledger-state" aria-label="筛选需求状态"><option value="all">全部状态</option>${Object.entries(progressLabels).map(([key,label])=>`<option value="${key}">${label}</option>`).join('')}</select>`;
    const days = `<select id="ledger-days" aria-label="统计周期">${[7,14,30,90].map(day=>`<option value="${day}">最近 ${day} 天</option>`).join('')}</select>`;
    el('content').innerHTML = `<div id="ledger-root" data-page="${page}">
      <div class="toolbar ledger-toolbar">${search}${page==='ledger'?status:days}
        <details class="ledger-meta"><summary>记录说明</summary><div id="ledger-meta-content">正在读取台账…</div></details>
        ${page==='ledger'?'<button type="button" data-console-action="intake">＋ 按需求号接单</button>':''}
      </div>
      <p id="ledger-health" class="ledger-warning" role="status" hidden></p>
      ${page==='ledger'?'<section id="ledger-capacity" class="panel ledger-capacity" aria-label="制作并发"><span class="quiet">正在读取制作并发…</span></section>':''}
      <div id="ledger-metrics"></div><div id="ledger-body"></div><article id="ledger-detail" class="panel ledger-detail" hidden></article>
    </div>`;
    if (el('ledger-state')) el('ledger-state').value=filters.progress;
    if (el('ledger-days')) el('ledger-days').value=filters.days;
    el('ledger-query').addEventListener('input',event=>{
      filters.q=event.target.value;
      clearTimeout(filterTimer);
      filterTimer=setTimeout(()=>refresh(),200);
    });
    el('ledger-state')?.addEventListener('change',event=>{
      filters.state='all';
      filters.progress=event.target.value;
      refresh();
    });
    el('ledger-days')?.addEventListener('change',event=>{
      filters.days=event.target.value;
      refresh();
    });
  }

  async function refresh(force=false) {
    const root=el('ledger-root');
    if (!root) return;
    const requestId=++listSequence;
    const page=root.dataset.page;
    try {
      const params = page==='ledger' ? filters : {q:filters.q,days:filters.days};
      const result = await request('/api/ledger?'+new URLSearchParams({...params,view:page==='ledger'?'list':'history'}));
      if (el('ledger-root')!==root || requestId!==listSequence) return;
      data=result;
      const {collector,sync,metrics,cohort}=result;
      const incidents=result.requirements.filter(row=>row.time_exclusion);
      el('ledger-meta-content').innerHTML=`<p><strong>${h(cohort.label || '项目台账')}</strong></p>
        ${cohort.started_at?`<p>统计起点 ${dt(cohort.started_at)}</p>`:''}
        <p>${collector.error?'采集异常 · 最近成功':collector.alive?'本地同步':'已保存快照'} ${dt(sync.last_success_at)}</p>
        ${sync.warning_count?`<p>${sync.warning_count} 项读取提示</p>`:''}
        ${incidents.length?`<ul>${incidents.map(row=>`<li><a href="#ledger/${encodeURIComponent(row.id)}">${h(row.code)}</a>
          · 耗时异常，已剔除效率统计</li>`).join('')}</ul>`:''}`;
      el('ledger-health').hidden=true;
      if(page==='ledger') {
        renderCapacity(result.source_capacity);
        const counted=result.requirements.filter(row=>row.countable);
        const productionCount=counted.reduce((total,row)=>total+row.output_count,0);
        const uploadCount=counted.reduce((total,row)=>total+(row.platform?.verified ?? 0),0);
        el('ledger-metrics').innerHTML=cards([
          ['已登记需求',metrics.requirements,`${metrics.tasks} 个语言任务`],
          ['制作完成',productionCount,`共 ${metrics.tasks} 个语言任务`],
          ['审核上传完成',uploadCount,'已核验平台绑定']
        ]);
        if (retries && !result.requirements.some(row => row.id === retries.id)) retries = null;
        renderTable();
        if (retries && (force || !retries.cursor) && !retries.loading) void loadRetries(retries.cursor);
        const row=result.requirements.find(item=>item.id===selected);
        const reveal=el('ledger-detail').hidden || detail?.requirement.id!==selected;
        if(selected && (force || reveal || (row && detailState(row)!==detailState(detail.requirement)))) {
          await loadDetail(selected,force || reveal);
          if(reveal && el('ledger-root')===root) el('ledger-detail').scrollIntoView({block:'start'});
        }
      } else renderEfficiency();
      return result.read_at;
    } catch(error) {
      if(el('ledger-root')===root && requestId===listSequence) {
        el('ledger-health').textContent=`台账读取失败。${error.message}`;
        el('ledger-health').hidden=false;
      }
    }
  }

  function renderTable() {
    const rows=data.requirements;
    const oldTable=el('ledger-body').querySelector('.ledger-table');
    const tableRows=rows.map(row=>{
      const languages = new Set((row.scope || []).flatMap(video=>video.targets)).size;
      const tasks = row.task_count !== languages ? ` · ${row.task_count} 项语言任务` : '';
      const expanded = retries?.id === row.id;
      const counts = row.retry_counts;
      const retryRows = Object.entries(retryServices).map(([key, label]) => ({
        label,
        count: key === 'codex' && !data.retry_coverage?.codex_retries && !counts?.codex
          ? null : counts?.[key]
      }));
      const retryLabel = retryRows.map(({label,count}) => `${h(label)} ${h(count ?? '—')}`).join('，');
      const retryMetrics = retryRows.map(({label,count}) => `
        <span class="ledger-retry-metric">
          <span>${h(label)}</span>
          <strong class="ledger-retry-count${count > 0 ? ' has-retries' : ''}">${h(count ?? '—')}</strong>
        </span>`).join('');
      return `<tr data-progress="${h(row.progress_state)}" data-selected="${selected===row.id}">
      <td><button class="table-action" data-requirement="${h(row.id)}">${h(row.code)}</button>
        <span class="quiet">${row.video_count} 部原片 · ${languages || '—'} 种语言${tasks}</span></td>
      <td><strong class="ledger-row-state">${h(progressLabels[row.progress_state])}</strong></td>
      <td class="ledger-counts"><div>制作完成 <strong>${row.output_count}/${row.task_count}</strong></div>
        <div>审核上传完成 <strong>${uploadProgress(row)}</strong></div>${row.launch?`<span class="quiet">${h(launchLabel(row.launch))}</span>`:''}</td>
      <td>${row.threads.map(thread=>{
        const name=h(thread.title?.trim() || '会话名称未记录');
        const identifier=thread.threadId || thread.id;
        return identifier ? `<a class="ledger-thread" href="#sessions/${encodeURIComponent(identifier)}">${name}</a>` : `<span class="quiet">${name}</span>`;
      }).join('') || '未绑定'}</td>
      <td class="ledger-times"><div>起始 <span>${row.first_started_at?dt(row.first_started_at):'—'}</span></div>
        <div>完成 <span>${row.complete_at?dt(row.complete_at):'—'}</span></div></td>
      <td><button type="button" class="ledger-retry-toggle" data-retry-demand="${h(row.id)}"
        aria-label="${h(row.code)} 重试记录，${retryLabel}" aria-expanded="${expanded}"
        ${expanded?'aria-controls="ledger-retry-detail"':''}>
        <span class="ledger-retry-metrics" aria-hidden="true">${retryMetrics}</span>
      </button></td>
    </tr>${expanded ? `<tr class="ledger-retry-detail"><td colspan="6" id="ledger-retry-detail">${retryDetails(retries)}</td></tr>` : ''}`;}).join('');
    const markup=`<p class="ledger-caption">${rows.length} 条记录${filters.state==='unlinked'?' · <button class="table-action" data-show-unlinked>返回需求</button>':data.unlinked_total?` · <button class="table-action" data-show-unlinked>待关联 ${data.unlinked_total}</button>`:''}</p>
      <div class="ledger-table bounded-table" role="region" aria-label="需求台账表" tabindex="0"><table><thead><tr><th scope="col">需求</th><th scope="col">状态</th><th scope="col">进度</th><th scope="col">负责会话</th><th scope="col">制作起止时间</th><th scope="col">重试次数</th></tr></thead>
      <tbody>${tableRows || '<tr><td colspan="6">没有匹配的需求</td></tr>'}</tbody></table></div>`;
    const body=el('ledger-body');
    if(body.innerHTML===markup)return;
    body.innerHTML=markup;
    const table=body.querySelector('.ledger-table');
    table.scrollLeft=oldTable?.scrollLeft || 0;
    table.scrollTop=oldTable?.scrollTop || 0;
  }

  function retryDetails(state) {
    if (state.error) return `<p role="status">重试明细读取失败。${h(state.error)}</p><button type="button" data-retry-reload>重新读取</button>`;
    if (!state.page) return '<p role="status">正在读取重试明细…</p>';
    const operations = {balance:'余额查询',status:'状态查询',upload:'文件上传',bind:'素材绑定',model_submit:'模型提交',
      model_request:'模型请求',model_retry:'模型重试',asset_retry:'附件恢复',
      pre_dispatch_retry:'提交前恢复',sampling:'模型请求'};
    const causes = {provider_failed:'供应商错误',transport:'连接或响应异常',invalid_response:'响应格式异常',
      previous_attempt:'前次尝试失败',sampling_error:'模型请求异常',upload_timeout:'前次上传超时',
      upload_replaced:'调整上传文件后重试'};
    const outcomes = {started:'已开始',submitted:'已提交',success:'成功',failed:'失败',
      unknown:'结果待核查',observed:'宿主记录重试',timeout:'超时'};
    const items = state.page.events.map(event => {
      const subject = event.session || event.run || `原片 ${event.video_index ?? '—'}${event.locale ? ` · ${event.locale}` : ''}`;
      const cause = /^http_[1-5]\d\d$/.test(event.reason) ? `状态码 ${event.reason.slice(5)}` : causes[event.reason];
      return `<tr><td>${dt(event.at)}</td><td>${h(retryServices[event.source])}</td><td>${h(subject)}</td>
        <td>${h(operations[event.operation] || '请求')} · 第 ${h(event.attempt)} 次重试</td>
        <td>${h(cause || '—')}</td><td>${h(outcomes[event.outcome] || '—')}</td></tr>`;
    }).join('');
    const table = items ? `<table class="ledger-retry-table" aria-label="需求重试明细"><thead><tr>
      <th>时间</th><th>服务</th><th>会话、运行或语种</th><th>事件</th><th>原因</th><th>结果</th>
      </tr></thead><tbody>${items}</tbody></table>` : '<p>暂无可关联的重试记录。</p>';
    const pager = (state.history.length || state.page.next_cursor) ? `<div class="retry-pages">
      <button type="button" data-retry-prev ${state.history.length && !state.loading ? '' : 'disabled'}>上一页</button>
      <button type="button" data-retry-next ${state.page.next_cursor && !state.loading ? '' : 'disabled'}>下一页</button>
      </div>` : '';
    const codex = state.page.coverage.codex_retries ? 'Codex 来自宿主可见记录，首次补录最近 7 天。' : 'Codex 日志暂不可读。';
    return `${table}${pager}<p class="quiet">${codex}${state.page.coverage.kie_history?'':'部分 KIE 历史任务暂不可读。'}</p>`;
  }

  async function loadRetries(cursor) {
    const state = retries;
    if (!state || state.loading) return;
    state.loading = true;
    state.error = null;
    try {
      state.page = await request('/api/retry-activity?'+new URLSearchParams({id:state.id,before:cursor}));
    } catch(error) {
      state.error = error.message;
    } finally {
      state.loading = false;
      if (retries === state && el('ledger-root')?.dataset.page === 'ledger') renderTable();
    }
  }

  async function loadDetail(id,force=false) {
    const n=++sequence;
    const value=await request('/api/ledger/detail?id='+encodeURIComponent(id));
    if(n!==sequence || id!==selected || !el('ledger-detail') || currentPage!=='ledger')return;
    if(!force && detail?.requirement.id===id && detailState(detail.requirement)===detailState(value.requirement) && !el('ledger-detail').hidden)return;
    const row=value.requirement;
    const node=el('ledger-detail');
    const opened = new Set(detail?.requirement.id===id
      ? [...node.querySelectorAll('details[open][data-section]')].map(item=>item.dataset.section) : []);
    detail=value;
    const summary=(key,title,body)=>`<details class="ledger-source" data-section="${key}" ${opened.has(key)?'open':''}><summary>${title}</summary>${body}</details>`;
    const actions=[['claim','认领'],['heartbeat','上报心跳'],['stage','更新阶段'],['release','释放认领'],['ready','信息齐备'],['block','登记阻塞'],['resume','解除阻塞'],['link','关联任务']];
    const taskRows=value.tasks.filter(task=>row.scope.some(video=>video.video_id===task.video_id&&video.targets.includes(task.locale))).map(task=>`<tr>
      <td>${h(row.videos.find(video=>video.id===task.video_id)?.title || task.video_id)}<br>${h(task.locale)}</td>
      <td>${task.runs.map(run=>`<a href="#tasks/${encodeURIComponent(run)}">${h(run)}</a>`).join('<br>') || '未开始'}</td>
      <td>${task.complete_at?dt(task.complete_at):task.active_revision?'新版制作中':'待完整输出'}
        ${row.progress_state==='blocked' && task.publication_blocked?`<span class="quiet">${tag('严重问题阻塞上传','bad')}</span>`:''}</td>
      <td>${task.current?.url?`<a href="${h(task.current.url)}" target="_blank" rel="noopener">播放成片</a>
        <span class="quiet mono">${h(task.current.sha256.slice(0,12))}</span>`:'未核验交付包'}
        <span class="quiet">${task.versions.length} 个输出版本</span></td>
    </tr>`).join('');
    const actualSeconds = row.received_at && row.first_complete_at ? (new Date(row.first_complete_at)-new Date(row.received_at))/1000 : null;
    const exceptions = [
      row.time_exclusion ? `<p><strong>耗时异常 · 已剔除效率统计</strong><br>${h(row.time_exclusion.reason)}<br>实际收件至完整输出 ${duration(actualSeconds)}。${h(row.time_exclusion.source)}</p>` : '',
      row.progress_state==='blocked' ? [
        row.publication_blocked_count ? `<p>${row.publication_blocked_count} 个语言任务有严重问题，上传受阻。</p>` : '',
        ...[row.block_reason,...(row.blockers || [])].filter(Boolean).map(reason=>`<p>${h(typeof reason==='string'?reason:JSON.stringify(reason))}</p>`),
      ].join('') : '',
    ].join('');
    const times=[['制作起始',dt(row.first_started_at)],['制作完成',dt(row.complete_at)],['审核上传完成',uploadProgress(row)]];
    node.hidden=false;
    node.innerHTML=`<div class="ledger-detail-header"><div><h2>${h(row.code)}</h2><p class="quiet ledger-title">${h(row.title)}</p></div><button data-close-requirement>收起</button></div>
      <div class="info-grid">${times.map(([label,time])=>`<div class="info"><span>${h(label)}</span><strong>${h(time)}</strong></div>`).join('')}</div>
      ${exceptions?summary('exceptions','查看异常说明',exceptions):''}
      ${row.description?summary('brief','需求原文',`<pre>${h(row.description)}</pre>`):''}
      ${summary('tasks','任务与视频',`<div class="table-wrap"><table><thead><tr><th>原片 / 语言</th><th>执行记录</th><th>当前输出</th><th>版本</th></tr></thead>
      <tbody>${taskRows || '<tr><td colspan="4">暂无关联任务</td></tr>'}</tbody></table></div>`)}
      ${summary('tracking','原片与会话',`
        <p class="ledger-caption">${h(healthLabels[row.agent_health])}${row.executors.some(executor=>executor.health==='recent')?' · 执行器近期有上报':''} · 最近产物 ${dt(row.last_activity_at)}</p>
        <p class="ledger-caption">${Object.entries(row.stage_counts || {}).map(([stage,count])=>`${h(stages[stage] || stage)} ${count}`).join(' · ')}</p>
        ${row.videos.map(video=>`<p class="ledger-caption">${h(video.title)} · ${h(video.id)} · ${h(video.source_sha256?.slice(0,12) || '原片尚未绑定')}
          ${video.thread?` · ${h(video.thread.title || '已绑定会话')}`:''}</p>`).join('')}`)}
      ${summary('evidence','平台状态与采集依据',`
        <p>平台状态 ${h(platformLabels[row.platform_status] || row.platform_status || '未记录')} · 审核上传完成 ${uploadProgress(row)} · 状态记录 ${dt(row.platform_refreshed_at)}</p>
        ${row.launch?`<p>${h(launchLabel(row.launch))} · 素材库最早核对 ${dt(row.launch.observed_at)}</p>`:''}
        <p>平台创建 ${dt(row.platform_created_at)} · 信息齐备 ${dt(row.ready_at)} · 首次发现 ${dt(row.first_seen_at)}</p>
        ${row.external.length?`<pre>${h(JSON.stringify(row.external,null,2))}</pre>`:'<p>暂无结构化提交回执。</p>'}
        <ul>${row.evidence.map(path=>`<li class="mono">${h(path)}</li>`).join('')}</ul>
        <p>预算引用 ${h(row.budget_ids.join('、') || '未绑定')} · 范围历史 ${value.scopes.length} 版</p>`)}
      ${summary('events','阶段与等待记录',value.events.filter(event=>event.kind!=='eta').map(event=>`<details class="ledger-event">
        <summary>${h(eventLabels[event.kind] || event.kind)} · ${dt(event.occurred_at || event.recorded_at)}${event.run_id?' · '+h(event.run_id):''}</summary>
        <pre>${h(JSON.stringify(event.data,null,2))}</pre></details>`).join(''))}
      ${summary('actions','台账操作',`<div class="ledger-actions">${actions.map(([action,label])=>`<button data-ledger-action="${action}">${label}</button>`).join('')}</div>`)}`;
  }

  function renderEfficiency() {
    const timing = data.historical_timing;
    const totals = [['首次完整输出',data.metrics.completed_in_period,`最近 ${data.metrics.days} 天`]];
    if (timing.requests.length) totals.push(
      ['需求平均制作耗时',duration(timing.request_mean_seconds),`${timing.requests.length} 条需求样本`],
      ['需求制作耗时中位数',duration(timing.request_median_seconds),`${timing.requests.length} 条需求样本`]
    );
    el('ledger-metrics').innerHTML = cards(totals);
    const body=el('ledger-body');
    const oldTable=el('timing-table');
    const scrollTop=oldTable?.scrollTop || 0;
    const scrollLeft=oldTable?.scrollLeft || 0;
    const tableFocused=oldTable===document.activeElement;
    const headings=['需求','开始','首次完整输出','总耗时','语种数','每种语言平均耗时'];
    const rows=timing.requests.map(row=>`<tr><td><a href="#ledger/${encodeURIComponent(row.id)}">${h(row.code)}</a></td>
      <td>${dt(row.started_at)}</td><td>${dt(row.finished_at)}</td><td>${duration(row.seconds)}</td>
      <td>${row.language_count || '—'}</td><td>${duration(row.seconds_per_language)}</td></tr>`);
    body.innerHTML=`<section class="panel timing-panel">
      <h2>已完成需求耗时</h2>
      <div id="timing-table" class="table-wrap bounded-table" role="region" aria-label="已完成需求耗时" tabindex="0">
        <table><thead><tr>${headings.map(name=>`<th scope="col">${name}</th>`).join('')}</tr></thead>
        <tbody>${rows.join('') || `<tr><td colspan="${headings.length}">所选时段暂无符合条件的耗时样本。</td></tr>`}</tbody></table>
      </div>
      <p class="quiet timing-note">每种语言平均耗时 = 需求总耗时 ÷ 去重后的目标语种数。总耗时从开始制作到首次完整输出，包含等待。时间为洛杉矶时间。</p>
    </section>`;
    const table=el('timing-table');
    table.scrollTop=scrollTop;
    table.scrollLeft=scrollLeft;
    if (tableFocused) table.focus({preventScroll:true});
  }

  function editor(action) {
    if(!detail || !data)return;
    let dialog=el('ledger-editor');
    if(!dialog){dialog=document.createElement('dialog');dialog.id='ledger-editor';dialog.className='ledger-editor';document.body.appendChild(dialog);}
    const r=detail.requirement;
    const name={claim:'认领',heartbeat:'上报心跳',stage:'更新阶段',release:'释放认领',ready:'登记信息齐备',block:'登记阻塞',resume:'解除阻塞',link:'关联已有任务'}[action];
    let fields='';
    if(['claim','heartbeat','stage','release'].includes(action))fields=`<label>原视频<select name="video_id"><option value="*">整条需求</option>${r.videos.map(v=>`<option value="${h(v.id)}">${h(v.title)}</option>`).join('')}</select></label><label>执行者<input name="owner" required maxlength="200" value="${h(owner)}" placeholder="Agent 或负责人的名称"></label><label>会话 ID<input name="session" required value="${h(session)}"></label>${action!=='release'?'<label>当前阶段<input name="stage" required placeholder="如 翻译、配音、审核"></label>':''}<p class="quiet">仅在实际工作时上报；此页面不会定时替 Agent 发送心跳。</p>`;
    if(action==='block')fields='<label>等待类型<select name="kind"><option value="user">等待用户／素材</option><option value="model">等待模型</option><option value="resource">等待资源</option><option value="platform">平台异常</option><option value="unknown">待核查</option></select></label>';
    if(action==='link')fields=`<label>原视频<select name="video_id">${r.videos.map(v=>`<option value="${h(v.id)}">${h(v.title)}</option>`).join('')}</select></label><label>语言<input name="locale" required placeholder="如 es"></label><label>已有任务 ID<input name="run_id" required></label><label>原视频完整 SHA256<input name="source_sha256" required pattern="[0-9a-f]{64}"></label><p class="quiet">校验实际任务的源哈希和语言，关联结果在下一次采集中显示。</p>`;
    dialog.innerHTML=`<div class="dialog-head"><h2>${h(name)} · ${h(r.code)}</h2><button type="button" data-close-editor>关闭</button></div><form class="ledger-form" id="ledger-edit-form">${fields}<label>原因 / 证据<textarea name="reason" required placeholder="记录实际依据或恢复说明"></textarea></label><p id="ledger-form-error" class="ledger-warning" role="alert"></p><button type="submit">保存记录</button></form>`;
    dialog.querySelector('[data-close-editor]').onclick=()=>dialog.close();
    const operation=crypto.randomUUID();
    el('ledger-edit-form').onsubmit=async e=>{
      e.preventDefault();const form=e.currentTarget;const spec=Object.fromEntries(new FormData(form));spec.requirement_id=r.id;
      if(spec.owner){owner=spec.owner;sessionStorage.setItem('ledger-owner',owner);}
      const button=form.querySelector('[type=submit]');button.disabled=true;
      try{
        await request('/api/ledger/action',{method:'POST',headers:{'Content-Type':'application/json','X-Ledger-Token':data.csrf_token},body:JSON.stringify({action,data:spec,operation_id:operation,expected_revision:r.revision})});
        dialog.close();await refresh(true);
      }catch(error){el('ledger-form-error').textContent=error.message;}finally{button.disabled=false;}
    };
    dialog.showModal();
  }

  document.addEventListener('click', e=>{
    const row=e.target.closest('[data-requirement]');
    const retryButton=e.target.closest('[data-retry-demand]');
    if (retryButton && currentPage === 'ledger') {
      const id=retryButton.dataset.retryDemand;
      retries=retries?.id===id ? null : {id,cursor:'',history:[],page:null,loading:false,error:null};
      renderTable();
      [...el('ledger-body').querySelectorAll('[data-retry-demand]')].find(button=>button.dataset.retryDemand===id)?.focus({preventScroll:true});
      if (retries) void loadRetries('');
      return;
    }
    if (retries && !retries.loading && e.target.closest('[data-retry-next],[data-retry-prev],[data-retry-reload]')) {
      if (e.target.closest('[data-retry-next]') && retries.page?.next_cursor) {
        retries.history.push(retries.cursor);
        retries.cursor = retries.page.next_cursor;
      } else if (e.target.closest('[data-retry-prev]') && retries.history.length) {
        retries.cursor = retries.history.pop();
      }
      void loadRetries(retries.cursor);
      return;
    }
    if(e.target.closest('[data-show-unlinked]')){
      filters.state=filters.state==='unlinked'?'all':'unlinked';
      filters.progress='all';
      el('ledger-state').value='all';
      refresh();
      return;
    }
    if(row){
      if(selected===row.dataset.requirement) el('ledger-detail').scrollIntoView({block:'start'});
      else location.hash='ledger/'+encodeURIComponent(row.dataset.requirement);
      return;
    }
    if(e.target.closest('[data-close-requirement]')){selected='';el('ledger-detail').hidden=true;location.hash='ledger';return;}
    const action=e.target.closest('[data-ledger-action]');if(action)editor(action.dataset.ledgerAction);
  });
  return {show,refresh};
})();
