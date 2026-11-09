# Fireplay在制新需求完成盯办

用户要求当前及后续人工新增需求合法接入并开始执行后，每20分钟检查是否全部完成并提交；未完成继续推进，普通项目问题选择实际第一个推荐项。唯一政策及原话在config/fireplay-monitor.json.completion_watch。它独立于永久30分钟新需求巡检，也不复活历史已完成批次的盯办。

## 创建与范围

1. 首次启用时在本地manifest登记enrollment_started_at，后续轮次保留此起点及history；新机器先恢复该检查点。已完整受理的旧批次不因旧格式缺结案文件自动重开，活动manifest内项目及真实未提交项仍逐项核查。用doctor验证的Python运行 `fireplay-monitor status`，读取completion_watch。它从全部实际ready负责请求（含人工接入）、未交付待办和活动manifest生成滚动范围，完整保留已盯办但暂不可见/缺记录/更换状态的项目；缺记录不算完成。未建聊、未确认语种的排队项仍走接入门禁，不伪造制作开始。
2. `ensure_active` 时核对work/fireplay-monitor/monitor-automation-roles-current.json和config指定manifest，并用automation_update查看实际ID。活动盯办只有一个，不限首次三项或固定批次；将新编号/UUID/真实threadId/hostId追加requirements，保留既有项、证据和history，不能覆盖旧范围来宣称全部完成。
3. 没有活动任务才用automation_update创建当前主控聊天的heartbeat，每20分钟、ACTIVE。创建前保存意图；实际回执含ID且读回匹配后才将manifest.status记ACTIVE。结果unknown先核查应用现有任务，不能盲目再建。完成时保存删除回执并记COMPLETE_DELETED，后续发现新需求并真实接入负责聊天时必须重新创建下一轮；新一轮使用新真实ID，不复活旧批次记录。提示词从config指定的项目模板读取，路径和主控聊天由当前宿主绑定。项目不安装cron、不存凭据、不手写宿主调度文件。
4. 宿主自动审批拒绝定时恢复/选择权限时保留原拒绝，不通过长期巡检、另一自动化或原聊天间接执行被拒绝动作。可以采用宿主实际允许的只读盯办：manifest记mode=read_only、followup_approval_required=true，status返回observe_only；只能读状态和报告，不恢复、不发送、不选项。人类重新明确批准且宿主审查通过后才更新为owner_followup；不能因下一轮到了就自动解除此限制。

## 每轮推进

1. 先读manifest及原授权、请求/预算/回传/parallel现场，分批用wait_threads(timeoutMs=0，最多8个)保存真实状态及cursor。运行中不重复发送；确有need_attention、idle/error、原聊天结束但缺项时read_thread核对当前实际问题/选项、在途模型、unknown费用及具体阻塞。
2. 普通项目提问在已授权需求、语种、额度和质量范围内，依据当前真实显示的第一个推荐选项回复原聊天，保存实际问题、顺序/推荐标记、选择依据和发送回执；只通过提供该选项的受支持工具操作，没有真实选项不得编造“已点击”。宿主强制审批/安全拒绝仍交人类，不代批不换接口；需要加额度、扩大范围、重发未知付费模型或放弃严重质量异议时不按第一项自动同意。
3. 无具体阻塞但停滞时沿原threadId恢复，按publication_followups的持久signal先unknown再实际发送、登记真实回执；unknown先对账。真实运行中只续租。租约、停滞重派上限及升级沿原配置；20分钟检查并不赋予每20分钟重复催办的权限。具体质量/预算/审批缺口定位后保留，不无限重复相同消息。
4. 原负责聊天继续实际制作/模型/费用/固定提交；主控只调度。ready先交，partial/pending持续补齐。保持原位替换、逐版首尾音频、每需求共享池及单原片单写入者门禁。入库→共享需求组并请求YouTube自动上传→语言及产品tag→编号加语言命名→实际其他执行人二创归属→精确需求绑定，逐项实际读回。

## 结案与停止

每项须有全部当前原片×全部语言实际哈希/平台ID/共享/标签/命名/归属/绑定读回，且当前fireplay-completion-check有效并fireplay-close。`completion_watch`计划核对当前content_version、UUID、绑定、completion-check及closure文件哈希；聊天idle/结束、消息sent、平台done、单批成功或临时不可见都不算全项完成。需要重新平台读回时按固定提交合同执行，不以旧摘要代替。

每轮都重新发现新增负责项并合并manifest；待付费结果、待选项、被阻塞、部分提交、已绑定但缺有效结案都属于未完成。“聊天目前不在运行”不等于没有待办。只有所有manifest范围项均核验结案且新鲜status没有新增未结负责项才返回delete_completion_watch，宿主再次核对实际范围未新增后通过automation_update删除**manifest内该ID**并保存真实回执。保留制作聊天、原预算、历史和unknown，永久fireplay仍ACTIVE。YouTube配额不足、未建任务或缺链接不延长结案，不跟踪下游或为缺链接重传。

每轮证据保存到work/fireplay-monitor；仅新增接入、全部完成、明确失败或需要人类输入时通知，同一旧阻塞保持安静。不得兼做全局知识或存储清理。

迁移安装与私有状态恢复见[换机器部署](../../docs/migration.md#fireplay滚动盯办迁移)。Git携带规则、模板与测试；应用自动化ID、真实聊天、预算、派发回执和检查点通过可信私有迁移单独恢复，缺记录先核查，不能重建预算或重复制作。
