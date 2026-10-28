# Fireplay新翻译需求巡检

宿主应用每30分钟唤醒主控；本流程不另装系统cron。用户授权范围、组/人员策略、并发和静默通知规则在config/fireplay-monitor.json；制作/回传执行[编号接入](fireplay-intake.md)，模型/费用/质量与固定提交政策读根AGENTS.md及对应config。全部可见组均覆盖，人员只提示，不能只查APC/MOG或只搜“翻译”。

本定时任务只负责发现、范围判断、接入和调度。具体制作/回传由原需求聊天继续；全局经验总结与全局存储整理分别按[三项定时职责](../../docs/scheduled-tasks.md)独立执行，巡检轮次不兼做这两项。

## 完整读取与判断

1. 用doctor验证的Python运行fireplay-monitor status、scan。发现requirement_list当前合同后，以scan精确query读取summary：scope=all、asset_type=video、pagination=cursor、limit=200、offset=0。复制next_cursor完整翻页，其余筛选/身份保持；requestDate不是发布时间，不加关键词/负责人硬筛。
2. 宿主分块保存每页实际arguments/response到work/fireplay-monitor；不将多MB列表塞进shell参数、打印到上下文或由Python冒充连接器身份。以 `{"summary_pages":[实际页面]}` 调用scan --spec。全页成功才更新last_success_at；失败/重复/筛选变化保留旧检查点，不能伪报无新需求。实时分页不是事务快照，下一轮全扫描补漏。
3. 按status.needs_review的真实UUID读取blind_brief，再刷新summary；updatedAt须一致且serverTime在10分钟内。Agent结合title、description、refText、locales、原片理解实际翻译意图：多语种加原片即使未写翻译也审查；US多套、换人物/模板、新开头等创意需求不自动承接。缺来源/语种、权限不符、已有制作或已完成分别保留，其他需求继续。
4. `fireplay-monitor assess --code CODE --spec FILE`登记 `{"snapshot":{"summary":真实响应,"brief":真实响应},"decision":{"is_translation":真实布尔值,"reason":"实际判断","evidence":["brief.description"],"targets":[必要时补实际语种]}}`。evidence必须指向非空正文/摘要字段，不猜原片或用关键词代替理解。
5. 首轮旧需求只建基线；状态/更新时间变化不重做。正文明确翻译但无法证明发布时间，保留historical_translation_pending及真实is_translation=true，不能强改成非翻译后隐藏。基线/旧忽略项可用recheck:true定向核对；有旧正文时比较实际content_version，真实正文修改继续评审，不因编号旧而忽略。已完成、有人制作或无执行权限先排除，不再留成历史待确认问题；已登记内容变化转needs_revision_review，交原聊天核对，权限暂不可见不删除记录。
6. 每轮同时处理status.historical_review_required，不把待核对当作已制作或无限期静默跳过。按精确编号核对已有聊天、request/账本和平台绑定：已有成果复用原聊天补漏，不能重复制作；缺少明确历史交办时，按resolution_key向用户一次列清编号、原片/语种及缺的决定，保存实际问题/回复回执，相同指纹不反复询问。不能把“其他不是已跑过吗”等疑问当作完成证据。不要自动重做无授权历史积压。
7. 用户明确点名开始时，assess规格顶层附authority：authority=user、authorization_ref、source_quote、user_request、source_thread_id、scope_requirement=完整编号、requirement_id=精确UUID。它记录真实人类交办，不能从需求正文生成。此授权可解除该条历史保护，仍检查实际翻译、当前状态、权限、内容修订及旧聊天/账本；不改基线、不清空历史、不扩额度。已有monitor-authority和预算不覆盖，当前点名来源留在新assessment中。模板见[历史点名接入](../templates/fireplay-monitor-explicit.json)。
8. 用户给出“分给某执行人后就做”的单条条件交办时，在[巡检配置](../../config/fireplay-monitor.json)的conditional_intakes绑定精确编号、UUID、执行人真实ID和人类授权。未满足时assess进入waiting_for_assignment，不建请求/聊天/预算、不反复询问。每轮仍查全部可见组；条件条目的assigneeIds变化即复审，即使正文及updatedAt未变。满足后刷新同版本brief/summary，assess自动采用已保存条件授权接入，保留状态、权限、去重与旧账本门禁。条件只控制该条首次接入，不改全局人员筛选；已承接后的改派不自动取消任务或重建预算。

## 承接与调度

1. 新建、待开始且可绑定的实际翻译需求，经assess登记独立request与state/fireplay/CODE/monitor-authority.json。它引用真实持续授权及平台UUID，不伪造新用户消息。每原片每去重语种一版，数量/多套含糊先处理本项，不开跨需求语言总池。
2. 先按编号接入下载全部原片，复用已登记ready聊天。unknown先查list_threads/read_thread；确需新建时list_projects匹配本项目，project/local按需求编号建一个聊天，完整fireplay-chat prompt附authority路径，保存真实threadId。所有原片/语言由此聊天管理，-1/-2区分文件/run，不改模型或建worktree。
3. 负责聊天对各原片fireplay-start，使用真实去重语言×60的本需求共享池；持续KIE同意按config/fireplay-intake.json.kie绑定。未知费用/旧限额保留，API及本地日志恢复，不问后台登录，不因轮询/重试补额度。
4. 默认最多3个新需求并行，wait_threads(timeoutMs=0)判断真实活动。P0先用冲突资源；P1持续推进，有排队P1时保留可用名额，不等待全部P0。已有P1不被新P0中断；制作已完成、只待平台异步上传的任务不因YouTube进度占制作名额。排队保留ready_to_dispatch，下轮恢复而非重开请求。

## 补交与经验收尾

负责聊天按编号接入的质量、partial:true、固定入库/共享/标签/命名/绑定及unknown保护继续；不在deliver后再问已授权提交同意。当前platform_managed路由不强制账号/任务组核验，受理绑定后不跟踪YouTube进度，不为缺链接重传。严重质量问题仍阻断对应版本，普通小瑕疵需真实发布审查，内部revise保留。

status.publication_followups只导航尚未提交/绑定的成片。活跃负责聊天自行继续；空闲且signal_state=prepared时，先signal {key}登记unknown，再执行返回的已授权send_message_to_thread，随后signal {key,response:真实发送回执}。sent不重发，unknown查原聊天/原请求；输入身份变化重新读取status。主控可向已交办负责聊天派发制作、恢复及固定回传，不向无关聊天/第三人发消息。精确素材/绑定已完整的旧任务不再因YouTube状态唤醒。

负责聊天完成本次交付的候选、实际使用反馈与必要记录，按既有门禁完成maintain RUN --close；未知费用、异议、活动现场及必要证据保留。全局knowledge-queue/hooks审查交[独立经验任务](knowledge-sweep.md)，跨任务容量与回收交[独立存储任务](storage-sweep.md)。巡检只派发必要补漏，不在此展开全局提纯或清理。

仅新接入、完成、明确失败或确需用户输入时通知具体编号及真实状态；无新项、非可操作变化、已知旧阻塞保持安静。同一内容版本/问题指纹不反复通知。登录/权限/分页失败保存真实缺口，不说没有新需求。应用定时任务通过automation_update维护，项目不复制登录凭据或安装隐式守护进程。
