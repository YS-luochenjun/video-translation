# 知识入口

先按索引区分现行方法与具体来源，再读正文和它绑定的证据。目录中的文件数量不是有效知识数量；运行 `bin/va.ps1 knowledge-audit` 查看当前可检索条目。

| 位置 | 唯一职责 | 何时读取 |
| --- | --- | --- |
| [index.json](index.json) 与 `rules/` | 当前通用/条件方法和项目政策 | `context.knowledge` 命中后 |
| [cases/index.json](cases/index.json) 与 `cases/` | 具体源视频、语种和版本的观察、反馈及限制 | `context.source_references` 命中后 |
| `examples/` | 由原始 manifest 绑定的图片、音频和观察；重复字节由共享对象保存 | 正文要求核对证据时 |
| [candidates/index.json](candidates/index.json) 与 `candidates/` | 待处理候选；索引同时保留已归档原文位置，不自动启用 | 审查采纳，或制作时经独立 advisory 通道按需参考 |
| `curation/` | 部分采纳、结构整理与来源对应关系 | 追溯某条经验如何进入现行方法时 |
| `distillations/` | 项目 Hook 生成的候选及独立来源快照 | 审查每日提纯结果时 |
| [history/](history/README.md) | 已被替代的规则、源案例原文及已处理候选 | 追溯旧决定与候选原始来源时 |
| `local/` | 客户私有证据、质量异议、候选与检查点 | 本地任务需要时；不进入源码导出 |

`rules/` 不再保留 `cases/` 的兼容副本。两份索引继续保存旧条目和替代关系，但历史正文集中在 `history/`，不会被正常检索加载。已删除旧路径仅作为来源标签，迁移对应表见 [结构整理记录](curation/structure-20261022.json)。

相似文字不总是重复知识：通用方法描述处理步骤，案例说明某次成功或失败的证据边界。`examples/**/original-method.md` 是当时正文的不可变快照，跟随 manifest 校验，不作为第二份现行规则维护。连续帧和声音证据支持不同时间边界，不能按文件名或相似缩略图删除。

同源多语言、多轮返工仍是一个来源。候选合并须保留各版本哈希、反例和未采纳部分；结构整理不扩大适用范围，也不改变历史验收。操作合同见 [知识规则](../agent/contracts/knowledge.md)。

## 按场景选择

[Agent 方法选择](rules/agent-method-selection-v2.md) 统一政策优先级、主方法及辅助方法的组合。方法按实际特征和请求模式检索，家庭/医院/校园等背景不直接决定算法；特征定义在 `config/content-features.json`。角色声线、声音事件、识别分歧与时间配合分别有条件方法。Agent 在现有 reason/evidence 说明首选/备选、切换及停止依据，不从命中推断已经使用。

语言 scope 默认完整匹配；经审查的基础语言 scope 才可扩大。`related_source_references` 为同源同基础语言的范围外发现线索，须重新语言审查。旧规则与未索引的选路草稿已按原字节留存，替代与迁移见 [八项整理记录](curation/selection-alignment-20261026.json)。

## 证据存储与旧路径

每个案例的 `manifest.json` 保留原始字节、逻辑路径、来源、scope 和判断。只有 SHA-256 完全相同的证据合并到 `examples/_objects/`；[storage-index.json](examples/storage-index.json) 将各原路径映射到对象，并保存原哈希和长度。连续帧只要字节不同就分别保留。共享一份图片不代表不同案例或语言得到相同结论。

读取 manifest 后，先查存储索引：有映射则读取对象，无映射则读取原文件。代码使用 `bundles.asset_path()`；人工可用以下命令解析原路径，输出实际文件位置及核验后的哈希。`context` 中的 `evidence_storage_index` 提醒调用方执行此步骤。

```powershell
.venv/Scripts/python.exe bin/knowledge_maintenance.py resolve knowledge/examples/<案例>/evidence/<文件>
.venv/Scripts/python.exe bin/knowledge_maintenance.py check
```

案例仍独立于 `runs/`、`outputs/` 和本机素材；迁移或导出时须一起携带整个 `knowledge/examples/`，包含共享对象和存储索引。单独复制一个案例子目录不再是完整证据包。原 manifest 哈希未变，旧采纳表中的案例哈希仍可校验；历史观察里的旧路径仍是来源标签。

新增证据先按原方式归档。后续去重先运行 `bin/knowledge_maintenance.py preview`，核对清单后再运行 `compact --execute --expect <预览指纹>`。工具先复制并核验所有对象、原子写入索引，再删除被替代的文件；中断后可重新预览并继续。这里所有命令均使用项目的 `.venv/Scripts/python.exe` 执行。

## 候选处理状态

候选原文中的 `status`、历史 outcome、范围、证据和限制保持不变。派生索引覆盖 JSON 与补充 Markdown，保存每份原文的哈希；`reviews` 绑定采纳表的路径、哈希和分组，未采纳部分及历史质量异议仍读原表。

- `partial_adoption_recorded`：存在哈希匹配的部分采纳记录；不能理解为整条候选已启用。
- `no_adoption_record`：尚未找到相应采纳表；不能据此断言内容从未审查。
- `synthetic_only` / `historical_retained`：采纳表明确仅保留合成实验或历史快照，没有采纳目标。其他无采纳目标的审查标记为 `reviewed_without_adoption`。
- `exact_hypothesis_groups`：仅将完全相同的假设文字分组浏览，不合并不同语言、源哈希、成片结论或反证。

`adopted_in_historical` 保留采纳当时的目标；旧规则沿正式索引的 `superseded_by` 找现行版本，旧目录沿 `curation/` 的迁移记录追溯。自动结案登记候选时会刷新索引；手动新增候选或采纳表后运行 `.venv/Scripts/python.exe bin/knowledge_maintenance.py reindex`。若采纳表绑定的原文哈希不符，刷新会报错，不会套用旧判断。

`history/` 保留既有文件和原文，不参与正常方法检索。本次 [旧候选索引](curation/candidate-index-before-dedup-20261023.json) 和 [存储迁移记录](curation/evidence-storage-20261023.json) 保留迁移前的哈希，去重不会删除来源与失败判断。

## 审查、实际使用与退出候选队列

`knowledge-queue` 才是当前待处理入口：它同时汇总原始候选、当前提纯版本和使用反馈。旧采纳表提供历史依据，新审查决定保存在 `curation/reviews/`（私有来源留在local），通过原文哈希和 `previous_review` 保留修订链。提纯建议与部分采纳不会自动变成正式规则。

`context`、`codex-packet`、`work-packet` 和 `plan` 提供独立的 `knowledge_advisories`，最多3条匹配观察。读原文及限制后可设计试验、避免已知错误；正式方法不足也不表示候选已经成立。每次实际使用用 `knowledge-use` 绑定当前计划、原文版本、视频与证据，明确采用效果或未采用。负面结果以 `review_alerts` 返回到同源同语种的原方法检索，同时进入修订队列。

已完全处理的候选可以从此目录移除：`candidate-archive` 先预览，再带指纹执行，原始字节保存在 `history/candidates/`。`candidate-archives.json` 保持旧来源路径可追溯；索引里的 `storage_path` 是实际文件位置，`queue_state=archived` 表示已退出默认队列。原始status/outcome保留历史含义，当前处理状态以审查链为准。只有部分采纳的内容仍保留待办，不批量删除。详细命令与表单见 [知识合同](../agent/contracts/knowledge.md)。

## 信息载体与防漏入口

[三类广告条件](rules/content-led-localization-v1.md) 说明音频主导、画面文案主导及混合型的适用条件和片段例外。旁白与对白都翻译。角色/文字事实补齐检索标签，Agent 保存分类与选路证据；必要方法完整返回，可选方法有界。普通和快速计划都冻结选择及知识版本，缺少旧记录时如实补登记，不改写历史质量或费用。
