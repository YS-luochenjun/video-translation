# Fireplay 承接、调度及补交

总入口见 [fireplay-monitor](fireplay-monitor.md)。

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

首轮或恢复轮数秒内结束且真实会话记录没有任何执行工具调用时，先分辨派单措辞、会话工具和正常制作故障。用户于2026-11-25指定制作聊天使用 GPT-6.2 Sol（`codex/gpt-6.2-sol`）。新建及恢复制作聊天按此模型执行，已发起的付费媒体任务和账本沿用原记录。以实际工具调用及制作记录判断恢复。

发现空闲轮次没有执行证据时，用 `read_thread` 读取最近两个轮次并保存完整回执，确认两轮 items 均未分页。`fireplay-monitor signal` 根据真实回执识别连续两个只有回复的已结束轮次，登记 `escalation_required` 和轮次 ID。工作台核对首个待执行命令、宿主工具和在途回执。已取得必要工具持续调用失败的实际回执时，可直接核实故障并进入接替流程。原聊天可恢复时沿原聊天继续。

### 会话故障接替

授权见 `config/fireplay-monitor.json.delivery_followup.owner_handoff`，适用于巡检发现的已交办、未结案需求。工作台可按该授权建一个接替聊天并派发原任务。按以下步骤完成交接。

1. 按需求 UUID、原片序号和当前负责人核对待办。用最新 `wait_threads` 和 `read_thread` 查原聊天的真实状态、最近动作和回执。以持续无法执行终端或必要工具的实际错误，或明确派发实际动作后持续无工具调用的完整轮次为依据，同时检查是否有在途写入、待确认创建或发送。单次空闲、正常运行或等待、KIE 故障、预算不足、严重质量阻塞及宿主审批问题分别按现有流程处理。
2. 确认原聊天仍停滞后，保存原负责人证据和本次建聊意图。用宿主 `create_thread` 在同一项目建候选聊天，沿用制作模型。首轮只验证该需求所需的工具和原现场读回，例如实际调用终端运行 `fireplay-status CODE`。取得真实 `threadId`、`hostId` 和成功调用证据后，再即时复查原聊天和写入领取。原聊天已恢复执行时由原聊天继续，候选聊天停在只读验证。建聊结果未知时先查历史和实际聊天，确认结果后再推进。
3. 确认原聊天已停写，按[并行制作](fireplay-parallel.md)核对活跃领取。在 `state/fireplay/CODE/` 保存独立交接回执，记入需求 UUID、原片序号、内容版本、原负责人、新负责人、故障及停写证据、候选工具验证和原预算。沿用 `status: READY` 及 `replacements` 中 `{code, old_thread_id, new_thread_id}` 的既有回执格式。在既有项目写入锁下核对 `state/fireplay/CODE/request.json` 仍指向旧负责人且内容版本与回执一致，再将该原片 `chat` 切换至真实新聊天，记录 `state: ready`、需求原片标题、`predecessor_thread_id` 和 `migration_receipt`。原负责人兼整单协调时同步切换 `request.chat` 和完成盯办 manifest 的对应项，保留历史。旧版整单共享聊天同步交接它实际负责的原片。保留旧聊天、原片、runs、预算、授权、成片、在途任务、未知费用及回传回执，沿同一原片名额推进。
4. 重新运行 `fireplay-monitor status`，读回新负责聊天和实际待办，按新负责人的 `signal` 派发首个实际制作或回传动作。先对账旧未知操作，沿原操作回执继续，已有素材 ID 和成片继续复用。确认接替聊天发出该需求的实际调用后交回定期巡检。新旧聊天只有当前负责人继续写入该原片。

partial和pending始终保留在恢复队列；同一旧阻塞不反复通知，不等于停止执行已授权补漏。设计师由负责聊天查Fireplay真实成员/原生页面自行判断，不向用户索要DID；KIE在本需求持续授权及原额度内直接使用，不重复项目同意问题。主控只向已交办负责聊天派发恢复，不向无关聊天或第三人发消息。

负责聊天完成本次交付的候选、实际使用反馈与必要记录，按既有门禁完成maintain RUN --close；未知费用、异议、活动现场及必要证据保留。全局knowledge-queue/hooks审查交[独立经验任务](knowledge-sweep.md)，跨任务容量与回收交[独立存储任务](storage-sweep.md)。巡检只派发必要补漏，不在此展开全局提纯或清理。

仅新接入、完成、明确失败或确需用户输入时通知具体编号及真实状态；无新项、非可操作变化、已知旧阻塞保持安静。同一内容版本/问题指纹不反复通知。登录/权限/分页失败保存真实缺口，不说没有新需求。应用定时任务通过automation_update维护，项目不复制登录凭据或安装隐式守护进程。
