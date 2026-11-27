# Fireplay按编号接入与固定回传

宿主Agent读取Fireplay、操作已授权聊天及外部提交；项目CLI只登记证据、媒体、账本与状态，不复制登录凭据或假装调用连接器。政策入口是[AGENTS](../../AGENTS.md)，来源及参数分别在config/fireplay-intake.json、config/fireplay-publication.json、config/fireplay-youtube-routing.json、config/kie-access.json。新需求自动发现另见[巡检](fireplay-monitor.md)。本文保留接口和恢复步骤，不重复历史聊天原话。

按当前阶段进入对应章节。各专题保留原章节正文与执行依据。

## 持续执行到平台受理

[阅读此章节](fireplay-execution.md#持续执行到平台受理)。

## 读取与下载

[阅读此章节](fireplay-source-intake.md#读取与下载)。

### 历史译片与原片复用

原需求被驳回后创建的返工单进入[局部返工与素材复用](quality-feedback.md#局部返工与素材复用)。以下整片复用流程适用于非驳回需求。

先登记本次提供的视频及其 SHA256。按原片派单的新聊天在首个制作批次和语种 run 创建前执行 `fireplay-reuse CODE search --profile quick --video N`。多个目标语种共用本次查找。既有批次、明确授权的单语试制及驳回返工沿各自入口。开关为 `config/fireplay-intake.json.historical_translation_reuse.enabled`。

1. `local_match` 时先用 `local_delivery_query` 读取旧需求的实时交付，按同一 profile 执行 `search --spec FILE` 登记 `{"local_deliveries":[原始响应]}`。本地索引按源哈希、原片或交付的精确 YouTube ID、交付哈希或素材 ID 定位已有真实绑定。按交付 YouTube ID 命中时，当前交付视图须返回同一素材及同一视频 ID。仍须核对平台当前绑定、选材和使用资格。已覆盖本单全部语种时进入回传。有缺项时用 `{"skip_local":true}` 再生成快速平台查询计划。
2. 有 YouTube ID 时用 `material_usage_query` 确认同一视频 ID 的素材，按原 profile 用 `search --spec FILE` 登记 `{"material_usage":原始响应}`。按返回计划执行素材 ID 与关键词查询，对命中的需求 UUID 读取 `delivery`，登记 `material_usage`、`searches` 和 `deliveries`。`searches` 各项包含 `arguments` 与真实 `response` 或 `error`。`no_quick_match` 或快速 `cached_no_match` 只覆盖快速查询，可直接制作缺项。明确知道有历史参考栏链接、快速查询发现同源线索但尚未找全、或用户需要完整核查时，用 `--profile full` 和 `{"skip_local":true}` 加查精确 YouTube 链接。用 `refresh:true` 可跳过短期查空缓存。超时、截断和平台待选材按实际状态记录，有限补查后推进其他缺项。平台选材由用户完成。
3. `candidates` 是可能匹配本单来片的旧交付。语言 Tag 用于筛选，多原片逐条对照同一剪辑。`historical_deliveries` 表示本次给的视频是旧交付。若目标语就是旧原片语种，优先查 `original_candidates`，按 `material_lookup` 查精确上游 YouTube ID，再读真实 `material_detail`。旧原片可以直接作为候选，无需有同语种的旧交付 Tag。参考链接只提供线索，须实际核对同一剪辑、文字和口播。被拒绝的旧需求只保留溯源。
4. 用 `fireplay-reuse CODE capture --spec FILE --video N` 传入 `search_sha256`、候选 `candidate_id` 和 `material_detail`。程序核验使用权限、R2 文件、字节身份及完整解码，保存首尾证据。实际审查本次来片与候选的剪辑、可观看性、画面文案、口播、首尾残音和本单规格。
5. `fireplay-reuse CODE package --spec FILE --video N` 填 `capture`、`video_sha256`、`locale`、`reviewer`、`target_voice_needed`、`target_language_observed` 和 `decision:"eligible"`。在 `observations` 分别记录 `same_original_version`、`target_language`、`complete_translation`、`required_voice_and_audio`、`specifications_and_watchability`。在 `head_tail_audio` 为 `head`、`tail` 各填 `decision:"pass"`、`original`、`delivery`、`original_language_residue`、`target_speech_completeness`。若 Tag 缺失或冲突，用 `language_tag_resolution` 记录实际语言依据。新单明确要求清晰音频时，实际核验通过后记录 `clear_audio_decision:"pass"`。
6. 用 `package` 返回项准备 `fireplay-return`。部分符合时使用 `partial:true`。通过审查的候选走新需求的入库、共享、命名、标签及绑定流程。
7. 运行 `fireplay-reuse CODE preflight --spec FILE --video N` 冻结本次复用决定。`search_sha256s` 列出本次实际使用的查找回执。剩余语种有语言 Tag 匹配或上游原片候选时，使用 `candidate_dispositions` 逐项写 `candidate_id`、`locale`、`decision`（`unsuitable` 或 `not_reviewed`）及实际 `reason`。遇到超时、结果残缺或候选审查到界，按实际情况填写 `fallback` 的 `kind`（`platform_unavailable`、`lookup_incomplete` 或 `candidate_review_limit`）和 `reason`，随后立即继续可生产语种。平台查询实际无法运行时可以只提交 `platform_unavailable` 及其原因。全量准备复用时以已核验回传包为据。决定绑定需求、内容版本、原片及目标语言。
8. 首个 `fireplay-start` 只为缺项建制作 run。全量复用时返回 `reuse_ready`，继续回传并读回平台绑定。记录过的决定供同一原片启动使用。

本地 SQLite 索引由 `state/fireplay` 的已核验交付回执重建，保存需求、原片／交付哈希、原片及已核验交付 YouTube ID、语种和素材 ID 等定位字段。交付 ID 来自受回执哈希保护的绑定读回，也可由已有的整单交付核验读回补齐。索引在同一工作区增量刷新，媒体过期后仍可通过平台重新核验素材。`local_lookup_ms` 记录本地检索耗时。完整、同一操作者和范围内的查空结果短期复用，快速和完整查询分别为 5 分钟和 15 分钟。缓存到期后重新查询。平台超时、权限缺口和截断保留各自状态。快速模式缩减查询种类，单次平台调用的耗时仍由平台决定。仅保存在参考栏的历史链接可能需要完整查询才能找到。

### 原片优先级

[阅读此章节](fireplay-source-intake.md#原片优先级)。

### YouTube 缺片补取

[阅读此章节](fireplay-source-intake.md#youtube-缺片补取)。

## 聊天、授权与制作

[阅读此章节](fireplay-production-start.md#聊天授权与制作)。

## 需求状态

[阅读此章节](fireplay-production-start.md#需求状态)。

## 就绪、部分提交与unknown

[阅读此章节](fireplay-publication.md#就绪部分提交与unknown)。

## 上传命名与标签

[阅读此章节](fireplay-publication-metadata.md#上传命名与标签)。

## 平台路由与结案

[阅读此章节](fireplay-publication-metadata.md#平台路由与结案)。

