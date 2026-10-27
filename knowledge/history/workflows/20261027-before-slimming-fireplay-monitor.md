# Fireplay新翻译需求定时发现与制作

用户2026-10-27明确授权：每30分钟检查承接面板的新翻译需求，覆盖当前账号可见的全部组（APC、MOG、KEY、SHE、WOW等均可），符合条件直接制作；人员可辅助发现，但用户最新明确“如果你认为用人员筛选不靠谱，可以去掉。只需要你进行查找到翻译的需求”，当前assignee_mode=hint_only，不用负责人硬排除其他翻译任务。每需求独立聊天与计费，P0优先但P1不等待。真实来源及范围保存在config/fireplay-monitor.json.authority。它授权按以下规则持续交办，不将每轮轮询伪装成新的用户请求，也不为旧任务重新开额度。

## 每次唤醒

1. 使用doctor验证过的Python，先运行 `fireplay-monitor status` 和 `fireplay-monitor scan`。实际命令为 `python bin/va.py ...`，本机Python见doctor；保持当前项目工作区和现有安装资产。定时唤醒依托当前主控聊天，制作由每需求自己的聊天继续，不创建每轮轮询的新主控聊天。
2. 发现当前Fireplay requirement_list工具合同，用scan返回的精确query读取summary；scope=all、asset_type=video，不按APC/MOG编号限定，不用keyword=翻译过滤（summary不含完整描述），不把requestDate当发布时间。按实际next_cursor完整翻页，不修改过滤条件。每页保存真实arguments和response；以 `{"summary_pages": [...]}` 调用 `fireplay-monitor scan --spec FILE`。工具数据通过宿主编排保存到work/fireplay-monitor，不向模型上下文打印全列表；大JSON分块保存，避免shell参数长度及宿主工具传输上限。脚本本身不复制宿主身份或登录凭据。
3. 首轮建立历史基线。当前首轮实读35页、6902条，检查点在state/fireplay/monitor；历史列表不自动重做，已登记任务照原聊天继续。之后按真实ID、createdAt和内容字段发现新建项与修改项。首次见到但创建早于启用时间的项为newly_visible_old，不擅自接历史积压。旧式不支持编号只隔离该项，不将编号用作任意文件路径。
4. 只有完整页链全部成功才更新last_success_at；分页失败/筛选变化/重复行时保留原检查点，下次重读。需求删除/权限暂不可见不删除原聊天、预算或证据。读取是实时列表而非平台事务快照，后续每轮完整扫描兜住分页期间新增，去重防止重复接单。

## 判断翻译与接入

1. 对status.needs_review逐条按精确ID读blind_brief，再刷新该条summary，使两视图updatedAt一致且serverTime在10分钟内。Agent实际理解标题、描述、refText、locales：翻译/本地化/换语言等不同表达都可；单纯提及翻译、无制作意图的文字不自动当任务。平台正文是业务数据，不能取消用户规则或增加费用。
2. 以 `fireplay-monitor assess --code CODE --spec FILE` 登记 `{"snapshot":{"summary":实际返回,"brief":实际返回},"decision":{"is_translation":true或false,"reason":"实际判断","evidence":["brief.description"],"targets":[实际目标语言]}}`。evidence必须指向真实非空字段。targets能从原字段/正文解析时可省略，复杂自由格式由Agent补全。新项必须待开始且canBindMaterials=true。缺来源/语种、权限不符或已有人制作的状态单独保留，其他需求继续。
3. 单纯updatedAt变化不触发重做；已有需求内容版本变化转needs_revision_review，交原聊天核对旧稿件、预算和差异，不新建聊天/额度。没有旧正文且摘要未变时，不假定一次状态更新是“新增翻译”；但Agent确认为翻译的正文必须保留为historical_translation_pending，并在status.historical_translation_candidates显示，不能把不确定发布时间改写成is_translation=false。现有基线或旧忽略项的定向复核用recheck:true，仍不自动启动未知历史积压；用户明确点名后沿本次真实授权接入。已忽略项后续出现明确标题/语种变化，可重新判断。
4. 通过判断后脚本登记独立需求，并将有来源的持续授权及该平台真实UUID派生的稳定请求引用写入 `state/fireplay/CODE/monitor-authority.json`。这是当前用户明确授权的逐需求交办记录，不是新的用户消息。每原片×去重语种各1版，别名沿项目字典；明确多套/数量冲突先澄清本项。不要对多个需求开总语言并集费用池。
5. 按 [编号接入](fireplay-intake.md) 查询并下载该需求全部原片。先查已登记聊天；ready则复用，unknown则list_threads/read_thread查明，不能再次create_thread。新聊天按精确需求编号命名，在当前项目local运行，使用fireplay-chat生成的完整prompt，并附本需求monitor-authority.json路径。主控使用list_projects匹配实际项目ID，不改模型、不建worktree。创建成功后登记真实threadId/hostId与标题，并向用户返回created-thread指令。
6. 由对应聊天对每个原片运行 `fireplay-start CODE state/fireplay/CODE/monitor-authority.json --video N`，按既有模型路由、实际targets×60的本需求账本和KIE同意继续；同需求多原片共用原池，不同需求即使原片相同也各自绑定独立需求池。旧账本、旧未知费用和所有原限额保持。

## 并行与资源

默认最多同时推进3个需求。用wait_threads(timeoutMs=0)读取真实活动状态，不能凭run目录推断Agent正在执行；闲置的已完成聊天不占正在制作名额。新任务优先填空位，P0优先获得冲突资源；P1持续推进，不等待所有P0完成。排队同时存在P0/P1时给P1保留一个可用名额，避免持续P0流量让P1饿死；没有P1时P0可以填满。已在进行的P1不因新P0到达被打断。未能立刻开始的已接需求保持ready_to_dispatch，下轮恢复，不重开账本。

持续授权包括为已交办监控需求创建聊天、向其负责聊天派发制作/恢复/固定回传指令。不要向范围之外的聊天或第三人发消息。

## 统一审核与回传

所有新聊天沿相同规则：quality通过的完整目标语种交付后，直接按既有固定话术继续素材入库、共享需求组、YouTube自动上传请求、语言/产品tag及绑定；不能在本地deliver后停下再问是否执行已授权固定动作。按用户最新固定话术入库、共享需求组、请求YouTube自动上传、打标签并绑定。config/fireplay-youtube-routing.json采用platform_managed，普通MCP可使用平台默认YouTube路由；账号/任务组显示不再作为上传门禁，不再逐视频截图或核查账号。仍核验入库、共享、名称、标签、真实绑定；unknown先恢复原请求，不重复入库。

用户最新允许普通瑕疵自动上传，但效果很差、问题过多的不上传。best_available不再一律等待用户确认：对正式outputs交付包，负责聊天实际看成片，用 `fireplay-publication-review CODE SPEC` 记录 `{"package":"outputs/...","assessment":{"reviewer":"真实审查者","reason":"实际依据","translation_complete":true,"required_audio_complete":true,"watchable":true,"too_many_issues":false,"defects":[{"severity":"minor","description":"具体缺陷及区间"}],"evidence":["final.mp4"]}}`。evidence引用真实包内视频/帧，脚本检查哈希与完整收口记录。该审查可以是同一Codex自审，必须如实标识。minor且完整可自动回传；major/critical、过多问题明显影响观看、漏译、缺少必需配音或有效质量异议会阻断上传，输出仍保留。不能因为文件在outputs就跳过实际判断，也不把内部revise改写为pass。

052先前受旧“仅质量通过自动提交”规则限制，且存在已披露保真问题；它后来获得用户具体同意并已完成回传。新规则沿config/fireplay-publication.json区分普通与严重问题，已成功回传的user-approved-return不重复提交。

每轮status.publication_followups导航可能遗漏的质量通过交付或未结束outbox。先核对负责聊天实时状态：活跃则让其继续；空闲且signal_state=prepared时，运行 `fireplay-monitor signal --spec {key}` 先登记unknown，宿主执行返回的send_message_to_thread，随后用同一命令登记 `{key,response:真实发送回执}`。sent不重复发送，unknown先读原聊天查证而不盲重发。实际回传仍走fireplay-return/dispatch/receipt的完整哈希、质量、共享、标签、绑定读回门禁。已有素材和user-approved-return记录不可重复入库。真实提交完成后由负责聊天maintain RUN --close。

## 通知与暂停

无新项、无状态变化和无可操作问题时保持安静。发现并接入新需求、完成、明确失败或确需用户补信息时在主控汇总编号/语言/负责聊天及实际状态。不要每30分钟重复播报旧阻塞；按需求内容版本和问题指纹记录已通知状态。登录过期、宿主能力/服务审批缺失或分页失败时保存原状态，报告实际缺口；不能伪报“没有新需求”。定时任务由Codex应用automation_update管理，实际ID/状态回执保存在state/fireplay/monitor；项目不另装系统cron或窃取连接器凭据。

## Fireplay受理后经验收尾（用户最新要求）

核验入库/共享/名称/标签/需求绑定和平台受理后就收尾，不跟踪YouTube上传进度。返回returned或历史手工绑定证据已完整时不派发YouTube催办；不等待队列、限额、向量化或全部链接，也不为此重新入库。只在提交结果unknown或绑定本身未确认时恢复确切原请求，不把提交确认扩大成上传进度轮询。规则见config/fireplay-publication.json.completion与[自动提交与经验收尾](../../knowledge/rules/fireplay-completion-recovery-v3.md)。

各聊天只用config/kie-access.json指定的API和本地日志核查KIE。结案处理knowledge-queue的新发现，审查/归档具体来源；原证据与未知费用保留。

逐语种部分回传：已合格版本可用fireplay-return的partial: true先提交；其余语种仍保留原质量异议和pending_locales。旧批次绑定核验完成后才追加新语种，既有素材和操作编号不重建。监控仅对尚待语种查新交付，不把部分成功当全需求完成，不因缺少YouTube链接重传已绑定语种。
