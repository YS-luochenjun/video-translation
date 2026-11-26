# 制作、检查、返工、交付

当前用户授权的默认模式是[快速交付](../workflows/fast-delivery.md)。新请求记录 `delivery_mode=fast`，优先按该工作流完成基本效果、增量检查和轻量收尾；下文完整逐实例门禁仍用于严格路线。模式变更不改写旧候选的审核结果。

所有任务同时遵守[最终输出](../workflows/always-output.md)：下文门禁决定质量通过和返工；返工结束仍用 `finalize` 输出当前最佳完整翻译视频，不能因分数未达标而无视频结案。旧 `close-failure` 保留失败证据，但不代替新任务的最终视频。

续作和切换阶段时优先运行 `work-packet RUN [--stage source|translation|neutral|render|review|delivery]`，从现有状态取得待办、任务恢复提示与知识入口，不另写重复进度日志。它只导航，不替代知识正文、真实观察或审核。制作的缓存、资源限制和兼容入口见 [缓存与执行恢复](../../docs/workflow-optimization.md)。

制作、返工和用户反馈时主动按[有界改进循环](../workflows/continuous-improvement.md)执行工作包的 `improvement_loop`：完整播放与听审、原片/译片整幅对照、提出具体反例、定位漏检原因、单变量修复、前后及未改区验证、知识反馈。`capture`自动生成最多12组原生整幅探针；只生成证据，不提供通过结论。普通瑕疵与到界收口继续按原完整输出/提交政策，不以改进循环延长边界。

工作包中的 `knowledge_advisories` 是待验证观察，和正式 `knowledge` 分开。按需读其原文，用作风险提醒或试验依据，不能直接作为通过标准。结案时按 `knowledge_followup` 用 `knowledge-use` 记录实际采用、未采用及效果，再审查 `knowledge-queue` 中本次新增或受反例影响的内容，具体见 [知识合同](knowledge.md)。

已有诊断预览、重复修复或正式候选尚未交付时，按 [制作收口](../workflows/production-completion.md) 处理：先完成 `next_action` 指出的当前缺口，复用已核验资产；当前候选待审则补实际审核，quality通过则直接deliver。水印／发布者标记默认去除，识别其文字/图形身份并检查片尾同标；用户本次明确要求保留的例外记录来源，旧评审不覆盖。

按当前阶段进入对应章节。各专题保留原章节正文与执行依据。

## 1. 收件

[阅读此章节](workflow-source.md#1-收件)。

## 2. 解析

[阅读此章节](workflow-source.md#2-解析)。

## 3. 判断与执行

[阅读此章节](workflow-production.md#3-判断与执行)。

## 4. 检查与返工

[阅读此章节](workflow-review-delivery.md#4-检查与返工)。

## 5. 交付与学习

[阅读此章节](workflow-review-delivery.md#5-交付与学习)。

## 信息载体与方法选择记录

[阅读此章节](workflow-content-routing.md#信息载体与方法选择记录)。

