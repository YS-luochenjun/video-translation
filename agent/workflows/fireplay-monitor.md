# Fireplay新翻译需求巡检

宿主应用每30分钟唤醒主控；本流程不另装系统cron。用户授权范围、组/人员策略、并发和静默通知规则在config/fireplay-monitor.json；制作/回传执行[编号接入](fireplay-intake.md)，模型/费用/质量与固定提交政策读根AGENTS.md及对应config。全部可见组均覆盖，人员只提示，不能只查APC/MOG或只搜“翻译”。

## 完整读取与判断

1. 用doctor验证的Python运行fireplay-monitor status、scan。发现requirement_list当前合同后，以scan精确query读取summary：scope=all、asset_type=video、pagination=cursor、limit=200、offset=0。复制next_cursor完整翻页，其余筛选/身份保持；requestDate不是发布时间，不加关键词/负责人硬筛。
2. 宿主分块保存每页实际arguments/response到work/fireplay-monitor；不将多MB列表塞进shell参数、打印到上下文或由Python冒充连接器身份。以 `{"summary_pages":[实际页面]}` 调用scan --spec。全页成功才更新last_success_at；失败/重复/筛选变化保留旧检查点，不能伪报无新需求。实时分页不是事务快照，下一轮全扫描补漏。
3. 按status.needs_review的真实UUID读取blind_brief，再刷新summary；updatedAt须一致且serverTime在10分钟内。Agent结合title、description、refText、locales、原片理解实际翻译意图：多语种加原片即使未写翻译也审查；US多套、换人物/模板、新开头等创意需求不自动承接。缺来源/语种、权限不符、已有制作或已完成分别保留，其他需求继续。
4. `fireplay-monitor assess --code CODE --spec FILE`登记 `{"snapshot":{"summary":真实响应,"brief":真实响应},"decision":{"is_translation":真实布尔值,"reason":"实际判断","evidence":["brief.description"],"targets":[必要时补实际语种]}}`。evidence必须指向非空正文/摘要字段，不猜原片或用关键词代替理解。
5. 首轮旧需求只建基线；状态/更新时间变化不重做。正文明确翻译但无法证明发布时间，保留historical_translation_pending及真实is_translation=true，在historical_translation_candidates可见；不能强改成非翻译后隐藏。基线/旧忽略项可用recheck:true定向核对，仍不自动付费重做历史积压。用户点名后用本次真实授权接入，旧聊天/预算不重建。已登记内容变化转needs_revision_review，交原聊天核对差异；权限暂不可见不删除记录。

## 承接与调度

1. 新建、待开始且可绑定的实际翻译需求，经assess登记独立request与state/fireplay/CODE/monitor-authority.json。它引用真实持续授权及平台UUID，不伪造新用户消息。每原片每去重语种一版，数量/多套含糊先处理本项，不开跨需求语言总池。
2. 先按编号接入下载全部原片，复用已登记ready聊天。unknown先查list_threads/read_thread；确需新建时list_projects匹配本项目，project/local按需求编号建一个聊天，完整fireplay-chat prompt附authority路径，保存真实threadId。所有原片/语言由此聊天管理，-1/-2区分文件/run，不改模型或建worktree。
3. 负责聊天对各原片fireplay-start，使用真实去重语言×60的本需求共享池；持续KIE同意按config/fireplay-intake.json.kie绑定。未知费用/旧限额保留，API及本地日志恢复，不问后台登录，不因轮询/重试补额度。
4. 默认最多3个新需求并行，wait_threads(timeoutMs=0)判断真实活动。P0先用冲突资源；P1持续推进，有排队P1时保留可用名额，不等待全部P0。已有P1不被新P0中断；制作已完成、只待平台异步上传的任务不因YouTube进度占制作名额。排队保留ready_to_dispatch，下轮恢复而非重开请求。

## 补交与经验收尾

负责聊天按编号接入的质量、partial:true、固定入库/共享/标签/命名/绑定及unknown保护继续；不在deliver后再问已授权提交同意。当前platform_managed路由不强制账号/任务组核验，受理绑定后不跟踪YouTube进度，不为缺链接重传。严重质量问题仍阻断对应版本，普通小瑕疵需真实发布审查，内部revise保留。

status.publication_followups只导航尚未提交/绑定的成片。活跃负责聊天自行继续；空闲且signal_state=prepared时，先signal {key}登记unknown，再执行返回的已授权send_message_to_thread，随后signal {key,response:真实发送回执}。sent不重发，unknown查原聊天/原请求；输入身份变化重新读取status。主控可向已交办负责聊天派发制作、恢复及固定回传，不向无关聊天/第三人发消息。精确素材/绑定已完整的旧任务不再因YouTube状态唤醒。

结案读knowledge-queue与hooks status，实际审查新增经验/反馈，按原scope关联现行知识；有依据才promote，review后用candidate-archive新指纹保留原文。案例副本/ASR是证据，空白占位不当经验；不重建已有检查点或为清空队列伪造验收。由负责聊天完成maintain RUN --close，未知费用、异议、活动现场及必要证据保留。

仅新接入、完成、明确失败或确需用户输入时通知具体编号及真实状态；无新项、非可操作变化、已知旧阻塞保持安静。同一内容版本/问题指纹不反复通知。登录/权限/分页失败保存真实缺口，不说没有新需求。应用定时任务通过automation_update维护，项目不复制登录凭据或安装隐式守护进程。
