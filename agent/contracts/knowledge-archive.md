# 知识候选退出与归档

总入口见 [knowledge](knowledge.md)。

## 候选退出队列与归档

MCP 对应入口为 `localizer_knowledge_advisories`、`localizer_knowledge_queue`、`localizer_knowledge_use`；正式方法仍走 `localizer_knowledge`。审查发布与归档使用以下 CLI，并按模板填写来源。

推广只是一个处理出口。重复内容可关联既有方法，只有合成意义的实验可结为历史，反例可以修订旧方法，证据不足则继续待审。`partial` 和 `pending` 不能归档；其余决定也必须明确全部内容已处理、剩余部分仅作历史，才能关闭。`adopted` 并不表示剩余限制获得推广。

```powershell
bin/va.ps1 knowledge-queue
bin/va.ps1 knowledge-review work/actual-review.json
bin/va.ps1 candidate-archive knowledge/candidates/actual-candidate.json
bin/va.ps1 candidate-archive knowledge/candidates/actual-candidate.json --execute --expect <预览指纹>
```

归档将原文件逐字节保存到 `knowledge/history/candidates/<哈希>/`，核验后从 `candidates/` 移除。映射保存在 `knowledge/curation/candidate-archives.json`；旧采纳表中的逻辑路径通过 `knowledge_records.resolve()` 继续解析，候选索引的 `storage_path` 指向实际原文。关闭的来源不再进入默认候选召回或每日提纯；`knowledge-queue --include-closed` 仍可追溯。已被部分采纳的文件不能仅凭采纳表批量删除。

历史正文按用途保留。用户授权清理时，可删除已审结的空占位、已由现行方法或精确同源案例完整覆盖的重复经验，以及无现行依赖的被替代正文。先核对现行方法、案例、待审来源和在制计划的实际依赖，再冻结删除清单与文件哈希。已结束任务的旧索引和历史报告中的来源标签可以随清理移除或保留为来源标识。保留独立的质量、费用、交付记录和能够改变后续决策的反例。实删后更新索引及版本替代关系，清理前后运行知识审计，回执置于本地工作状态。

知识分为初始方法、源限定参考和条件类方法。类方法按topic和内容特征检索：requires_features须全部满足，非空requires_any_features须至少满足一项，两组同时存在时共同成立。多源观察须绑定至少两个独立源的长期证据，不将同源返工计作跨源复验。类方法提供触发条件、步骤、失败签名和核验标准；示例的遮罩、坐标、字体参数及验收不推广。单源细节保留候选。

候选仍标candidate不代表全部内容未使用。人工审查的部分采纳关系记在knowledge/curation/，包含候选原文哈希、合并目标与未推广部分；它用于追溯，不直接加载进制作提示。候选文件或证据发生变化时须重新审查，不能仅因同名记录在旧采纳表中就跳过。

`knowledge/index.json`只索引与具体视频无关的方法及项目政策；`knowledge/cases/index.json`单独索引源限定参考。context分别返回knowledge和source_references，plan分别冻结；方法的适用条件不以案例视频哈希限定。一个方法可关联多个案例，案例只证明已有观察，不绑定方法只能在原视频使用。rules 不重复保存源参考；现行参考正文以 cases 索引为准，已替代正文位于 history。案例中的原文快照仍按 manifest 保留，不作为另一份现行规则维护。

启用采用有来源的用户明确反馈或开发者评审，经 `knowledge-promote SPEC` 建立独立正文和案例。记录 reviewed_by/at、来源、源哈希、目标语种、实际视频哈希和原话；通过 `knowledge-audit`。公司偏好/质量标准需要对应授权，自动总结不会修改它们。跨源、跨语种结论须有对应复验证据。

