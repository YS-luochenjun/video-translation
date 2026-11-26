# Fireplay 需求发现与轮询

总入口见 [fireplay-monitor](fireplay-monitor.md)。

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

