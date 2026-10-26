# 知识、案例与交付素材

## 三种生命周期

- `knowledge/rules/`、`knowledge/examples/` 和 `knowledge/candidates/` 保存项目开发所得的方法、训练案例和未启用经验，可进入Git。源/语种限定是适用范围，不等于个人私有；通用技术经验与素材限定经验都应按原scope保存，不因搬目录扩大结论。
- `knowledge/local/` 留存私有客户数据、原始证据和个人偏好；不把所有技术学习都归到local。项目案例用经过整理的实际观察、哈希、必要对照与原文方法；manifest中的文件就是完整依赖，旧路径仅为历史来源标签。正文及公开案例不依赖local、run或交付素材，私有原始证据另行独立留档。
- `outputs/<源>/<语种>/<版本>/` 是可到期的交付/复用包，`runs/` 为工作过程。交付包包含源片、实际成品、语言资产、准备依赖和原有技术状态，可以离开原run恢复。删除交付包会丢失视频与素材，知识仍独立存在。

项目知识可版本管理；原始私有案例、outputs、runs、本地索引和密钥留在本地。私有迁移原文/旧索引存 `knowledge/local/history/`；公开的已替代正文集中在 `knowledge/history/`，两套正式索引保留替代关系。历史失败评审保持原决定，当前正文只有一份。目录导航见 `knowledge/README.md`。

## 记录、提纯、启用

`deliver` 自动生成交付包、候选案例和持久inbox；已有候选及实际评审的失败结案使用 `reflect`。尚未形成候选时，按 `agent/templates/preproduction-failure.json` 用 `close-failure RUN SPEC` 保存有证据的失败观察，不补造质量报告。技术复盘另存项目candidate，原始媒体证据留私有案例；个人/客户保密复盘在review标注knowledge_class后保持私有。重复收尾不重复生成候选、不重发付费任务。自动记录不是自动证明新结论，也不代表已配置后台定时服务。

每次结案保存简短结果；有新原因、有效修正、反例、成本改善或用户纠正时提纯。相同含义且范围一致的知识合并证据，保留来源、反例与版本；同一素材多次返工不算多个独立复验。正文不得引用可删除的run/output/work文件作为使用前提；资产可用性由交付库单独查询。

`reflect` 只产生candidate，不被正式检索加载。候选包含真实结果、假设、失败签名、有效范围、限制与下一次反证。新反馈生成新记录，不把整体认可改写为分轨无损、独立评审或所有细节通过。

候选可以通过独立的 `knowledge_advisories` 通道按需参考：`context`、`codex-packet`、`work-packet` 与新 `plan` 最多返回3条，按同源/语种或显式内容特征匹配；源和语种约束不放宽。候选不是正式方法，只能提出风险、试验或补证方向，不覆盖当前规则、不放行质量、不授权模型或费用。原始stage仍是历史适用条件，不能因出现在其他阶段的工作包就扩大范围。使用前读取原文和限制；计划保存召回内容与原文哈希。没有匹配、已结清或不具备明确匹配条件时不填充无关条目。

## 从提纯到采纳，再回到制作

1. `hooks` 提纯新增来源，建议合并目标、限定案例、新方法或缺证据项；这些建议保持candidate。`knowledge-queue` 汇总原始候选、当前提纯版本和使用反馈，显示历史采纳表、当前审查与具体下一步。不要为已处理来源换个标题再次生成候选。
2. 主控按 `agent/templates/knowledge-review.json` 审查。`knowledge-review SPEC` 记录原文哈希、审查者、来源、采纳部分、保留部分、目标版本和下一步。`adopted/partial/duplicate` 必须指向已启用且哈希匹配的方法/案例；新方法或修订先走 `knowledge-promote`，可用 `candidate_sources` 绑定候选来源，再登记采纳。公司偏好和质量标准变化仍遵守原有授权范围。
3. 方法的使用效果用 `agent/templates/knowledge-use.json` 记录，执行 `knowledge-use RUN SPEC`（SPEC相对run）。只能绑定冻结计划中实际选中的正式知识、同源参考或候选，分别报告 `helpful/ineffective/counterexample/not_used`。实际使用需要真实证据；未使用需要解释，不能从检索命中推断使用或成功。当前计划、输入和视频哈希必须匹配，证据复制到独立本地反馈包。
4. `reflect` 与 `work-packet` 的 `knowledge_followup` 列出尚未记录使用状态的条目。结案时主控补齐反馈，随后处理 `knowledge-queue`；知识收尾不替代或伪造视频验收。负面反馈在同源同语种检索原方法版本时以 `review_alerts` 返回，并进入修订队列。它不是直接改写规则；审查后发布带 `supersedes` 的新版本或说明无需修改，再关闭反馈。

全部为 `not_used` 的回执只记账，退出未反馈清单；不作为新经验进入召回、提纯或待审队列。部分实际使用的报告保留整体来源，按实际结果审查。
5. 原记录不覆盖；审查修订通过 `previous_review` 链接上一份决定。采纳目标正文快照、来源和失败判断保留。每日Hook不自动发布方法，主控负责完成审查、发布与使用反馈；缺证据时保留明确待办。

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

知识分为初始方法、源限定参考和条件类方法。类方法按topic和内容特征检索：requires_features须全部满足，非空requires_any_features须至少满足一项，两组同时存在时共同成立。多源观察须绑定至少两个独立源的长期证据，不将同源返工计作跨源复验。类方法提供触发条件、步骤、失败签名和核验标准；示例的遮罩、坐标、字体参数及验收不推广。单源细节保留候选。

候选仍标candidate不代表全部内容未使用。人工审查的部分采纳关系记在knowledge/curation/，包含候选原文哈希、合并目标与未推广部分；它用于追溯，不直接加载进制作提示。候选文件或证据发生变化时须重新审查，不能仅因同名记录在旧采纳表中就跳过。

`knowledge/index.json`只索引与具体视频无关的方法及项目政策；`knowledge/cases/index.json`单独索引源限定参考。context分别返回knowledge和source_references，plan分别冻结；方法的适用条件不以案例视频哈希限定。一个方法可关联多个案例，案例只证明已有观察，不绑定方法只能在原视频使用。rules 不重复保存源参考；现行参考正文以 cases 索引为准，已替代正文位于 history。案例中的原文快照仍按 manifest 保留，不作为另一份现行规则维护。

启用采用有来源的用户明确反馈或开发者评审，经 `knowledge-promote SPEC` 建立独立正文和案例。记录 reviewed_by/at、来源、源哈希、目标语种、实际视频哈希和原话；通过 `knowledge-audit`。公司偏好/质量标准需要对应授权，自动总结不会修改它们。跨源、跨语种结论须有对应复验证据。

## 检索与保留门禁

选择的统一入口为 [Agent 方法选择](../../knowledge/rules/agent-method-selection-v2.md)。delivery_modes 限定 fast/strict，未声明的历史方法适用两种模式；具体检查强度依现行模式政策。requires_features 全部满足且 requires_any_features 至少一项（非空时）才适用；命中不表示必须调用模型。

语言 scope 默认 language_match=exact，完整标签不区分大小写匹配；只有审查发布的 base 条目才匹配同基础语言，scope 必须写基础标签。原案例不批量扩域。related_source_references 只发现同源同基础语言的其他标签案例，requires_language_review=true，不能当作已批准同语种参考或进入计划。地区、文字系统、发音与成片须重新审核。

`context`/`plan` 完整返回适用的 project_policy 和 retrieval_role=required 方法，另外最多取6条可选方法；所有条目先满足 active、时效、替代关系、scope、特征和模式条件。政策及必要方法不与可选方法竞争名额。输入阶段政策仍须匹配phase。内容同义特征通过config/content-features.json归一化；未知特征保留，不根据镜头运动臆测文字运动。读取正文及独立案例，正文或证据缺失/篡改时报错，不能静默丢知识。计划记录命中正文哈希。替代用superseded_by，接口/模型/语言变化时标记待复验或有效期。初始两条是开发者规则，未假装经过真实广告实验。

新启用方法的evidence引用必须通过 `evidence_references` 解析到案例内部文件。已有案例可用 `knowledge-evidence SPEC` 追加不可变证据包，索引的required_evidence声明必要标签；缺失、篡改、跨源或错视频阻断审计与检索。补证不改写原方法、历史评审或用户验收。旧成片来源标签仍由交付库查询，不能当作永久视频文件。

后续反例能够推翻旧案例的整片成功解释。原观察保留，追加独立反例与evidence_caveat，让检索同时呈现限制；局部镜像文字或声音边界的证据不能扩张成整片视觉成功。实际资产的使用资格另由有来源的quality-hold约束，不能只写知识候选而继续复用已否定底片，见 `agent/workflows/quality-feedback.md`。

清理runs或outputs前验证知识独立性、交付包内部依赖和未结算账本。验证以离开原目录仍可读/可恢复为准，路径指针和哈希本身不能恢复已删文件。归档到期后同源资产显示expired；再次使用需重新制作或恢复冷存储并验证。

直接查阅历史规则时，先核对索引状态；`superseded` 或带 `superseded_by` 的正文仅用于追溯，沿替代关系读取当前规则。预算现行入口为 [请求总预算](../../knowledge/rules/user-request-budget-20261026.md)，历史额度和旧plan中的知识快照不构成新调用授权。

具体操作入口为 `.agents/skills/knowledge-curation/SKILL.md`；目录说明见 `agent/contracts/storage.md`。

## 必要方法和快速选择记录

retrieval_role=required 表示满足既有 scope/特征/模式后必须返回该指导，和政策一起不占额外六条可选方法名额；不表示必须执行对应算法。metadata 的 selection_review 绑定本次开发者审阅及哈希。历史/范围外方法仍不返回；首次未声明 retrieval_role 时为 optional，普通修订省略时继承上一版的必要角色及审阅来源，显式调整仍须正式审阅。

新请求按 content-led-localization-v1 记录三类信息载体及逐域方法选择。context.feature_origins 标识可从角色/文字清单直接得出的特征；Agent 不从这些事实臆测剧情、性别或未知人物。普通与新快速计划冻结实际分类、理由、知识与同源参考/候选版本，快速分支同样支持 knowledge_followup 和 knowledge-use。源解析快照不保存目标语言选择，换语言重新判断。
