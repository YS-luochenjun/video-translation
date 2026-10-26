'use strict';

const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const asArray = value => Array.isArray(value) ? value : [];
const date = value => value ? new Date(value).toLocaleString('zh-CN', {hour12:false}) : '未记录';
const short = value => String(value || '—').slice(0, 12);
const languages = {ar:'阿拉伯语',es:'西班牙语',pt:'葡萄牙语',de:'德语',fr:'法语',ja:'日语',ko:'韩语',en:'英语',vi:'越南语',tr:'土耳其语',th:'泰语',ru:'俄语',it:'意大利语',pl:'波兰语',hi:'印地语','zh-CN':'简体中文','zh-TW':'繁体中文'};
const qualityLabels = {pass:['质量记录通过','good'],issues:['未通过 · 有瑕疵','warn'],revise:['审核要求修正','warn'],hold:['存在质量异议','bad'],invalid:['文件或绑定异常','bad'],stale:['审核记录过期','bad'],reference:['历史参考',''],not_reviewed:['尚无有效审核','']};
const statusLabels = {reviewed:'已核对',pending:'待核对',pass:'通过',fail:'失败',failed:'失败',success:'执行成功',submitted:'已提交',generating:'生成中',waiting:'等待中',queuing:'供应商排队',ambiguous:'状态不明',needs_review:'待审核',helpful:'有帮助',ineffective:'无效',counterexample:'反例',not_used:'未采用',pending_distillation:'待提纯',retired:'现场已保全清理',deferred:'维护暂缓',completed:'已完成',closed:'已关闭',partial_adoption_recorded:'部分采纳',no_adoption_record:'无采纳记录',synthetic_only:'仅合成实验',historical_retained:'保留历史',active:'现行',candidate:'候选',superseded:'已替代'};
const label = value => statusLabels[value] || value || '未记录';
const badge = (value, kind='') => `<span class="badge ${esc(kind)}">${esc(value)}</span>`;
const qbadge = value => { const [name,kind] = qualityLabels[value] || [value,'']; return badge(name,kind); };
const empty = text => `<div class="empty">${esc(text)}</div>`;
const list = values => asArray(values).length ? `<ul class="list">${values.map(v=>`<li>${esc(typeof v === 'object' ? JSON.stringify(v) : v)}</li>`).join('')}</ul>` : '<p class="quiet">未记录</p>';
const section = (title, body, aside='') => `<div class="section-title"><h3>${esc(title)}</h3><span class="quiet">${esc(aside)}</span></div>${body}`;
const info = (name,value) => `<div class="info"><span>${esc(name)}</span><strong>${esc(value ?? '未记录')}</strong></div>`;
const documentButton = (path,title='查看正文') => path ? `<button class="table-action" data-document="${esc(path)}">${esc(title)}</button>` : '';
let snapshot = null, detail = null, catalog = null, tab = 'overview', query = '', filter = 'all', knowledgeQuery = '', knowledgeKind = 'all';
let refreshing = false, detailSequence = 0, lastSuccess = 0;

async function api(url) {
  const controller = new AbortController();
  const timer = setTimeout(()=>controller.abort(), 45000);
  try {
    const response = await fetch(url, {cache:'no-store', signal:controller.signal});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `读取失败 (${response.status})`);
    return data;
  } finally { clearTimeout(timer); }
}

function route() {
  const [page='tasks', id=''] = location.hash.slice(1).split('/');
  return {page:['tasks','knowledge','system'].includes(page) ? page : 'tasks', id:decodeURIComponent(id)};
}

function notice(message) {
  $('notice').hidden = !message;
  $('notice').textContent = message || '';
}

async function refresh(force=false) {
  if (refreshing || (!force && (!$('auto').checked || document.hidden))) return;
  refreshing = true;
  $('refresh').disabled = true;
  $('refresh').setAttribute('aria-busy','true');
  try {
    const next = await api('/api/snapshot');
    const changed = !snapshot || snapshot.revision !== next.revision;
    snapshot = next; lastSuccess = Date.now();
    $('connection').textContent = $('auto').checked ? '自动更新 · 5 秒' : '已暂停更新';
    $('connection').dataset.state = 'ok';
    $('read-time').textContent = `最近读取 ${date(next.read_at)}`;
    $('nav-count').textContent = next.stats.tasks;
    notice(next.warnings.length ? `有 ${next.warnings.length} 项记录暂不可读取。任务中的文件异常会单独标记，其他记录仍可查看。` : '');
    if (changed || force) renderPage();
    if (route().page === 'tasks') await loadDetail(false);
    if (force && route().page === 'knowledge') await loadKnowledge();
  } catch (error) {
    $('connection').textContent = '连接中断'; $('connection').dataset.state = 'error';
    notice(`${error.message}。保留最后一次读取内容${lastSuccess ? '（'+date(lastSuccess)+'）' : ''}，可点击右上角重试。`);
  } finally {
    refreshing = false; $('refresh').disabled = false; $('refresh').removeAttribute('aria-busy');
  }
}

function renderPage() {
  const {page} = route();
  const titles = {tasks:['任务与视频','查看制作进展、实际产物和仍需处理的问题。'],knowledge:['知识与调用','区分现行方法、来源案例、待验证候选和实际采用。'],system:['运行概况','查看模型分工、费用快照与维护情况。']};
  $('page-label').textContent = titles[page][0]; $('page-title').textContent = titles[page][0]; $('page-description').textContent = titles[page][1];
  document.querySelectorAll('[data-nav]').forEach(a=>a.setAttribute('aria-current', a.dataset.nav===page ? 'page' : 'false'));
  if (!snapshot) return;
  if (page==='tasks') renderTasks();
  if (page==='knowledge') renderKnowledge();
  if (page==='system') renderSystem();
}

function metrics() {
  const s = snapshot.stats;
  return `<div class="metrics">${[['任务记录',s.tasks,'含已归档'],['已有视频',s.outputs,'按任务统计'],['需要关注',s.needs_attention,'质量或记录问题'],['保留现场',s.active_records,'不代表正在执行']].map(([name,n,note])=>`<div class="metric"><span>${name}</span><strong>${n}</strong><small>${note}</small></div>`).join('')}</div>`;
}

function renderTasks() {
  const body = $('content');
  if (!document.getElementById('task-list')) {
    body.innerHTML = `<div id="metrics">${metrics()}</div><div class="toolbar"><input id="task-search" class="search" type="search" aria-label="搜索任务、语言" placeholder="搜索任务、语言或源视频" value="${esc(query)}"><select id="task-filter" aria-label="筛选任务"><option value="all">全部任务</option><option value="attention">需要关注</option><option value="outputs">已有视频</option><option value="working">尚未输出</option><option value="live">保留现场</option></select><span id="filter-count" class="quiet"></span></div><div class="task-layout"><div id="task-list" class="task-list" aria-label="任务列表"></div><article id="task-detail" class="panel">${empty('选择任务查看产物和记录')}</article></div>`;
    $('task-filter').value = filter;
    $('task-search').addEventListener('input', e=>{query=e.target.value; renderTaskList();});
    $('task-filter').addEventListener('change',e=>{filter=e.target.value; renderTaskList();});
  } else $('metrics').innerHTML = metrics();
  renderTaskList();
}

function selectedTask() { return route().id || snapshot?.tasks[0]?.id; }

function renderTaskList() {
  const filtered = snapshot.tasks.filter(t=>{
    const matches = `${t.id} ${t.target_language} ${languages[t.target_language] || ''} ${t.source_sha256}`.toLowerCase().includes(query.toLowerCase());
    return matches && (filter==='all' || filter==='attention' && ['issues','revise','hold','invalid','stale'].includes(t.quality_state) || filter==='outputs' && t.output_available || filter==='working' && !t.output_available || filter==='live' && !t.archived);
  });
  $('filter-count').textContent = `${filtered.length} / ${snapshot.tasks.length} 项`;
  const groups = new Map();
  filtered.forEach(t=>{const key=t.source_sha256 || t.id; if(!groups.has(key))groups.set(key,[]);groups.get(key).push(t);});
  let html = '';
  for (const [key,tasks] of groups) {
    html += `<div class="group-head"><span>源视频 ${esc(short(key))}</span><span>${tasks.length} 项</span></div>`;
    html += tasks.map(t=>`<button class="task-button ${selectedTask()===t.id?'selected':''}" data-task="${esc(t.id)}" aria-pressed="${selectedTask()===t.id}"><div class="task-line"><span class="locale">${esc(t.target_language)} <span>${esc(languages[t.target_language] || '')}</span></span>${badge(t.output_available?'已有视频':'制作记录',t.output_available?'blue':'')}</div><div class="task-name">${esc(t.id)}</div><div class="task-meta"><span>${esc(t.state_label)}</span><span>${t.archived?'已归档':'保留现场'}</span></div></button>`).join('');
  }
  $('task-list').innerHTML = html || empty('没有匹配的任务');
}

async function loadDetail(force) {
  const id = selectedTask();
  if (!id || !document.getElementById('task-detail')) return;
  const seq = ++detailSequence;
  try {
    const value = await api('/api/task?id='+encodeURIComponent(id));
    if (seq!==detailSequence || route().page!=='tasks' || id!==selectedTask()) return;
    const changed = force || detail?.revision!==value.revision || detail?.id!==value.id;
    detail = value;
    if (changed || !document.getElementById('detail-body')) renderDetail();
  } catch (error) {
    if (seq===detailSequence && document.getElementById('task-detail')) $('task-detail').innerHTML = empty(error.message);
  }
}

function renderDetail() {
  if (!detail || !$('task-detail')) return;
  const tabs = [['overview','视频与状态'],['instances','翻译与实例'],['knowledge','知识调用'],['execution','执行与维护'],['versions','版本']];
  $('task-detail').innerHTML = `<div class="detail-top"><h2>${esc(detail.id)}</h2><div class="detail-summary">${badge(languages[detail.target_language] || detail.target_language,'blue')}${badge(detail.state_label)}${qbadge(detail.quality_state)}${detail.mode!=='未记录'?badge(detail.mode==='fast'?'快速模式':detail.mode):''}</div><p class="detail-note">${esc(detail.brief || '此任务的原始要求未包含在当前包中。')}</p></div><div class="tabs" role="tablist" aria-label="任务详情">${tabs.map(([id,title])=>`<button role="tab" id="tab-${id}" aria-controls="detail-body" aria-selected="${tab===id}" data-tab="${id}">${title}${id==='versions'?' · '+detail.versions.length:''}</button>`).join('')}</div><div id="detail-body" class="detail-body" role="tabpanel" aria-labelledby="tab-${tab}"></div>`;
  renderDetailBody();
}

function renderDetailBody() {
  if (!detail || !$('detail-body')) return;
  document.querySelectorAll('[data-tab]').forEach(b=>b.setAttribute('aria-selected',b.dataset.tab===tab));
  $('detail-body').setAttribute('aria-labelledby','tab-'+tab);
  const d = detail;
  if (tab==='overview') {
    const player = (asset,name,id,muted) => `<div class="player"><p>${name}</p>${asset?.url ? `<video id="${id}" controls playsinline preload="metadata" ${muted?'muted':''} src="${esc(asset.url)}"></video>` : '<div class="media-empty">当前记录未提供可播放文件</div>'}</div>`;
    $('detail-body').innerHTML = `<div class="play-grid">${player(d.source,'原片','source-video',true)}${player(d.output,'当前结果','output-video',false)}</div><div class="player-controls"><button data-play="toggle">播放 / 暂停</button><button data-step="-1">前一帧</button><button data-step="1">后一帧</button><label><input id="sync" type="checkbox" checked>同步定位</label><select id="audio-select" aria-label="选择音轨"><option value="output">听当前结果</option><option value="source">听原片</option><option value="mute">全部静音</option></select></div><p class="quiet">播放器按时间定位；精确帧以导出证据与 PTS 为准。只播放一路声音。</p>${d.held?'<div class="block-note bad">此版本存在质量异议。历史通过记录不能代表当前可交付或可复用。</div>':''}<div class="block-note ${d.quality_state==='issues'?'warn':''}">${esc(d.next_action)}</div>${d.limitations.length?section('当前版本的瑕疵与限制',list(d.limitations)):''}<div class="info-grid">${info('输出与质量分别记录',d.state_label)}${info('审核范围',d.quality_scope || d.quality.scope || '未记录')}${info('源内容覆盖',Object.entries(d.coverage).map(([k,v])=>`${{visual:'画面',speech:'声音',timeline:'时间轴'}[k]} ${label(v)}`).join(' / '))}${info('记录更新时间',date(d.updated_at))}</div>${d.quality_failures.length?section('质量记录中的问题',list(d.quality_failures)):''}${d.warnings.length?section('记录读取提示',list(d.warnings)):''}${section('查看边界','<p class="quiet">此页读取现有记录和文件，不重新签署质量通过，也不代表独立审核或用户验收。</p>')}`;
    setupPlayers();
  }
  if (tab==='instances') {
    $('detail-body').innerHTML = section('画面文字',d.items.length?d.items.map(item=>`<div class="item-row"><div class="item-time">${esc(item.id)}<br>${Number(item.start||0).toFixed(2)}s<button class="jump" data-jump="${Number(item.start||0)}">定位画面</button></div><div><p>${esc(item.source_text || '未记录原文')}</p><p class="translation" dir="auto">${esc(item.target_text || '译文未记录')}</p><p class="quiet">${esc(item.text_role || '')} · ${esc(item.action || '')} · ${esc(item.reason || '')}</p></div></div>`).join(''):empty('当前记录中没有文字实例。已归档结果可能仅保留了交付所需内容。'))+section('人声片段',d.speech.length?d.speech.map(s=>`<div class="item-row"><div class="item-time">${esc(s.id)}<br>${Number(s.start||0).toFixed(2)}s</div><div><p>${esc(s.source_text || s.text || '')}</p><p class="translation" dir="auto">${esc(s.target_text || '未记录译文')}</p></div></div>`).join(''):empty('未提供人声实例；这不证明原片没有人声。'))+section('已记录的具体观察',d.observations.length?d.observations.map(v=>`<details><summary>${esc(v.path.split('/').pop())}</summary><pre>${esc(JSON.stringify(v.data,null,2))}</pre></details>`).join(''): '<p class="quiet">当前包中没有单独的问题观察文件。</p>');
  }
  if (tab==='knowledge') $('detail-body').innerHTML = knowledgeDetail(d);
  if (tab==='execution') {
    const jobRows = d.jobs.map(j=>`<tr><td class="mono">${esc(short(j.id))}<br>${esc(j.model || '未记录模型')}</td><td>${badge(label(j.state),['failed','fail','ambiguous'].includes(j.state)?'warn':'')}</td><td>${esc(j.credits_consumed ?? '未知')} / ${esc(j.estimated_credits ?? '—')}</td><td>${esc(j.error ? JSON.stringify(j.error) : '—')}</td></tr>`).join('');
    $('detail-body').innerHTML = section('模型任务',jobRows?`<div class="table-wrap"><table><thead><tr><th>任务</th><th>最近回执</th><th>实扣 / 估价</th><th>错误</th></tr></thead><tbody>${jobRows}</tbody></table></div>`:empty('当前记录没有模型任务。'))+section('Codex 视觉工作',`<div class="info-grid">${info('准备的工作包',d.codex_packets.length)}${info('登记的结果',d.codex_results.length)}</div><p class="quiet">工作包准备不代表已执行；登记结果不代表已通过质量检查。</p>`)+d.codex_results.map(r=>`<details><summary>${esc(r.stage==='image'?'图片处理':'看图识字')} · ${esc(r.method || '方法未记录')}</summary>${list(r.observations.map(o=>`${o.image}：${o.observation}`))}${list(r.limitations)}</details>`).join('')+section('维护与后续',`<div class="info-grid">${info('维护状态',label(d.maintenance.state))}${info('后续归档 / 提炼',label(d.deferred.status))}</div>${list(d.maintenance.blockers)}<p class="quiet">持久待办不表示已有后台执行器。工作台不会触发清理或关闭任务。</p>`)+section('已记录的阶段耗时',Object.keys(d.timing).length?`<div class="table-wrap"><table><thead><tr><th>阶段</th><th>次数</th><th>累计秒数（含嵌套）</th><th>失败</th></tr></thead><tbody>${Object.entries(d.timing).map(([k,v])=>`<tr><td class="mono">${esc(k)}</td><td>${v.calls}</td><td>${v.seconds.toFixed(1)}</td><td>${v.failures}</td></tr>`).join('')}</tbody></table></div>`: '<p class="quiet">没有可用的阶段耗时记录。</p>')+'<p class="quiet">阶段可能相互嵌套，不能相加为总耗时；没有新记录不代表卡死。</p>';
  }
  if (tab==='versions') $('detail-body').innerHTML = section('独立交付库中的版本',d.versions.length?d.versions.slice().reverse().map(v=>`<div class="version"><div><p>${badge(v.status==='delivered_with_issues'?'已输出 · 有瑕疵':v.status==='delivered'?'已交付':'历史参考',v.status==='delivered_with_issues'?'warn':'')} ${v.held?badge('质量异议','bad'):''}</p><p class="mono">${esc(short(v.video_sha256))} · ${esc(date(v.archived_at))}</p><p class="quiet">${v.usable?'清单与视频哈希匹配':'文件或清单绑定异常'} · ${esc(v.quality_scope || '未记录审核范围')}</p></div>${v.media.url?`<a href="${esc(v.media.url)}" target="_blank" rel="noopener">打开视频 ↗</a>`:'<span class="quiet">文件缺失</span>'}</div>`).join(''):empty('尚无独立交付包'))+'<div class="block-note">历史版本保留原始结论。带瑕疵输出、技术通过和用户验收分别记录。</div>';
}

function knowledgeDetail(d) {
  const selected = [...d.knowledge.map(e=>({...e,kind:'方法 / 政策'})),...d.source_references.map(e=>({...e,kind:'同源参考'})),...d.knowledge_advisories.map(e=>({...e,kind:'待验证提醒'}))];
  const rows = selected.map(e=>`<tr><td>${documentButton(e.path,e.title || e.id || e.path)}<br><span class="mono quiet">${esc(short(e.sha256))}</span></td><td>${esc(e.kind)}</td><td>${esc(asArray(e.requires_features).join('、') || '按范围匹配')}</td></tr>`).join('');
  let html = '<div class="block-note">检索命中、纳入计划、声明阅读和实际采用分别显示。缺少采用记录时保留“未记录”。</div>';
  html += section('当前计划冻结的知识', rows?`<div class="table-wrap"><table><thead><tr><th>条目 / 版本</th><th>类型</th><th>适用特征</th></tr></thead><tbody>${rows}</tbody></table></div>`:empty('当前记录没有冻结知识清单，不推断为从未参考知识。'));
  html += section('Codex 工作包与阅读声明',d.codex_packets.length?d.codex_packets.map(p=>`<details><summary>${esc(p.stage==='image'?'图片处理':'看图识字')}工作包 · ${p.images} 张输入 · ${p.knowledge.length} 条知识</summary>${list(p.knowledge.map(k=>`${k.id || k.path} · ${short(k.sha256)}`))}</details>`).join(''): '<p class="quiet">当前包未保留 Codex 工作包。</p>');
  html += d.codex_results.map(r=>`<details><summary>阅读声明 · ${esc(r.stage)} · ${r.knowledge_read.length} 个上下文文件</summary>${list(r.knowledge_read)}<p class="quiet">这是署名回执，不单独证明实际理解或效果。</p></details>`).join('');
  html += section('实际采用与效果反馈',d.knowledge_usage.length?d.knowledge_usage.map(u=>`<div class="info"><span>${esc(u.reviewed_by || '未记录署名')} · ${esc(u.review_type || '')} · ${u.video_sha256===d.versions.at(-1)?.video_sha256?'对应当前视频':'历史版本或候选绑定'}</span>${asArray(u.uses).map(v=>`<div class="item-row"><div>${badge(label(v.outcome),v.outcome==='helpful'?'good':v.outcome==='not_used'?'':'warn')}</div><div>${documentButton(v.path,v.selected_snapshot?.id || v.path)}<p>${esc(v.observation)}</p></div></div>`).join('')}</div>`).join(''):empty('没有读取到实际采用记录；不根据命中次数推断采用或效果。'));
  return html;
}

function setupPlayers() {
  const source = $('source-video'), output = $('output-video');
  const videos = [source,output].filter(Boolean);
  const sync = (from,playing=false) => {
    if (!$('sync')?.checked) return;
    videos.filter(v=>v!==from).forEach(v=>{
      if (Math.abs(v.currentTime-from.currentTime)>.15) v.currentTime=from.currentTime;
      if (playing) v.play().catch(()=>{});
    });
  };
  videos.forEach(v=>{
    v.addEventListener('seeked',()=>sync(v));
    v.addEventListener('play',()=>sync(v,true));
    v.addEventListener('pause',()=>{if($('sync')?.checked)videos.filter(x=>x!==v && !x.paused).forEach(x=>x.pause());});
  });
  $('audio-select').addEventListener('change',e=>videos.forEach(v=>{v.muted = v.id !== e.target.value+'-video';}));
}

async function loadKnowledge() {
  catalog = await api('/api/knowledge');
  if(route().page==='knowledge') renderKnowledge();
}

function renderKnowledge() {
  if (!catalog) { $('content').innerHTML=empty('正在读取知识索引…'); loadKnowledge().catch(e=>notice(e.message)); return; }
  if (!$('knowledge-list')) {
    $('content').innerHTML = `<div class="toolbar"><input id="knowledge-search" type="search" class="search" placeholder="搜索知识名称、适用条件或路径" aria-label="搜索知识" value="${esc(knowledgeQuery)}"><select id="knowledge-kind" aria-label="知识类别"><option value="all">全部类别</option><option value="method">方法与政策</option><option value="reference">同源参考</option><option value="candidate">候选经验</option></select></div><div class="knowledge-layout"><aside class="panel knowledge-guide"><h2>从知识到结果</h2><p>检索命中</p><p>↓ 纳入工作包 / 计划</p><p>↓ Codex 声明阅读</p><p>↓ 实际采用与效果反馈</p><hr><p>候选不会自动启用；同源多语言不能算作多个独立来源。</p><p>打开任务的“知识调用”，查看该次制作的版本和回执。</p></aside><section class="panel" id="knowledge-list" aria-label="知识条目"></section></div>`;
    $('knowledge-kind').value=knowledgeKind;
    $('knowledge-search').addEventListener('input',e=>{knowledgeQuery=e.target.value;renderKnowledgeList();});
    $('knowledge-kind').addEventListener('change',e=>{knowledgeKind=e.target.value;renderKnowledgeList();});
  }
  renderKnowledgeList();
}

function renderKnowledgeList() {
  const rows = catalog.entries.filter(e=>(knowledgeKind==='all'||e.kind===knowledgeKind)&&JSON.stringify(e).toLowerCase().includes(knowledgeQuery.toLowerCase()));
  const kinds={method:'方法 / 政策',reference:'同源参考',candidate:'候选'};
  $('knowledge-list').innerHTML = rows.length ? rows.map(e=>`<div class="knowledge-entry"><div class="entry-head"><h3>${documentButton(e.path,e.title || e.id || e.hypothesis || e.path)}</h3>${badge(kinds[e.kind],e.kind==='method'?'blue':'')}</div><p class="mono">${esc(e.id || e.path)}</p><p>${esc(e.summary || e.hypothesis || (e.scope?Object.entries(e.scope).map(([k,v])=>`${k}: ${v}`).join(' · '):'查看正文了解来源、限制和反例'))}</p><div class="chips">${badge(label(e.review_status || e.status))}${e.superseded_by?badge('已被替代','warn'):''}${asArray(e.requires_features).map(f=>badge(f)).join('')}${asArray(e.requires_any_features).map(f=>badge(f)).join('')}${e.sha256?badge(short(e.sha256)):''}</div></div>`).join('') : empty('没有匹配的知识条目');
}

function renderSystem() {
  const s=snapshot, roles={text_recognition:'文字识别',image_editing:'图片处理',asr:'真实音频转写',audio_analysis:'音频理解',separation:'人声 / 背景分离',tts:'目标语言配音',video:'视频编辑'};
  const pending=s.tasks.filter(t=>t.maintenance?.blockers?.length || t.deferred?.status==='pending');
  $('content').innerHTML = `<div class="system-grid"><section class="panel"><h2>当前模型分工</h2><div class="table-wrap"><table><tbody>${Object.entries(roles).map(([key,title])=>`<tr><td>${title}</td><td class="mono">${esc(s.routing[key] || '未配置')}</td></tr>`).join('')}</tbody></table></div><div class="block-note">${s.policy.default_delivery_mode==='fast'?'默认快速交付':'模式按任务记录'} · ${s.policy.output_policy==='best_available_required'?'达到边界仍输出最佳完整译片':'输出策略按任务记录'}。输出与质量通过分别显示。</div></section><section class="panel"><h2>本地资源</h2><div class="info-grid">${info('重任务并发上限',s.resources.max_heavy_jobs)}${info('资源锁记录',s.resources.locks.length)}</div>${list(s.resources.locks.map(l=>`${l.name} · ${l.owner}`))}<p class="quiet">${esc(s.resources.scope)}</p>${section('监控范围','<p class="quiet">自动读取 runs、outputs、state、knowledge 的规范记录。不访问 .env、不查询供应商、不运行制作、不执行维护。旧状态不是运行心跳。</p>')}</section><section class="panel"><h2>请求费用快照</h2><p class="quiet">按请求账本列出，不按语言或视频重复累加；未知费用继续保留。页面不对账。</p><div class="table-wrap"><table><thead><tr><th>请求</th><th>上限</th><th>实扣或预留</th><th>金额未知项</th></tr></thead><tbody>${s.budgets.map(b=>`<tr><td class="mono">${esc(short(b.id))}</td><td>${esc(b.limit ?? '—')}</td><td>${Number(b.reserved_or_billed).toFixed(2)}</td><td>${b.unknown}</td></tr>`).join('')}</tbody></table></div></section><section class="panel"><h2>待维护事项</h2>${pending.length?pending.map(t=>`<div class="version"><div><p>${esc(t.id)}</p><p class="quiet">${esc(label(t.maintenance?.state))} · ${esc(label(t.deferred?.status))}</p></div><button data-task="${esc(t.id)}">查看</button></div>`).join(''): '<p class="quiet">当前任务中没有读取到待维护事项。</p>'}<p class="quiet">队列持久保存，不代表存在后台执行器。已清理的现场仍可通过独立交付包查看。</p></section></div>`;
}

document.addEventListener('click',async e=>{
  const task=e.target.closest('[data-task]');
  if(task){location.hash='tasks/'+encodeURIComponent(task.dataset.task);return;}
  const targetTab=e.target.closest('[data-tab]');
  if(targetTab){tab=targetTab.dataset.tab;renderDetailBody();return;}
  const doc=e.target.closest('[data-document]');
  if(doc){
    const dialog=$('document');$('document-title').textContent=doc.textContent;$('document-text').textContent='读取中…';$('document-hash').textContent='';dialog.showModal();
    try{const d=await api('/api/document?path='+encodeURIComponent(doc.dataset.document));$('document-text').textContent=d.text;$('document-hash').textContent=d.path+' · '+short(d.sha256);}catch(error){$('document-text').textContent=error.message;}
    return;
  }
  const jump=e.target.closest('[data-jump]');
  if(jump){tab='overview';renderDetailBody();document.querySelectorAll('video').forEach(v=>{v.currentTime=Number(jump.dataset.jump);});return;}
  const control=e.target.closest('[data-play],[data-step]');
  if(control){
    const videos=[...document.querySelectorAll('video')];const primary=$('output-video') || videos[0];if(!primary)return;
    if(control.dataset.play){if(primary.paused)videos.forEach(v=>v.play().catch(()=>notice('浏览器未能播放该文件，请检查媒体格式或重新打开视频。')));else videos.forEach(v=>v.pause());}
    else{videos.forEach(v=>{v.pause();v.currentTime=Math.max(0,v.currentTime+Number(control.dataset.step)/(Number(detail.media_info.fps)||30));});}
  }
});

$('close-document').addEventListener('click',()=>$('document').close());
$('refresh').addEventListener('click',()=>refresh(true));
$('auto').addEventListener('change',()=>{$('connection').textContent=$('auto').checked?'自动更新 · 5 秒':'已暂停更新';if($('auto').checked)refresh(true);});
window.addEventListener('hashchange',()=>{detailSequence++;const r=route();if(r.page!=='tasks')detail=null;renderPage();if(r.page==='tasks'){renderTaskList();loadDetail(true);}});
setInterval(()=>refresh(),5000);
refresh(true);
