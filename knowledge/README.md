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

| 问题 | 现行入口 | 使用边界 |
| --- | --- | --- |
| 内容分类与主/辅助路线 | [Agent方法选择](rules/agent-method-selection-v2.md)、[三类广告](rules/content-led-localization-v1.md) | 按实际音频、文案、运动及遮挡选路；记录首选、备选、切换和停止条件 |
| 图片与连续视频修复 | [ImageGen优先](rules/imagegen-first-v3.md)、[自然修复选路](rules/content-aware-text-restoration-v2.md) | 参考图须实际绑定并审核；静态供体、局部采用与连续运动分别判断 |
| 发布者水印和片尾同标 | [去除范围](rules/publisher-watermark-removal-v2.md) | 逐实例解析身份；产品品牌与用户明确保留例外单列 |
| 配音、角色和字幕时轴 | [最终混音核查](rules/method-spoken-caption-verification-v4.md)、[角色声线](rules/short-drama-character-voices-v2.md) | 孤立TTS、模型语义时间和预设名不能替代实际混音及编码边界 |
| 全部原片/语种提交与恢复 | [全项交付](rules/fireplay-complete-delivery-v3.md)、[固定提交与收尾](rules/fireplay-completion-recovery-v4.md) | 部分批次继续补交；真实平台读回后结案，不跟踪YouTube进度 |
| YouTube自动上传与历史补传 | [真实初始受理](rules/fireplay-youtube-enqueue-verification-v1.md) | R2入库不等于已入队；精确素材/视频资源任务ID或当前链接才是受理证据 |
| 设计师身份与KIE核查 | [设计师归属](rules/fireplay-designer-attribution-v2.md)、[API与本地日志](rules/kie-api-local-verification-v1.md) | 自行查询真实成员，持续授权沿原需求账本，不索要后台登录或DID |

语言scope默认完整匹配；审查过的基础语言scope才可扩大。`related_source_references`只是同源其他语言标签的发现线索，须重新审查。条件方法按实际特征命中；背景场景和候选存在本身不决定算法。

## 源限定案例导航

每行保持正文登记的源SHA、语种和版本范围；同源其他语种仍须独立定稿、配音、时轴和审核。这里只按主题分组，不复制规则或合并验收。

| 主题 | 案例入口 |
| --- | --- |
| ImageGen参考与Wan局部采用 | [APC024日语上部试片](cases/apc024-ja-imagegen-wan-upper-trial-v1.md)、[MOG005英语](cases/mog005-en-imagegen-wan-local-adoption-v1.md)、[SHE039西语](cases/she039-es-reference-wan-boundaries-v1.md) |
| 残字、供体与边界 | [MOG010日语](cases/mog010-ja-static-donor-and-cta-v1.md)、[MOG044韩语控件](cases/mog044-record-control-ko-v2.md)、[KEY008日语一帧切换](cases/key008-ja-caption-switch-v1.md) |
| 最终混音和角色分歧 | [KEY002阿语时轴](cases/key002-ar-mix-timing-v1.md)、[KEY005阿语源语漏音](cases/key005-ar-source-gap-audio-v1.md)、[MOG044葡语句尾串音](cases/mog044-pt-utterance-tail-v2.md)、[SHE044第二原片韩语声线](cases/she044-2-ko-voice-diagnostic-v1.md) |
| 同源复用与逐语种检查 | [MOG005西语原音轨/UI](cases/mog005-es-original-audio-stable-ui-v1.md)、[SHE043阿语共用底片](cases/she043-ar-shared-base-boundaries-v1.md) |
| 有界取舍与字幕合成 | MOG063[西语](cases/mog063-es-straw-and-phone-boundaries-v1.md)、[印地语](cases/mog063-hi-straw-and-phone-boundaries-v1.md)、[葡语](cases/mog063-pt-straw-and-phone-boundaries-v1.md)；[WOW042德语合成](cases/wow042-caption-compositing-v1.md) |
| 保全包提炼与特殊边界 | [KEY021印地语道具](cases/key021-hi-prop-plane-v1.md)、KEY010[第一原片英语](cases/key010-1-en-fade-boundary-v1.md)/[第二原片西语](cases/key010-2-es-source-scope-v1.md)、[MOG054葡语专名分歧](cases/mog054-pt-name-asr-v1.md)、[WOW045西语场景文案](cases/wow045-es-scene-copy-v1.md) |
| 上传暂缓与原操作恢复 | [MOG047](cases/mog047-upload-deferral-v1.md) |

完整清单以[cases/index.json](cases/index.json)为准。本轮新增来源与采纳关系见[融合记录](curation/consolidation-20261028.json)；已有七组来源与历史迁移仍由各自curation记录追溯，不按语言数量增加独立复验数。

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

`current_review` 是派生索引中的当前审查链入口，包含决定文件及哈希、是否结案和现行目标；旧 `review_status` 与 outcome 继续保留历史含义。使用 `python3 bin/project_health.py` 可生成本地知识导航，按源与相同假设浏览成员，完整 scope 和每语种状态保存在 JSON 中。自动占位经验不会进入制作建议，仍能从队列补写有来源的观察。见 [维护地图](../docs/project-map.md) 与 [七组实测整理](curation/seven-source-review-20261027.json)。

## 审查、实际使用与退出候选队列

`knowledge-queue` 才是当前待处理入口：它同时汇总原始候选、当前提纯版本和使用反馈。旧采纳表提供历史依据，新审查决定保存在 `curation/reviews/`（私有来源留在local），通过原文哈希和 `previous_review` 保留修订链。提纯建议与部分采纳不会自动变成正式规则。

`context`、`codex-packet`、`work-packet` 和 `plan` 提供独立的 `knowledge_advisories`，最多3条匹配观察。读原文及限制后可设计试验、避免已知错误；正式方法不足也不表示候选已经成立。每次实际使用用 `knowledge-use` 绑定当前计划、原文版本、视频与证据，明确采用效果或未采用。负面结果以 `review_alerts` 返回到同源同语种的原方法检索，同时进入修订队列。

已完全处理的候选可以从此目录移除：`candidate-archive` 先预览，再带指纹执行，原始字节保存在 `history/candidates/`。`candidate-archives.json` 保持旧来源路径可追溯；索引里的 `storage_path` 是实际文件位置，`queue_state=archived` 表示已退出默认队列。原始status/outcome保留历史含义，当前处理状态以审查链为准。只有部分采纳的内容仍保留待办，不批量删除。详细命令与表单见 [知识合同](../agent/contracts/knowledge.md)。

## 整理与维护

相同含义且scope一致的过程经验关联现行方法；单源新事实按精确语种建独立案例。未提取经验的保全包保留具体审查入口，不把占位句当结论，也不因等待跨源复验而阻止单源案例整理。[融合记录](curation/consolidation-20261028.json)保留本轮公开来源、原文哈希和审查关系；私有记录继续留在local。

反馈包中，`feedback.json`是事件，经过哈希manifest核验的声明成员是该事件的证据。队列与Hook只排除已声明且核验一致的证据成员；未列入清单的新反馈仍进入待审。清单缺文件、哈希改变或路径越界会报错，不能静默隐藏。原文件不因去重计数而删除。

操作步骤见[知识合同](../agent/contracts/knowledge.md)，职责和工具见[维护地图](../docs/project-map.md)。实际积压读取`knowledge-queue`、`hooks status`与`project_health.py`；目录数量和历史“已整理”说明不能替代当前状态。证据只按相同SHA256共享，现行正文、历史原文、manifest与原评审分别保留。
