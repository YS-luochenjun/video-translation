# 手动经验总结

用户在工作台点「总结新增经验」或在项目会话提出整理时执行。配置 `knowledge_daily.automatic=false`，旧定时入口 `hooks run --due` 返回 `manual_only`。Fireplay巡检负责接入和调度。

1. 读AGENTS.md、知识合同及 `.agents/skills/knowledge-curation/SKILL.md`，使用doctor验证的Python。读knowledge-queue与hooks status；保留原检查点、既有审查、原scope和公私边界。
2. 先按问题浏览待审队列，优先处理反例、有对照的修正和能改变下次制作决定的观察。需要结构化提炼时手动执行 `hooks run`，每轮最多处理24条来源。也可用 `hooks prepare` 和 `hooks apply` 由当前会话处理。沿用原检查点，超出本轮范围保留具体下一步。
3. 同源多语的共用问题审一次，各语言的证据、限制和结论分别保留。相同含义且适用范围一致时，优先补充现行方法。单源观察归入限定案例；跨原片推广须复验。已有规则覆盖的常见问题保留质检证据。使用 `knowledge-promote` 发布审定的正文，再用 `knowledge-review` 登记采纳和保留部分。全部处理的候选按预览指纹归档。
4. 读本次新增knowledge-use反馈及反例，不从命中推断使用，也不替活跃制作填写未观察的效果。普通开发者审查可在既有授权下自主完成；公司偏好/质量标准变化仍需明确授权。
5. 运行knowledge-audit并刷新project_health，保存输入/输出计数及真实审查回执到work/state。`new_records=0`不等于审查完成，同时核对adoption_queue_open和pending。不为清空队列伪造验证。

本任务不扫描或接入Fireplay、不调度制作、不做平台写回、不清理媒体/交付库、不自动commit/push。原始候选的指纹归档属于本任务的知识生命周期。仅在有新采纳、具体反例、明确失败或需要用户决定时通知；相同未变待办保持安静。
