# Fireplay 派单、授权与需求状态

总入口见 [fireplay-intake](fireplay-intake.md)。

## 聊天、授权与制作

角色边界：工作台负责分配及检查；独立制作聊天负责实际完成指定原片的全部目标语言视频、质量审核及平台提交。交办消息是制作请求而非状态查询；只有实际交付或真实不可恢复的具体阻塞才结束，不以报告未完成代替执行。

1. `fireplay-chat CODE --video N`预览标题和提示。单原片使用需求编号，多原片使用需求号-1、-2、-3。各聊天仅制作自己的原片和该片语种。第一个实际绑定的聊天协调整单状态。已承接需求沿原聊天继续。
2. 下载并登记该原片后运行 `fireplay-chat CODE --video N --execute`。`queued` 等待全局名额。`needs_status_start` 表示已占名额，按下节完成状态写回。仅 `prepared` 时按返回的提示调用项目本地 `create_thread`，执行模型按[巡检恢复规则](fireplay-monitor.md#补交与经验收尾)使用 GPT-6.2 Sol。用 `set_thread_title` 设置精确标题并以真实 `threadId`、`hostId`、`title` 绑定。`unknown` 时查原创建回执并绑定原会话。
   创建首轮与工作台登记绑定是异步的。制作聊天应立即调用终端做doctor和原片状态检查，绑定就绪即实际启动，不因暂未登记或已授权事项提前结束。工作台绑定后做一次启动交接核对：读取真实聊天状态及本地制作记录；若运行中不打断，若空闲且尚无真实制作开始证据，核查实际阻塞后通过原聊天的持久signal派发启动指令并登记发送回执。不得用建聊成功或首轮结束代替制作开始；不重复建聊、不重置账本，也不等待完整制作结束才承接下一项。
3. 新原片先按[历史译片与原片复用](fireplay-intake.md#历史译片与原片复用)完成有界核验。负责聊天在绑定和复用决定就绪后执行 `fireplay-start CODE AUTHORITY --video N`。若返回 `reuse_preflight_required`，按该流程登记后重试同一命令。AUTHORITY 包含 authority=user、稳定 authorization_ref、user_request、mode=first/reuse 及真实来源。续作用原请求和账本。监控授权文件为 `state/fireplay/CODE/monitor-authority.json`。本需求多原片共用真实去重语言×60的独立账本，并保留已发生和未知费用。
4. KIE持续同意读config/fireplay-intake.json.kie及本需求kie-user-authorization.json；fireplay-start绑定真实需求、语种、内容版本、请求和原预算，工作区automatic_use=true时直接使用范围内模型及必要媒体传送，不逐次问同意。项目询问是否需要/同意KIE音频或视频时依据持续授权直接确定为需要、同意；缺本需求绑定先fireplay-start，不把它误当成需要用户再次同意。宿主强制审批不代用户点击。仅API/真实taskId/保存响应/本地费用日志恢复；用户没有后台登录权限。超时无可查询ID保留未知费用，不重扣、不重开额度。模型与返工上限仍按制作合同，宿主审批按其有效政策。
5. 按[本地化流程](video-localization.md)完成实际观察、翻译、选路、制作及审核。共用底片不继承别的语种验收；同名/同源的不同需求仍独立账本。P0只优先冲突资源，不停止P1。主控协调，实际制作与回传由对应聊天继续。

## 需求状态

1. 新接入的「视频翻译」「未开始」需求按此规则管理状态。第一个原片占到名额后，刷新精确UUID的summary和blind_brief。用 `fireplay-transition CODE start SNAPSHOT --execute` 登记写入并取得 `requirement_update_status` 参数。通过宿主调用后重新读取两种视图，执行 `fireplay-transition CODE start SNAPSHOT` 确认「进行中」，再运行原片建聊命令。随后原片继续按同一需求状态领名额。
2. 各原片会话可分批提交自己的语种。最后一批绑定读回自动生成整单交付校验。由 `fireplay-status.coordinator_chat` 指定的协调会话直接把本地 `receipts/<原片序号>-bind.json` 交给 `fireplay-transition CODE finish RECEIPT --execute`。回执须含新鲜的 Fireplay delivery 读回、完整需求字段、权限及全部绑定。字段不全时补读取 summary 和 blind_brief，附件来源另附 delivery。整单校验缺失、过期或平台版本变化时，用精确需求的 delivery 视图执行 `fireplay-completion-check`。实际调用状态工具后，取同一需求最新 delivery 视图读回「已完成」，用不带 `--execute` 的 `fireplay-transition CODE finish RECEIPT` 确认，随后执行 `fireplay-close CODE`。YouTube 发布进度由平台继续处理。
3. 状态更新参数包含平台真实 `updatedAt`，防止覆盖别人刚做的修改。未知结果先查原回执和最新状态。确认第一次未生效、状态和版本仍适用时，可带 `--retry --execute` 有界恢复一次。其他状态逐项核对。无法继续建聊时，可用 `fireplay-chat CODE --video N --release-reservation` 释放尚未发起创建的预约，保留原状态回执。

