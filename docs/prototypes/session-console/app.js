'use strict';
// Deliberately offline: no fetch, WebSocket, production commands, or persisted state.
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const initialSessions = [
  {id:'demo-042',code:'DEMO-042',name:'游戏广告 · 三语本地化',state:'running',phase:3,percent:58,elapsed:'38分 24秒',eta:'约 18–32 分钟',cost:'72 / 180',langs:3,source:'演示需求 · 1条原片 · 3个语种',stage:'字层与配音制作',messages:[{who:'agent',text:'原片解析、文字清单和共用底片已完成。日语正在审核，德语制作字层，法语正在等待配音任务。'},{who:'agent',text:'下一步核对各语言实际配音与文字时轴，再检查原片、底片、译片的完整画面对照。预计还需18–32分钟，此处为演示估计。'}]},
  {id:'demo-018',code:'DEMO-018',name:'产品广告 · 两语本地化',state:'blocked',phase:4,percent:76,elapsed:'52分 10秒',eta:'等待解除后重估',cost:'86 / 120',langs:2,source:'演示需求 · 1条原片 · 2个语种',stage:'等待原任务费用核实',messages:[{who:'agent',text:'一笔模型请求同步超时，未取得可查询的任务ID。费用状态未知，保留原请求记录。对应语种等待核实，其他已具备提交条件的版本可以继续。'}]},
  {id:'demo-007',code:'DEMO-007',name:'休闲游戏 · 已完整提交',state:'done',phase:7,percent:100,elapsed:'1小时 06分',eta:'已完成（演示）',cost:'104 / 180',langs:3,source:'演示需求 · 1条原片 · 3个语种',stage:'全部语种平台读回核验',messages:[{who:'agent',text:'演示中的3个语种均已完成输出，并模拟核验入库、共享、名称、标签、归属和绑定。普通局部修复痕迹已披露；质量结论与平台提交结果分别记录。'}]},
  {id:'01a18056-0960-7800-bba1-943d025e3989',code:'知识与工作流',name:'梳理项目知识沉淀与工作流',state:'idle',snapshot:true,stage:'最近一轮完成 · 会话 idle',elapsed:'未读取台账',eta:'周期任务无整项 ETA',source:'已读取的真实会话快照 · 非实时连接',messages:[{who:'agent',text:'真实快照：最近一轮完成了排版、字体绑定、清底边界取证和必需人声检查方面的共性修复及知识沉淀。会话当前状态为 idle；这不代表历史知识待办已全部清零。'}]},
  {id:'01a17bfc-80be-7461-8f19-592fa0ef2ae3',code:'Fireplay 调度',name:'设计 Fireplay 需求自动接入方案',state:'idle',snapshot:true,stage:'两次巡检之间 · 会话 idle',elapsed:'未读取台账',eta:'巡检计划另行核验',source:'已读取的真实会话快照 · 非实时连接',messages:[{who:'agent',text:'真实快照：该会话负责发现翻译需求、接入与必要调度。最近回复记录原监控集合交齐22/23项，仍保留MOG-042原阻塞；这是读取时的历史快照，不代表平台此刻的完整状态。'}]}
];
let sessions = structuredClone(initialSessions);
let selected = sessions[0].id;
let view = 'sessions';
let detailTab = 'flow';
let selectedNode = 'production';
let selectedArtifact = 'base-b';
const artifactImages = Object.fromEntries(['source','base-a','base-b','target'].map(id=>[id,'assets/'+id+'.svg']));
const artifactData = [{id:'source',title:'原片参考帧',stage:'解析 · T+02:10',status:'基准',cls:'',note:'源视觉、主体与文字布局的对照基准。'},{id:'base-a',title:'清底候选 A',stage:'底片 · T+15:20',status:'需调整',cls:'amber',note:'示意：顶部出现矩形修复痕迹，需调整清底方向。'},{id:'base-b',title:'清底候选 B',stage:'底片 · T+23:10',status:'待实审',cls:'blue',note:'示意：去除源文字并保留背景与主体，等待实际运动复核。'},{id:'target',title:'日语字层预览',stage:'字层 · T+34:00',status:'候选 · 非终稿',cls:'green',note:'静帧示意：目标文字、层级与CTA；配音、运动和整片效果待审。'}];
let filter = 'all';
let search = '';
const SESSION_PAGE_SIZE = 8;
let sessionPage = 1;
const drafts = new Map();
let simulate = false;
let simulationTimer;
let toastTimer;
let demoStep = 0;
let automations = [{name:'Fireplay 需求巡检',icon:'◷',cadence:'每 30 分钟',scope:'全部可见组，执行人包含邹彬；新增且正文明确翻译。',owner:'设计 Fireplay 需求自动接入方案',time:'下一次：以真实调度回执为准',enabled:true},{name:'项目经验总结',icon:'◇',cadence:'每天 18:00 · 上海',scope:'审查新观察、用户反馈与反例；候选与正式知识分开。',owner:'梳理项目知识沉淀与工作流',time:'洛杉矶同日 02:00 PST / 03:00 PDT',enabled:true},{name:'项目存储整理',icon:'▱',cadence:'每天 18:30 · 上海',scope:'预览到期包，核对保全、活动锁与当前指纹后整理。',owner:'独立维护任务',time:'洛杉矶同日 02:30 PST / 03:30 PDT',enabled:true}];
const autoLog = [];
const curated = [];
const labels = {running:'制作中',blocked:'待处理',done:'已提交',idle:'快照 · idle',queued:'已排队'};
const stateClass = state => ({running:'green',blocked:'amber',done:'green',idle:'blue',queued:''}[state] || '');
const current = () => sessions.find(s => s.id === selected);
const badge = (text, cls='') => `<span class="badge ${cls}">${esc(text)}</span>`;

function toast(text) { clearTimeout(toastTimer); $('#toast').textContent = text; $('#toast').classList.add('show'); toastTimer = setTimeout(()=>$('#toast').classList.remove('show'),4000); }
function pageHead(title,sub,buttons='') { return `<div class="page-head"><div><div class="eyebrow">PROJECT CONTROL CENTER</div><h1>${title}</h1><p>${sub}</p></div><div class="actions">${buttons}</div></div>`; }
function render() {
  $$('.nav').forEach(el=>el.classList.toggle('active',el.dataset.nav===view));
  $('#breadcrumb-current').textContent={sessions:'会话总览',automations:'自动任务',knowledge:'经验与知识',plan:'接入方案'}[view];
  $('#nav-count').textContent=sessions.length;
  $('#main').innerHTML=({sessions:renderSessions,automations:renderAutomations,knowledge:renderKnowledge,plan:renderPlan}[view])();
}
function $$(selector) { return [...document.querySelectorAll(selector)]; }
function renderSessions() {
  const s=current();
  return pageHead('所有会话，一个工作台。','从接单到交付，查看每一步，也直接参与每一步。',`<button class="btn" data-action="simulation">${simulate?'Ⅱ 暂停模拟':'▷ 播放进度模拟'}</button><button class="btn primary" data-action="intake">＋ 按编号接单</button>`)+
  `<div class="stats"><div class="stat"><span class="stat-icon">▦</span><div class="stat-label">当前制作 · 演示</div><div class="stat-value">${sessions.filter(s=>s.state==='running'||s.state==='queued').length}<small>个会话</small></div><div class="stat-foot">会话与语种分别查看</div></div><div class="stat warn"><span class="stat-icon">⊙</span><div class="stat-label">需要关注 · 演示</div><div class="stat-value">${sessions.filter(s=>s.state==='blocked').length}<small>个阻塞</small></div><div class="stat-foot">查看原因、影响与下一步</div></div><div class="stat"><span class="stat-icon">↗</span><div class="stat-label">完整提交 · 演示</div><div class="stat-value">${sessions.filter(s=>s.state==='done').length}<small>项需求</small></div><div class="stat-foot">全部原片 × 目标语种</div></div><div class="stat"><span class="stat-icon">◷</span><div class="stat-label">自动任务 · 演示开关</div><div class="stat-value">${automations.filter(a=>a.enabled).length}<small>/ 3</small></div><div class="stat-foot">真实调度状态尚未接入</div></div></div>
  <div class="console-grid"><section class="panel"><div class="panel-head"><h3>项目会话</h3><small>${sessions.length} 个</small></div><div class="session-tools"><input class="search" id="session-search" aria-label="搜索会话" placeholder="⌕  搜索编号或会话…" value="${esc(search)}"><div class="filters">${[['all','全部'],['running','进行中'],['blocked','待处理']].map(([id,name])=>`<button class="filter ${filter===id?'active':''}" data-filter="${id}">${name}</button>`).join('')}</div></div><div class="session-list" id="session-list">${renderSessionList()}</div><div class="session-pagination" id="session-pagination">${renderSessionPager()}</div><div class="list-foot">${sessions.filter(s=>!s.snapshot).length} 个模拟会话 + 2 个真实会话静态快照</div></section><section class="panel" id="session-detail">${renderDetail(s)}</section><aside class="panel chat" id="session-chat">${renderChat(s)}</aside></div>
  <div class="below"><span><strong>◉ 进度有来源</strong>　节点完成以证据为准；会话空闲、文件输出、质量通过与平台交齐分别记录。</span><button class="text-btn" data-nav="plan">查看接入方案 ↗</button></div>`;
}
function filteredSessions() {
  return sessions.filter(s=>(filter==='all'||s.state===filter||(filter==='running'&&s.state==='queued'))&&`${s.code} ${s.name}`.toLowerCase().includes(search.toLowerCase()));
}
function sessionPageInfo() {
  const total=filteredSessions().length;
  const pages=Math.max(1,Math.ceil(total/SESSION_PAGE_SIZE));
  sessionPage=Math.max(1,Math.min(sessionPage,pages));
  return {total,pages,start:(sessionPage-1)*SESSION_PAGE_SIZE};
}
function renderSessionPager() {
  const {total,pages,start}=sessionPageInfo();
  return `<div class="session-page-meta">${total?`${start+1}–${Math.min(start+SESSION_PAGE_SIZE,total)} / ${total} 个`:'0 个匹配'} · 每页最多 8 个</div><div class="session-page-actions"><button class="btn" data-session-page="${sessionPage-1}" ${sessionPage===1?'disabled':''} aria-label="上一页会话">← 上一页</button><span>第 ${sessionPage} / ${pages} 页</span><button class="btn" data-session-page="${sessionPage+1}" ${sessionPage===pages?'disabled':''} aria-label="下一页会话">下一页 →</button></div>`;
}
function refreshSessionList() {
  $('#session-list').innerHTML=renderSessionList();
  $('#session-pagination').innerHTML=renderSessionPager();
  $('#session-list').scrollTop=0;
}
function renderSessionList() {
  const {start}=sessionPageInfo();
  const list=filteredSessions().slice(start,start+SESSION_PAGE_SIZE);
  return list.length?list.map(s=>`<button class="session ${s.id===selected?'selected':''}" data-session="${esc(s.id)}"><div class="session-top"><span class="session-code">${esc(s.code)}</span>${badge(labels[s.state],stateClass(s.state))}</div><div class="session-name">${esc(s.name)}</div><div class="session-meta"><span>${esc(s.stage)}</span>${s.snapshot?'':`<span>${s.percent}%</span>`}</div>${s.snapshot?'':`<div class="bar"><i style="width:${s.percent}%"></i></div>`}</button>`).join(''):'<div class="empty">没有匹配的会话</div>';
}
function renderDetail(s) {
  if(s.snapshot) return renderSnapshot(s);
  return `<div class="detail-top"><div class="detail-title"><h2>${esc(s.code)} <span class="muted small">/ ${s.langs} 语</span></h2>${badge(labels[s.state],stateClass(s.state))}</div><div class="detail-meta"><span>${esc(s.source)}</span><span>快速交付 · 第1轮</span></div><div class="progress-info"><span>${s.state==='done'?'平台完整性已模拟核验':esc(s.stage)}</span><strong>${s.percent}% <span class="muted">节点进度示意</span></strong></div><div class="bar"><i style="width:${s.percent}%"></i></div><div class="detail-meta"><span>◷ 已历时 ${esc(s.elapsed)}</span><span>↗ ${esc(s.eta)}</span></div></div>
  <div class="detail-tabs">${[['flow','任务流程'],['artifacts','阶段产物'],['locales','语种进度'],['events','活动记录'],['evidence','耗时 / 证据']].map(([id,name])=>`<button class="tab ${detailTab===id?'active':''}" data-detail-tab="${id}">${name}</button>`).join('')}</div>
  ${{flow:renderFlow,artifacts:renderArtifacts,locales:renderLocales,events:renderEvents,evidence:renderEvidence}[detailTab](s)}`;
}
function renderArtifactStrip(s) {
  if(s.phase<2)return '';
  return `<div class="artifact-strip"><div class="artifact-strip-head"><strong>最新阶段产物 <span class="muted">· 示意图片</span></strong><button class="text-btn" data-detail-tab="artifacts">查看对比 ↗</button></div><div class="artifact-thumbs">${artifactData.filter(a=>a.id!=='base-a').map(a=>`<button data-open-artifact="${a.id}"><img src="${artifactImages[a.id]}" alt="${a.title}，演示示意帧"><span>${a.title}</span></button>`).join('')}</div></div>`;
}
function renderArtifacts(s) {
  if(s.phase<2)return '<div class="empty">当前还没有阶段产物。正式版在真实文件生成后显示，不预先标记成功。</div>';
  const a=artifactData.find(a=>a.id===selectedArtifact);
  return `<div class="artifact-content"><div class="artifact-intro">每一张中间图都关联节点、版本和反馈。以下为手绘示意帧，未调用模型，不是本项目真实产物。</div><div class="artifact-grid">${artifactData.map(a=>`<button class="artifact-card ${selectedArtifact===a.id?'chosen':''}" data-select-artifact="${a.id}"><img src="${artifactImages[a.id]}" alt="${a.title}，示意图"><span class="artifact-card-body"><strong>${a.title}</strong>${badge(a.status,a.cls)}<small>${a.stage}</small></span></button>`).join('')}</div><div class="artifact-inspect"><div class="card-top"><strong>${a.title} <span class="muted">· v${a.id==='base-b'?'2':'1'}</span></strong><button class="text-btn" data-open-artifact="${a.id}">原片对比 / 大图 ↗</button></div><p>${a.note}</p><p class="small muted">演示需求：${esc(s.code)} · 原片01 · ${a.id==='target'?'JA 语种':'共用资产'} · 仅静帧预览</p><div class="actions"><button class="btn" data-artifact-feedback="请调整这个候选的方向，并与原片重新对比。">要求调整方向</button><button class="btn primary" data-artifact-feedback="请沿用这个候选继续制作，其余质量检查照常完成。">沿用候选继续 →</button></div></div><div class="notice">正式版同时提供图片大图、候选视频播放与配音试听；预览绑定真实产物哈希，过期或缺失明确标记。看到候选不等于通过审核。</div></div>`;
}
function openArtifact(id) {
  selectedArtifact=id;const a=artifactData.find(a=>a.id===id);const s=current();
  $('#artifact-dialog-title').textContent='阶段产物对比';
  $('#artifact-dialog-body').innerHTML=`<p class="muted small">${esc(s.code)} · 原片01 · ${esc(a.title)} · 示意图，不是真实模型结果</p><div class="artifact-compare"><figure><img src="${artifactImages.source}" alt="原片参考帧，示意图"><figcaption>原片基准 · 源文字与主体</figcaption></figure><figure><img src="${artifactImages[a.id]}" alt="${a.title}，示意图"><figcaption>${a.title} · ${a.status}</figcaption></figure></div><p class="muted">${a.note}</p><div class="notice">画面为静态示意。正式版还需视频运动与声音证据，静帧不能证明整片质量。</div><div class="actions"><button class="btn" data-artifact-feedback="请调整这个候选的方向，并与原片重新对比。">要求调整方向</button><button class="btn primary" data-artifact-feedback="请沿用这个候选继续制作，其余质量检查照常完成。">沿用候选继续 →</button></div>`;
  if(!$('#artifact-dialog').open)$('#artifact-dialog').showModal();
}
function openNodeOutputs(s,id) {
  const nodes={
    intake:{title:'接单与范围冻结',ready:s.phase>=1,images:[],records:[['范围快照（示例）',`原片01 · ${s.langs}个目标语种 · ${s.code}`],['会话与预算绑定（示例）','复用当前会话与请求账本；无真实平台写入。']]},
    analysis:{title:'内容解析与源样式',ready:s.phase>=2,images:['source'],records:[['逐实例清单（示例）','主标题 / CTA / 人声轮次 / 源样式与保护区。']]},
    base:{title:'共用底片与选路',ready:s.phase>=3,images:['base-a','base-b'],records:[]},
    ja:{title:'日语 · 字层与审核',ready:s.phase>=3,images:['target'],records:[['审核状态（示例）','已生成静帧候选；实际配音、运动与整片效果尚待实审。']]},
    production:{title:'德语 · 字层合成',ready:false,images:[],pending:'德语字层正在合成，当前没有可展示的德语候选图片。生成后会出现在这个节点；不会拿其他语言的图片代替。'},
    fr:{title:'法语 · 配音与字层',ready:false,images:[],pending:'当前等待法语配音，尚无音轨或译文字层产物。正式版有真实音轨后可在此试听。'},
    review:{title:'整幅对照与有界修复',ready:s.phase>=5,images:['source','base-b','target'],records:[['对照审查记录（示例）','原片 / 底片 / 日语字层静帧已关联；不代表真实整片质量通过。']]},
    output:{title:'完整输出与提交审查',ready:s.phase>=6,images:[],records:[['完整输出记录（示例）','正式版在此播放当前确切版本的完整视频，展示哈希及提交资格；本演示无真实MP4。']]},
    publication:{title:'平台回传与整项结案',ready:s.phase>=7,images:[],records:[['平台核验记录（示例）','入库、共享、标签、设计师归属与绑定逐项读回；本演示没有真实平台回执。']]}
  };
  const n=nodes[id];if(!n)return;
  $('#artifact-dialog-title').textContent=n.title+' · 节点产物';
  const imageCards=n.ready?n.images.map(imageId=>{const a=artifactData.find(a=>a.id===imageId);return `<button class="artifact-card" data-open-artifact="${a.id}"><img src="${artifactImages[a.id]}" alt="${a.title}，节点示意产物"><span class="artifact-card-body"><strong>${a.title}</strong>${badge(a.status,a.cls)}<small>${a.stage} · 点击大图对比</small></span></button>`;}).join(''):'';
  $('#artifact-dialog-body').innerHTML=`<p class="muted small">${esc(s.code)} / 原片01 · 仅显示这个节点的产物 · 演示数据</p>${n.ready?`${imageCards?`<div class="artifact-grid node-output-images">${imageCards}</div>`:''}${n.records.map(([title,body])=>`<article class="node-output-record"><strong>${esc(title)}</strong><p>${esc(body)}</p>${badge('示例记录 · 非真实回执')}</article>`).join('')}`:`<div class="node-output-empty"><span>◷</span><h3>当前暂无节点产物</h3><p>${esc(n.pending||'这个节点尚未完成。产物生成后在此展示，未生成的结果不会提前标记成功。')}</p></div>`}<div class="notice">图片和记录均为演示示意。正式版按节点关联真实图片、视频、音轨、文档与审核记录，并标明版本、生成状态和时间。</div>`;
  $('#artifact-dialog').showModal();
}
function node(s,id,title,desc,index,tail='',override='') {
  const state=override||(s.phase>index?'done':s.phase===index?'running':'waiting');
  const icon=state==='done'?'✓':state==='running'?'◌':String(index+1).padStart(2,'0');
  return `<button class="flow-node ${state} ${selectedNode===id?'selected-node':''}" data-node="${id}"><span class="node-icon">${icon}</span><span><strong>${title}</strong><small>${desc}</small></span><span class="node-right">${(state==='done'&&tail)||({done:'已完成',running:'进行中',waiting:'未开始'}[state])}</span></button>`;
}
function renderFlow(s) {
  return `${renderArtifactStrip(s)}<div class="flow-area"><div class="flow-caption"><span>执行路径 · 点击节点查看详情</span><span class="legend"><span><i style="background:#8fa876"></i>完成</span><span><i style="background:#4f7e3a"></i>当前</span><span><i style="background:#d7dfcf"></i>待执行</span></span></div>
  ${node(s,'intake','接单与范围冻结','真实需求 → 原片 / 语种 → 复用会话',0,'02:10')}<div class="flow-line"></div>
  ${node(s,'analysis','内容解析与源样式','文字 / 人声清单 · 水印与保护区',1,'06:40')}<div class="flow-line"></div>
  ${node(s,'base','共用底片与选路','困难区域验证 → 多语言共享资产',2,'14:20')}<div class="flow-line"></div>
  <div class="branches">${node(s,'ja','日语 JA','配音 → 字层 → 实审',3,'',s.phase>=5?'done':s.phase>=3?'running':'waiting')}${node(s,'production','德语 DE','真实字体 · 字层合成',3)}${node(s,'fr','法语 FR','等待配音 → 字层',4)}</div><div class="flow-line"></div>
  ${node(s,'review','整幅对照与有界修复','原片 / 底片 / 译片 · 声音与时轴',4)}<div class="flow-line"></div>
  ${node(s,'output','完整输出与提交审查','最佳完整成片 · 版本哈希绑定',5)}<div class="flow-line"></div>
  ${node(s,'publication','平台回传与整项结案','入库 → 共享 → 标签 → 绑定 → 全量核验',6)}
  </div><div class="node-detail" id="node-detail">${nodeDescription(s,selectedNode)}</div>`;
}
function nodeDescription(s,id) {
  const info={intake:['接单与范围冻结','正式接入将核对精确UUID、已有聊天、原请求和预算，不重复创建。','来源：request.json / 会话绑定'],analysis:['内容解析与源样式','逐实例记录画面文字、人声、运动与源字体样式；缺证据保持 pending。','来源：inventory.json / style-capture'],base:['共用底片与选路','先验证代表性困难区域，再扩展多语言。共用底片通过取证不代表各目标语审核通过。','来源：work-packet / 三路对照'],production:['德语 · 字层合成','当前示例：按源样式绑定真实字体，校对译文宽度、描边、阴影与最终配音时轴。','演示子任务：DE-typography · 预计 4–7 分钟'],ja:['日语 · 当前审核','本分支演示实际音画同步与边界帧检查。其他语言可以并行推进。','示例状态：审核中 · 没有真实成片'],fr:['法语 · 等待配音','仅此语言等待模型；整项需求仍有其他工作，不记为整项停工。','示例状态：模型等待 · 非真实taskId'],review:['整幅对照与有界修复','正常播放听审，结合源 / 无字底片 / 译片取证；最多两轮返工，完整输出与质量结论分开。','来源：review / quality / improvement_loop'],output:['完整输出与提交审查','审核必须绑定当前视频哈希。普通瑕疵披露后可有界交付，严重漏译、缺必需配音仍阻断对应版本。','来源：deliver / finalize / publication-review'],publication:['平台回传与整项结案','全部原片×全部目标语种入库、共享、标签、归属与绑定读回，completion-check 后结案。YouTube后处理交平台。','来源：真实平台回执 / fireplay-close']}[id]||['节点详情','选择流程节点查看。',''];
  return `<strong>↳ ${info[0]}</strong><p>${info[1]}</p><p class="tiny-code">${info[2]}</p>`;
}
function renderLocales(s) {
  const rows=s.state==='done'?[['日语 JA','已审核','有瑕疵披露','已核验'],['德语 DE','已审核','通过','已核验'],['法语 FR','已审核','通过','已核验']]:[['日语 JA','审核中','待实审','未提交'],['德语 DE','字层制作','待实审','未提交'],['法语 FR','等待配音','待实审','未提交']];
  return `<div class="hint-row">示例原片 01 · 视频 / 语种矩阵 · ${s.langs}个目标语种</div><div class="table-wrap"><table class="locale-table"><thead><tr><th>语种</th><th>当前阶段</th><th>质量</th><th>平台</th></tr></thead><tbody>${rows.slice(0,s.langs).map(r=>`<tr>${r.map(c=>`<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div><div class="notice" style="margin:18px">输出、质量和平台回传是三个维度；某语种等待，不阻断其他可提交语种。</div>`;
}
function renderEvents(s) {
  return `<div class="timeline">${[['T+00:00','接单：冻结原片与语种矩阵，绑定请求账本。'],['T+02:10','完成内容解析，登记文字 / 人声逐实例清单。'],['T+08:50','困难区域验证后，采用共用底片。'],['T+23:10','进入多语种配音与字层制作。'],['当前',s.stage],...s.messages.filter(m=>m.who==='user').map(m=>['本地演示输入',m.text])].map(([t,text])=>`<div class="event"><time>${esc(t)} · 模拟记录</time><p>${esc(text)}</p></div>`).join('')}</div>`;
}
function renderEvidence(s) {
  return `<div class="snapshot"><h3>时间与费用 · 演示值</h3><table class="locale-table"><tbody><tr><td>收件后历时</td><td>${esc(s.elapsed)}</td></tr><tr><td>执行器区间并集</td><td>25分 10秒</td></tr><tr><td>明确等待区间</td><td>8分 00秒（可与执行器重叠）</td></tr><tr><td>未分类区间</td><td>12分 04秒</td></tr><tr><td>已知费用 / 请求池</td><td>${esc(s.cost)} credits</td></tr><tr><td>未知费用</td><td>${s.state==='blocked'?'1 笔 · 保留核实':'0 笔（模拟）'}</td></tr></tbody></table><p>ETA：${esc(s.eta)}。此处按阶段剩余工作演示，未用项目真实样本校准，不能当作工时承诺。</p><p>正式版显示每项数据的 observed_at、证据路径、内容版本与哈希；失联显示过期，不继续伪造进度。</p><div class="notice">上述区间有重叠，不能逐项相加为总工时。读取会话不计作 Agent 实际工作心跳。</div></div>`;
}
function renderSnapshot(s) {
  return `<div class="detail-top"><div class="detail-title"><h2>${esc(s.code)}</h2>${badge('真实快照','blue')}</div><div class="detail-meta">${esc(s.source)}</div></div><div class="snapshot"><h3>${esc(s.name)}</h3><p>${esc(s.messages[0].text)}</p><div class="snapshot-flow"><span>唤醒 / 人工输入</span>→<span>执行当前轮任务</span>→<span>保存回执 / 等待下轮</span></div><p><b>会话状态：</b>读取时 idle。会话空闲与需求整项完成分别判断。</p><p><b>业务进度：</b>此演示未读取该会话的完整台账，不生成百分比或剩余时间。</p><p><b>关联标识：</b><code>${esc(s.id)}</code></p><div class="notice">此处仅为已核验会话的静态摘要。右侧输入依然只作本地模拟，不会触发原会话。</div><button class="btn" data-nav="automations">查看自动任务设计 →</button></div>`;
}
function renderChat(s) {
  return `<div class="panel-head"><h3>会话指令</h3>${badge('本地模拟')}</div><div class="chat-target">发送目标 <b>${esc(s.snapshot?s.name:s.code)}</b><span>${esc(s.snapshot?s.id:'演示 thread · '+s.id)}</span></div><div class="chat-messages" id="chat-messages">${s.messages.map(renderMessage).join('')}</div><div class="chat-prompts"><button class="prompt-chip" data-prompt="请说明当前阻塞和下一步。">查看阻塞</button><button class="prompt-chip" data-prompt="请继续当前任务，复用已有结果。">继续当前任务</button><button class="prompt-chip" data-prompt="请总结本次新增经验及适用范围。">总结经验</button></div><form class="composer" id="chat-form" data-target="${esc(s.id)}"><div class="composer-box"><textarea id="chat-input" aria-label="发送到当前会话的指令" placeholder="输入给这个会话的指令…" maxlength="5000">${esc(drafts.get(s.id)||'')}</textarea><div class="composer-bottom"><span>⌘ / Ctrl + Enter 发送</span><button class="send" type="submit">模拟发送 ↑</button></div></div></form><p class="chat-note">正式版收到会话回执后才标记“已送达”</p>`;
}
function renderMessage(m) { return `<div class="message ${m.who==='user'?'user':''}"><div class="message-label"><span class="mini-avatar">${m.who==='user'?'Y':'C'}</span>${m.who==='user'?'你 · 本地输入':m.who==='system'?'演示系统 · 未发送':'Codex · 摘要'}</div><div class="message-body">${esc(m.text)}</div></div>`; }
function renderAutomations() {
  return pageHead('让例行工作，可见可控。','统一查看计划、当前轮节点、上次回执与下一次触发。',`<button class="btn primary" data-action="curate">↗ 立即总结经验</button>`)+
    `<p class="section-intro">以下节奏来自项目文档；运行开关和执行记录为交互模拟，未核验本机当前调度。正式版接管已有任务，不再新增一套重复轮询。计划原时区为上海，界面同时按你的洛杉矶时区显示。</p><div class="card-grid">${automations.map((a,i)=>`<article class="panel auto-card"><div class="card-top"><div class="auto-icon">${a.icon}</div><button class="toggle ${a.enabled?'':'off'}" data-toggle="${i}" role="switch" aria-checked="${a.enabled}" aria-label="模拟${a.enabled?'暂停':'恢复'}${a.name}"></button></div><h3>${a.name}</h3><p>${a.scope}</p>${badge(a.enabled?'演示计划开启':'演示计划暂停',a.enabled?'green':'')}<dl class="auto-details"><dt>触发节奏</dt><dd>${a.cadence}</dd><dt>负责入口</dt><dd>${a.owner}</dd><dt>运行状态</dt><dd>未连接 · 不推断已执行</dd><dt>时间说明</dt><dd>${a.time}</dd></dl><div class="actions"><button class="btn" data-run-auto="${i}">模拟执行一轮</button><button class="btn" data-auto-owner="${i}">查看负责会话</button></div></article>`).join('')}</div><section class="panel wide-panel"><div class="panel-head"><h3>本地模拟操作记录</h3><small>手动触发不改变计划</small></div><div class="table-wrap"><table class="data-table"><thead><tr><th>任务</th><th>动作</th><th>结果</th><th>生产影响</th></tr></thead><tbody>${autoLog.length?autoLog.map(r=>`<tr><td>${esc(r[0])}</td><td>${esc(r[1])}</td><td>${badge('已在页面模拟','green')}</td><td>无</td></tr>`).join(''):'<tr><td colspan="4" class="empty">尚无操作。点击“模拟执行一轮”查看效果。</td></tr>'}</tbody></table></div></section><div class="below"><strong>每项只保留一个调度入口</strong><span>电脑休眠 / 应用关闭 / 服务断连时显示漏跑或离线，不标记成功。</span></div>`;
}
function renderKnowledge() {
  return pageHead('把一次经验，变成下一次能力。','观察有来源，结论有边界，待补证也能清楚地保留。',`<button class="btn primary" data-action="curate">＋ 发起总结</button>`)+
  `<div class="knowledge-grid"><section class="panel"><div class="panel-head"><h3>经验审查队列 · 示例</h3>${badge('3 条示意')}</div>${[['待补证','amber','共用底片的短暂残字','需要源片、清底、译片的同源连续边界证据。'],['待审查','','字体测量与编码后裁字','实际字体 / 字重绑定，检查描边、阴影与最终画面。'],['范围受限','blue','同源多语种复用','解析观察可以复用，译文、声音、时轴和审核独立建立。']].map((r,i)=>`<article class="knowledge-item">${badge(r[0],r[1])}<h3>${r[2]}</h3><p>${r[3]}</p><button class="text-btn" data-knowledge="${i}">查看来源与结论 →</button></article>`).join('')}</section><section class="panel"><div class="panel-head"><h3>审查工作区</h3><small>演示 · 不发布真实规则</small></div><div class="review-detail" id="knowledge-detail">${knowledgeDetail(0)}</div></section></div><section class="panel wide-panel"><div class="panel-head"><h3>总结任务记录</h3><small>正式版关联原会话与实际执行回执</small></div>${curated.length?curated.map(t=>`<div class="knowledge-item"><h3>${esc(t)}</h3><p>状态：本地演示排队。未运行知识提炼、未修改规则。</p></div>`).join(''):'<div class="empty">尚未发起演示总结。可按需求、会话或指定时间范围总结。</div>'}</section>`;
}
function knowledgeDetail(index) {
  const rows=[['共用底片的短暂残字','源清底前后出现极短残字，静态概览可能漏检。','增加源区间前后原生帧取证；对照不能证明的结论保留待补证。'],['字体测量与编码后裁字','配置字体可加载、字形齐全，不等于编码后文本没有裁边。','检查实际字体字面、描边和阴影占用；审查最终编码画面。'],['同源多语种复用','共用底片中的瑕疵可能传播到多个目标语言。','复用源解析与已验证资产；各目标语定稿、时轴与质量分别审核。']][index];
  return `<span class="eyebrow">EVIDENCE → CANDIDATE → REVIEW</span><h2 style="margin-top:10px">${rows[0]}</h2><p><b>观察：</b>${rows[1]}</p><p><b>候选动作：</b>${rows[2]}</p><p><b>适用边界：</b>此处仅展示审查逻辑，不能代替逐片效果验证。</p><ul><li>关联源会话、源片与产物哈希</li><li>保留失败、反例及未知项</li><li>公司偏好与默认规则变更保留明确确认</li></ul><div class="review-actions"><button class="btn" data-review="补证待办">模拟保留补证</button><button class="btn primary" data-review="采纳候选记录">模拟记录审查</button></div><div id="review-result"></div>`;
}
function renderPlan() {
  return pageHead('可实现。先打通，再统一入口。','复用现有工作台和制作链路，新增会话桥接与插件外壳。')+
  `<section class="panel"><div class="panel-head"><h3>建议架构</h3>${badge('本地优先','green')}</div><div class="architecture"><div class="arch-block"><strong>一个项目控制界面</strong><p>会话总览 / 动态流程图<br>输入指令 / 按号接单 / 自动任务</p></div><div class="arch-arrow">⇄</div><div class="arch-block"><strong>本地桥接与事件聚合</strong><p>会话适配器 / SSE推送<br>指令回执 / 去重 / 断线恢复</p></div><div class="arch-arrow">⇄</div><div class="arch-block"><strong>现有真实执行体系</strong><p>Codex 会话 / 台账 / work-packet<br>Fireplay / 模型任务 / 交付回执</p></div></div></section>
  <div class="milestones"><div class="milestone"><b>PHASE 00 · 当前</b><h3>交互原型</h3><p>验证布局、流程、指令和快捷操作的使用方式。</p></div><div class="milestone"><b>PHASE 01</b><h3>真实只读进度</h3><p>分页枚举全部项目会话，聚合台账和版本证据。</p></div><div class="milestone"><b>PHASE 02</b><h3>会话双向控制</h3><p>验证原会话可靠收信、执行中追加、空闲时续作。</p></div><div class="milestone"><b>PHASE 03</b><h3>插件与动作中心</h3><p>按号接单、经验总结、调度管理和恢复性验收。</p></div></div>
  <section class="panel"><div class="plan-content"><h3>1. 会话如何完整覆盖</h3><p>以项目ID、规范化工作区路径及宿主标识确定范围；分页读取活动、旧会话与归档记录。非制作会话也保留，无法映射阶段时显示“未上报”，不猜进度。旧资料只读接入，不自动重做。</p><h3>2. 流程如何可信</h3><p>统一 requirement → source video → locale → run → output hash → platform receipt 的关联。节点保留状态、开始/更新时间、证据引用、阻塞原因、下一步。清底和配音可并行；返工回到对应节点，并保存轮次。Agent自报、技术校验、独立审核和用户验收分别显示。</p><h3>3. 实时与预计时间</h3><p>会话事件通过本地适配器推送到页面；台账和任务文件作为补充采集。界面显示最近同步时间、断线和过期状态。耗时区分已历时、执行器占用、明确等待及未分类；ETA显示上下界、预测时间、依据、样本量和假设。样本不足标记“未校准”，遇到未知费用或用户等待显示暂无法预测。不会用节点百分比机械换算剩余时间。</p><h3>阶段产物与方向反馈</h3><p>图片、配音、候选视频生成后即可出现，不等最终交付。按节点和时间组织产物，显示版本、来源、语种、生成状态、审核结论与真实哈希。提供源片/清底/译片对比、视频播放、音轨试听及必要连续边界。用户选中某个产物后输入反馈，指令附带该版本和反馈范围；旧版本保留可比，缺失或到期不伪装可预览。调整方向影响哪些语种、需要多少返工和是否新增费用也应可见。</p><h3>4. 页面输入如何到达原会话</h3><p>发送时固定 hostId / threadId，记录 command_id、目标、输入原文、状态和回执。执行中的会话追加输入，空闲会话续作。超时保留 unknown 并查询原回执，不盲目重发。读取状态不会触发模型，也不会替工作会话续写假心跳。桌面已有会话与本地 app-server 的跨客户端控制必须先做真实联调，不能假设另启进程就能控制桌面正在运行的 turn。</p><h3>5. 按编号接单与例行任务</h3><p>手动输入编号 → Fireplay精确查询 → 原片/语种/权限与歧义核查 → 已有会话去重 → 复用或新建编号会话 → 沿本请求预算开工。手工交办独立于自动发现过滤规则，仍遵守明确授权和范围。已有巡检、知识和存储任务原位接入；暂停调度与停止正在制作的任务分开操作。知识总结可按会话、需求或日期发起，候选不会直接变成新默认规则。</p><h3>6. 插件交付方式与边界</h3><p>核心为可独立运行的本地控制台，复用现有 workbench 服务。通过 MCP 工具暴露会话、阶段和动作，再封装成项目插件；支持时使用 MCP Apps 或宿主侧栏扩展作为唯一入口。具体当前客户端的侧栏常驻、事件订阅和跨会话写入需要能力探测；若宿主入口有限，同一界面先在内置浏览器运行。不要把本聊天可用的工具默认当作网页可直接调用的公共接口。</p><h3>7. 正式版完成标准</h3><ul class="checklist"><li>项目会话全部分页可见；未知阶段明确标注；断线恢复不丢事件。</li><li>两个不同会话间切换发送，目标准确；运行中和空闲状态分别验证。</li><li>超时 / 重连 / 重复点击不产生重复会话、模型请求或素材上传。</li><li>按编号接单可以复用原线程、授权、预算与历史回执。</li><li>全源全语交齐才显示整项完成，质量异议与返工仍能追踪。</li><li>自动任务可以查看真实下次触发、当前轮、历史和修改回执。</li></ul><h3>工作量判断</h3><p>先用约半天至1个工作日验证会话桥接的关键路径，再根据联调结果估算开发排期。只读工作台可以先交付，双向控制与插件封装分阶段验收；这只是初步工作量判断，尚未进行真实端到端联调。</p><h3>本次依据</h3><p>已读取用户指定的全流程总结、两个引用会话，以及 workbench、台账和 Benchmark 文档。未触发真实接单、发消息、付费模型、自动任务改动或平台提交。</p><p><a href="https://developers.openai.com/codex/app-server/" target="_blank" rel="noopener noreferrer">官方：Codex App Server</a> · <a href="https://developers.openai.com/plugins/build/chatgpt-ui" target="_blank" rel="noopener noreferrer">官方：MCP UI</a> · <a href="https://developers.openai.com/plugins/build/plugins" target="_blank" rel="noopener noreferrer">官方：插件打包</a></p></div></section>`;
}
function navigate(next) { view=next;location.hash=next;render(); }
function selectSession(id) { selected=id; let index=filteredSessions().findIndex(s=>s.id===id);if(index<0){filter='all';search='';index=sessions.findIndex(s=>s.id===id);}sessionPage=Math.floor(Math.max(0,index)/SESSION_PAGE_SIZE)+1; detailTab='flow';selectedNode=current()?.phase===0?'intake':'production';view='sessions';location.hash='sessions';render(); }
function openIntake() { $('#intake-result').textContent='';$('#intake-dialog').showModal();$('#requirement-code').focus(); }
function curate() {curated.unshift(`项目经验总结 · 演示任务 ${String(curated.length+1).padStart(2,'0')}`);navigate('knowledge');toast('已加入本地演示队列，未触发真实总结。');}
function advanceDemo() {
  const s=sessions.find(s=>s.id==='demo-042');
  if(s.state==='done') { simulate=false;clearInterval(simulationTimer);if(view==='sessions')render();return; }
  demoStep++;
  const stages=[{percent:68,phase:4,stage:'整幅对照与声音实审',eta:'约 12–22 分钟'}, {percent:82,phase:5,stage:'完整输出与提交审查',eta:'约 7–15 分钟'}, {percent:94,phase:6,stage:'平台回传与逐语种核验',eta:'约 3–8 分钟'}, {percent:100,phase:7,stage:'全部语种平台读回核验',eta:'已完成（演示）',state:'done'}];
  const stage=stages[Math.min(demoStep-1,stages.length-1)];Object.assign(s,stage);
  s.messages.push({who:'system',text:`模拟事件：${stage.stage}。进度值仅用于体验，不代表真实制作。`});
  if(view==='sessions')render();
  if(s.state==='done'){simulate=false;clearInterval(simulationTimer);if(view==='sessions')render();toast('模拟完成：全量回传核验后才显示整项完成。');}
}
document.addEventListener('click',event=>{
  const el=event.target.closest('button,[data-nav]');if(!el)return;
  if(el.dataset.nav){navigate(el.dataset.nav);return;}
  if(el.dataset.session){selectSession(el.dataset.session);return;}
  if(el.dataset.filter){filter=el.dataset.filter;sessionPage=1;render();return;}
  if(el.dataset.sessionPage){sessionPage=Number(el.dataset.sessionPage);refreshSessionList();return;}
  if(el.dataset.detailTab){detailTab=el.dataset.detailTab;$('#session-detail').innerHTML=renderDetail(current());return;}
  if(el.dataset.node){selectedNode=el.dataset.node;$('#session-detail').innerHTML=renderDetail(current());openNodeOutputs(current(),selectedNode);return;}
  if(el.dataset.selectArtifact){selectedArtifact=el.dataset.selectArtifact;$('#session-detail').innerHTML=renderDetail(current());return;}
  if(el.dataset.openArtifact){openArtifact(el.dataset.openArtifact);return;}
  if(el.dataset.artifactFeedback){const a=artifactData.find(a=>a.id===selectedArtifact);const text=`针对「${current().code} / 原片01 / ${a.title} / v${a.id==='base-b'?'2':'1'}」（演示产物）：${el.dataset.artifactFeedback}`;drafts.set(selected,text);$('#chat-input').value=text;if($('#artifact-dialog').open)$('#artifact-dialog').close();$('#chat-input').focus();toast('已将具体产物版本带入当前会话输入框，确认后可模拟发送。');return;}
  if(el.dataset.prompt){$('#chat-input').value=el.dataset.prompt;drafts.set(selected,el.dataset.prompt);$('#chat-input').focus();return;}
  if(el.dataset.toggle!==undefined){const a=automations[Number(el.dataset.toggle)];a.enabled=!a.enabled;autoLog.unshift([a.name,a.enabled?'恢复演示计划':'暂停演示计划']);render();toast('只改变演示开关，真实自动任务保持原状。');return;}
  if(el.dataset.runAuto!==undefined){const a=automations[Number(el.dataset.runAuto)];autoLog.unshift([a.name,'模拟手动触发一轮']);if(Number(el.dataset.runAuto)===1){curate();}else{render();toast('模拟执行记录已保存到本页；未运行真实任务。');}return;}
  if(el.dataset.autoOwner!==undefined){const i=Number(el.dataset.autoOwner);if(i===2){toast('存储任务正式版将显示独立运行回执，此处未绑定会话。');}else{selectSession(initialSessions[i===0?4:3].id);}return;}
  if(el.dataset.knowledge!==undefined){$('#knowledge-detail').innerHTML=knowledgeDetail(Number(el.dataset.knowledge));return;}
  if(el.dataset.review){$('#review-result').innerHTML=`<div class="review-result">已模拟记录：${esc(el.dataset.review)}。没有发布或修改正式知识。</div>`;return;}
  switch(el.dataset.action){
    case'intake':openIntake();break;
    case'curate':curate();break;
    case'close-dialog':$('#intake-dialog').close();break;
    case'close-artifact':$('#artifact-dialog').close();break;
    case'simulation':
      if(sessions.find(s=>s.id==='demo-042').state==='done'){toast('当前模拟已结束。点击左下角“重置演示”可重新播放。');break;}
      simulate=!simulate;if(simulate){simulationTimer=setInterval(advanceDemo,6500);toast('每6.5秒推进一个演示阶段，可随时暂停。');}else{clearInterval(simulationTimer);}render();break;
    case'reset':clearInterval(simulationTimer);simulate=false;demoStep=0;sessions=structuredClone(initialSessions);selected=sessions[0].id;autoLog.length=0;curated.length=0;automations.forEach(a=>a.enabled=true);detailTab='flow';selectedNode='production';filter='all';search='';sessionPage=1;drafts.clear();navigate('sessions');toast('已重置本地演示。');break;
  }
});
document.addEventListener('input',event=>{if(event.target.id==='chat-input')drafts.set(selected,event.target.value);if(event.target.id==='session-search'){search=event.target.value;sessionPage=1;refreshSessionList();}});
document.addEventListener('keydown',event=>{if(event.target.id==='chat-input'&&event.key==='Enter'&&(event.metaKey||event.ctrlKey)){event.preventDefault();$('#chat-form').requestSubmit();}});
document.addEventListener('submit',event=>{
  if(event.target.id==='chat-form'){
    event.preventDefault();const text=$('#chat-input').value.trim();if(!text){$('#chat-input').focus();return;}
    const target=event.target.dataset.target;drafts.delete(target);const s=sessions.find(s=>s.id===target);if(!s)return;
    s.messages.push({who:'user',text},{who:'system',text:`已记录给「${s.snapshot?s.name:s.code}」的模拟指令。生产连接未启用，未发送至 Codex。`});
    $('#session-chat').innerHTML=renderChat(s);const list=$('#chat-messages');list.scrollTop=list.scrollHeight;toast('已记录本地模拟输入，未向真实会话发送。');
  }
  if(event.target.id==='intake-form'){
    event.preventDefault();const code=$('#requirement-code').value.trim().toUpperCase();
    if(!/^[A-Z][A-Z0-9]{1,11}-\d{8}-\d{2,6}$/.test(code)){$('#intake-result').textContent='请使用类似 APC-20261103-014 的编号格式。';return;}
    const existing=sessions.find(s=>s.intakeCode===code||s.code===code);
    if(existing){$('#intake-dialog').close();selectSession(existing.id);toast('已找到同编号演示会话，直接复用，未重复创建。');return;}
    const note=$('#intake-note').value.trim();
    const session={id:'intake-'+code,code,intakeCode:code,name:'按编号接单 · 本地模拟',state:'queued',phase:0,percent:0,elapsed:'刚刚',eta:'范围核验后估计',cost:'0 / 180',langs:3,stage:'等待需求范围核验',source:'固定演示范围 · 非平台读取',messages:[{who:'system',text:`已模拟接收需求号 ${code}。正式版将精确读取平台、核对范围和已有会话，再决定复用或创建。当前没有创建真实聊天或开工。${note?' 补充要求：'+note:''}`}]};
    sessions.unshift(session);$('#intake-dialog').close();$('#intake-form').reset();selectSession(session.id);toast('已创建本地演示条目；未查询Fireplay、未开真实会话。');
  }
});
window.addEventListener('hashchange',()=>{const next=location.hash.slice(1);if(['sessions','automations','knowledge','plan'].includes(next)&&view!==next){view=next;render();}});
if(['sessions','automations','knowledge','plan'].includes(location.hash.slice(1)))view=location.hash.slice(1);
render();
