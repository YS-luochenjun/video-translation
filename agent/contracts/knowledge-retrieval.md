# 知识检索与保留门禁

总入口见 [knowledge](knowledge.md)。

## 检索与保留门禁

选择的统一入口为 [Agent 方法选择](../../knowledge/rules/agent-method-selection-v2.md)。delivery_modes 限定 fast/strict，未声明的历史方法适用两种模式；具体检查强度依现行模式政策。requires_features 全部满足且 requires_any_features 至少一项（非空时）才适用；命中不表示必须调用模型。

语言 scope 默认 language_match=exact，完整标签不区分大小写匹配；只有审查发布的 base 条目才匹配同基础语言，scope 必须写基础标签。原案例不批量扩域。related_source_references 只发现同源同基础语言的其他标签案例，requires_language_review=true，不能当作已批准同语种参考或进入计划。地区、文字系统、发音与成片须重新审核。

`context`/`plan` 完整返回适用的 project_policy 和 retrieval_role=required 方法，另外最多取6条可选方法；所有条目先满足 active、时效、替代关系、scope、特征和模式条件。政策及必要方法不与可选方法竞争名额。输入阶段政策仍须匹配phase。内容同义特征通过config/content-features.json归一化；未知特征保留，不根据镜头运动臆测文字运动。读取正文及独立案例，正文或证据缺失/篡改时报错，不能静默丢知识。计划记录命中正文哈希。替代用superseded_by，接口/模型/语言变化时标记待复验或有效期。初始两条是开发者规则，未假装经过真实广告实验。

新启用方法的evidence引用必须通过 `evidence_references` 解析到案例内部文件。已有案例可用 `knowledge-evidence SPEC` 追加不可变证据包，索引的required_evidence声明必要标签；缺失、篡改、跨源或错视频阻断审计与检索。补证不改写原方法、历史评审或用户验收。旧成片来源标签仍由交付库查询，不能当作永久视频文件。

后续反例能够推翻旧案例的整片成功解释。原观察保留，追加独立反例与evidence_caveat，让检索同时呈现限制；局部镜像文字或声音边界的证据不能扩张成整片视觉成功。实际资产的使用资格另由有来源的quality-hold约束，不能只写知识候选而继续复用已否定底片，见 `agent/workflows/quality-feedback.md`。

清理runs或outputs前验证知识独立性、交付包内部依赖和未结算账本。验证以离开原目录仍可读/可恢复为准，路径指针和哈希本身不能恢复已删文件。归档到期后同源资产显示expired；再次使用需重新制作或恢复冷存储并验证。

直接查阅历史规则时，先核对索引状态。`superseded` 或带 `superseded_by` 的正文用于追溯，沿替代关系读取当前规则。新调用使用当前授权和[请求总预算](../../knowledge/rules/user-language-budget-60-v2.md)。

具体操作入口为 `.agents/skills/knowledge-curation/SKILL.md`；目录说明见 `agent/contracts/storage.md`。

## 必要方法和快速选择记录

retrieval_role=required 表示满足既有 scope/特征/模式后必须返回该指导，和政策一起不占额外六条可选方法名额；不表示必须执行对应算法。metadata 的 selection_review 绑定本次开发者审阅及哈希。历史/范围外方法仍不返回；首次未声明 retrieval_role 时为 optional，普通修订省略时继承上一版的必要角色及审阅来源，显式调整仍须正式审阅。

新请求按 content-led-localization-v1 记录三类信息载体及逐域方法选择。context.feature_origins 标识可从角色/文字清单直接得出的特征；Agent 不从这些事实臆测剧情、性别或未知人物。普通与新快速计划冻结实际分类、理由、知识与同源参考/候选版本，快速分支同样支持 knowledge_followup 和 knowledge-use。源解析快照不保存目标语言选择，换语言重新判断。
