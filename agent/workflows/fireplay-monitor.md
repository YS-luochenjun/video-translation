# Fireplay新翻译需求巡检

宿主应用每30分钟唤醒主控；本流程不另装系统cron。用户授权范围、组/人员策略、并发和静默通知规则在config/fireplay-monitor.json；制作/回传执行[编号接入](fireplay-intake.md)，模型/费用/质量与固定提交政策读根AGENTS.md及对应config。全部可见组均覆盖，仅查询执行人包含邹彬（已核验ID `b2fbcgab`）的需求；不能只查APC/MOG或只搜“翻译”。

长期生命周期按config/fireplay-monitor.json.lifecycle：新需求巡检全天每30分钟持续开启，不因本批、当前全部会话完成或队列暂空而暂停/删除；只有用户明确要求停止需求巡检才调整。滚动范围的会话完成盯办是独立任务，后续人工新增并接入的需求也纳入；全部当前范围真实交付核验且无新接入负责项后只结束该盯办，不删除制作聊天，也不停止本长期巡检。旧批次停止记录不能充当长期巡检的停止条件。

本定时任务负责发现、范围判断、接入和调度。制作与回传由原需求聊天继续。用户手动触发经验总结，存储按自己的日程整理。各入口见[任务职责](../../docs/scheduled-tasks.md)。

新需求按原片拆分会话。读取 `source_capacity` 和 `ready_to_dispatch[].sources`，在每个原片建聊前占用全局10个名额之一。旧需求的聊天和已领取原片沿原执行者续作。派发、恢复和状态更新保留真实回执。操作未知时先查原记录。步骤见[并行制作](fireplay-parallel.md)。

自动接单同时检查执行人包含邹彬、AI承接交付为视频翻译、状态为未开始、具备绑定及状态权限。读取正文确认原片和实际语种。建聊和付费前按编号及UUID核对原聊天、请求、账本与平台绑定。其他状态保留日常跟踪和具体判断。

用户明确撤回或确认由同事接手的需求，在 `config/fireplay-monitor.json.excluded_requirements` 按编号和 UUID 记录。保留原需求、聊天及回执，排除后续接入、派发和完成盯办。

优先级不是接入条件。所有等级（含P2、其他值和未标等级）都按同一范围判断承接，排序与推进规则读取config/fireplay-intake.json.priority_policy；低优先级不得被静默丢弃或等待所有高优先级结束。排队须保留ready_to_dispatch，具体信息/权限/费用/质量缺口分别记录。普通单条语言确认不扩展为全局别名；用户2026-11-09已明确将sa统一为ar，按config/language-aliases.json及[语言解析政策](../../knowledge/rules/language-aliases-v3.md)执行，不再逐条询问sa。旧请求/账本/费用及历史确认保留。

发起规范在需求面板指派邹彬，可另加实际设计师。巡检用精确assignee_ids筛选，多执行人中包含该ID即可。按同一全局原片上限排队。需求数独立保留，原片的所有语言合占一个名额。

## 分层轮询与判断

1. 用doctor验证的Python运行fireplay-monitor status、scan。日常每30分钟执行程序返回的active查询，其中 `ai_mode=video_translate`、`status=["not_started"]`。所有组和优先级均覆盖。沿 `next_cursor` 完整翻页。复核时保留人员和视频范围。
2. 每页保存真实arguments/response到work/fireplay-monitor，以 `{"scan_mode":"active","summary_pages":[实际页面]}` 调用scan --spec。UUID、updatedAt及元数据未变化时复用原判断。每24小时执行polling.full_reconciliation，按返回参数核对全部状态及AI分类。人员、视频及组范围沿用原筛选。
3. 每轮还执行status.polling.tracking内各批精确UUID查询（每批最多40，无状态/日期条件），以 `{"scan_mode":"tracked","requirement_ids":[该批UUID],"summary_pages":[实际页面]}` 入账。覆盖原负责聊天未结项、排队、缺片/缺语种、修订及待确认项，包含平台变成pending_upload/done的已接入需求。单批未返回的UUID进入tracking_gaps，核对权限/改派，不能据缺席或平台done宣告完成。active/full/tracked分别维护last_active_success_at、last_full_success_at、每UUID tracking_checkpoints；last_success_at/visible_count只表示完整full结果。失败、坏JSON、重复ID、循环游标或筛选变化不推进对应检查点，不清空旧记录。实时分页不是事务快照，重叠轮询和每日全量共同补漏。
4. 按status.needs_review的真实UUID读取blind_brief，再刷新summary；updatedAt须一致且serverTime在10分钟内。Agent结合title、description、refText、locales、原片理解实际翻译意图：多语种加原片即使未写翻译也审查；US多套、换人物/模板、新开头等创意需求不自动承接。按[原片优先级](fireplay-intake.md#原片优先级)，正文和参考栏均无可识别视频链接时，将同版本delivery回执附入snapshot，用附件判断和接入。缺来源/语种、权限不符、已有制作或已完成分别保留，其他需求继续。
5. `fireplay-monitor assess --code CODE --spec FILE`登记 `{"snapshot":{"summary":真实响应,"brief":真实响应},"decision":{"is_translation":真实布尔值,"reason":"实际判断","evidence":["brief.description"],"targets":[必要时补实际语种]}}`。evidence必须指向非空正文/摘要字段，不猜原片或用关键词代替理解。
6. 首轮旧需求只建基线；状态/更新时间变化不重做。正文明确翻译但无法证明发布时间，保留historical_translation_pending及真实is_translation=true，不能强改成非翻译后隐藏。基线/旧忽略项可用recheck:true定向核对；有旧正文时比较实际content_version，真实正文修改继续评审，不因编号旧而忽略。已完成、有人制作或无执行权限先排除，不再留成历史待确认问题；已登记内容变化转needs_revision_review，交原聊天核对，权限暂不可见不删除记录。
7. 每轮同时处理status.historical_review_required，不把待核对当作已制作或无限期静默跳过。按精确编号核对已有聊天、request/账本和平台绑定：已有成果复用原聊天补漏，不能重复制作；缺少明确历史交办时，按resolution_key向用户一次列清编号、原片/语种及缺的决定，保存实际问题/回复回执，相同指纹不反复询问。不能把“其他不是已跑过吗”等疑问当作完成证据。不要自动重做无授权历史积压。
8. 用户明确点名开始时，assess规格顶层附authority：authority=user、authorization_ref、source_quote、user_request、source_thread_id、scope_requirement=完整编号、requirement_id=精确UUID。它记录真实人类交办，不能从需求正文生成。此授权可解除该条历史保护，仍检查实际翻译、当前状态、权限、内容修订及旧聊天/账本；不改基线、不清空历史、不扩额度。已有monitor-authority和预算不覆盖，当前点名来源留在新assessment中。模板见[历史点名接入](../templates/fireplay-monitor-explicit.json)。
9. 用户给出“分给某执行人后就做”的单条条件交办时，在[巡检配置](../../config/fireplay-monitor.json)的conditional_intakes绑定精确编号、UUID、执行人真实ID和人类授权。未满足时assess进入waiting_for_assignment，不建请求/聊天/预算、不反复询问。每轮仍查全部可见组；条件条目的assigneeIds变化即复审，即使正文及updatedAt未变。满足后刷新同版本brief/summary，assess自动采用已保存条件授权接入，保留状态、权限、去重与旧账本门禁。条件只控制该条首次接入，不改全局人员筛选；已承接后的改派不自动取消任务或重建预算。
10. 已登记但尚未建聊、建账本、生成制作任务或准备回传的排队需求，正文修订可由Agent核对实际差异后，在decision附reviewed_content_version=原content_version接受；reason写清原片、语种和文案变化。正文分别指定原片和语种时，附source_targets（精确source_url到语言列表的完整映射），targets为其并集；各原片只制作videos[].targets，不能全部交叉相乘，仍共用本需求并集语种的账本。旧request完整保留在revisions并记录历史，未变原片保留哈希，新增原片使用版本隔离目录，不能误用旧编号目录中的下载。已有聊天（含unknown）、预算、制作或回传时拒绝此路径，仍交原负责聊天处理，不重置费用或覆盖旧工作。

## 需求面板的投放记录

每轮在完成原有需求巡检和必要调度后，用 doctor 验证的 Python 执行 `workbench/material_launch.py plan`。仅按返回的已核验素材 ID 调用 Fireplay `material_list`，每轮至多两批，优先补齐未查询或最久未核对的素材。将每批实际 JSON 响应保存到 `work/state` 的本轮临时文件，再执行 `workbench/material_launch.py record --response FILE`。需求面板读取素材库返回的 `hasLaunchRecord` 和查询时间。缺失素材保持待核对，查询失败保留上次结果，巡检和结案继续。

## 承接与调度

1. `assess` 登记合范围请求及 `state/fireplay/CODE/monitor-authority.json`，沿用精确UUID及用户持续授权。
2. 按 `ready_to_dispatch` 及其 `sources` 顺序推进。先按[编号接入](fireplay-intake.md#读取与下载)准备原片。YouTube 精确查库缺片时按[缺片补取](fireplay-intake.md#youtube-缺片补取)接入及复查，再运行 `fireplay-chat CODE --video N --execute`。有名额时登记预约。首片需按[需求状态](fireplay-intake.md#需求状态)改为「进行中」并读回，再建聊。建聊回执逐原片绑定。`unknown` 先查 `list_threads`/`read_thread`。已有聊天沿原编号继续。
3. 各原片聊天在自己的序号上执行 `fireplay-start`，共用本需求去重语种×60的账本。每次绑定完成后做一次真实启动交接核对，按[聊天、授权与制作](fireplay-intake.md#聊天授权与制作)检查首轮：运行中不打断；空闲且未启动的，先核对真实阻塞和在途操作，再沿原threadId使用下文持久signal明确派发实际启动，不等待下一轮才处理首轮误退出。只确认交接，不持续盯着制作。各片沿自己的回传进度交付，首个绑定的会话协调整单结案。
4. 无名额时保留 `ready_to_dispatch`，按全局占用继续排队。原片完成真实绑定后开放名额。P0优先用有冲突的资源，其余优先级有空位即推进。
5. 每次真实建聊/恢复及每轮status后处理 `completion_watch`：[20分钟完成盯办](fireplay-completion-watch.md)按config.completion_watch单独调度。`host_action=ensure_active` 时先核对角色文件、manifest及应用真实定时任务；已有活动盯办复用并追加新项，没有才通过automation_update创建；已删除的旧盯办遇到新接入必须重新创建，不能沿用旧ID或旧批次已完成结论。创建/更新提示使用config指定的可迁移模板，按当前项目和实际主控聊天绑定，不把本机ID当跨机器安装证据。保存真实ID/回执后更新manifest与角色文件，不以本地计划冒充已创建；创建unknown先核查。长期发现巡检始终保持30分钟ACTIVE。

## 补交与经验收尾

负责聊天按编号接入的质量、partial:true、固定入库/共享/标签/命名/绑定及unknown保护继续；不在deliver后再问已授权提交同意。当前platform_managed路由不强制账号/任务组核验，受理绑定后不跟踪YouTube进度，不为缺链接重传。大面积撕裂等严重问题仍阻断对应版本；有界最佳完整成品带普通不合格可按真实发布审查提交，内部revise保留。

status.publication_followups逐项导航未完整交付的原片/语种。`production_initialization=not_initialized` 表示该原片尚无已登记制作成员；结合真实会话状态识别首轮提前退出，不能当作已经制作。`initialized` 仅证明已初始化，不代表正在运行或已经交付。auto_return的ready_locales先提交，review_locales做实际发布审查，production_locales和blocked_locales持续制作/修复；不因尚有缺项而等全部就绪。普通不合格按有界最佳成品政策提交，严重损坏仍阻断对应版本；真实文件上传超时先核对已有ID，再按既有额外两次授权有界重传，不能重发未知付费模型。全部本地绑定齐全但尚缺整项平台读回时，verify_completion要求真实delivery视图执行fireplay-completion-check，再fireplay-close；不跟踪YouTube。

派发由同一原聊天、原账本和持久signals维护。每轮先wait_threads(timeoutMs=0)检查负责聊天，正在运行的不重复打断；prepared且空闲时先signal {key}登记unknown，再执行返回的已授权send_message_to_thread，随后signal {key,response:真实发送回执}。unknown必须查原聊天/原请求核对，不按超时自动重发。

固定提交使用config/fireplay-publication.json.submission_consent的持续授权，不再主动询问上传或对应组共享。宿主实际拒绝且要求人类处理的项目不算普通漏交，不能因为聊天空闲就重派以绕过拦截；先读当前及原负责聊天中的真实人类答复，匹配精确成片/组范围，已确认则登记来源并沿原聊天继续，未确认保持具体阻塞且相同指纹只问一次。历史“等待确认”快照不能覆盖后来的真实回复。

sent只表示消息已送达。租约默认120分钟，到期signal_state=owner_check_required；未到期也要检查真实会话，不能用租约代替运行状态。保存真实wait_threads/read_thread回执，调用signal附owner_observation，字段为threadId、status（idle/running/needs_attention/error）、observed_at、source以及evidence:{path,sha256}。running只续租；已送达且确认idle/error时，先核对具体阻塞、在途任务与unknown，存在可执行工作才调用signal生成新unknown派发并保留历史，执行后登记真实发送回执；重派回执还须附本次attempt，防止旧回执确认新派发。最多两次停滞重派，之后定位或升级；不能假报完成、无限催同一句或自动重试付费任务。needs_attention按实际缺口处理，不从状态推断用户许可。配置见config/fireplay-monitor.json.delivery_followup。

首轮或恢复轮数秒内结束且真实会话记录没有任何执行工具调用时，先区分派单措辞误解、实际工具故障和正常制作失败，不归咎于KIE或原片。用户于2026-11-25指定制作聊天使用 GPT-6.2 Sol（`codex/gpt-6.2-sol`），不再使用 GPT-6.1 Terra。新建及恢复制作聊天按此模型执行；明确制作交付角色后仍连续无工具调用时，保留真实发送和执行回执并定位宿主问题，不自行切换其他执行模型。不重新创建会话、不切换已发起的付费媒体模型、不重置账本。只有真实工具调用与制作记录可证明恢复，模型变更及聊天活跃本身不证明交付成功。

partial和pending始终保留在恢复队列；同一旧阻塞不反复通知，不等于停止执行已授权补漏。设计师由负责聊天查Fireplay真实成员/原生页面自行判断，不向用户索要DID；KIE在本需求持续授权及原额度内直接使用，不重复项目同意问题。主控只向已交办负责聊天派发恢复，不向无关聊天或第三人发消息。

负责聊天完成本次交付的候选、实际使用反馈与必要记录，按既有门禁完成maintain RUN --close；未知费用、异议、活动现场及必要证据保留。全局knowledge-queue/hooks审查交[独立经验任务](knowledge-sweep.md)，跨任务容量与回收交[独立存储任务](storage-sweep.md)。巡检只派发必要补漏，不在此展开全局提纯或清理。

仅新接入、完成、明确失败或确需用户输入时通知具体编号及真实状态；无新项、非可操作变化、已知旧阻塞保持安静。同一内容版本/问题指纹不反复通知。登录/权限/分页失败保存真实缺口，不说没有新需求。应用定时任务通过automation_update维护，项目不复制登录凭据或安装隐式守护进程。
