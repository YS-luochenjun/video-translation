# Fireplay按编号接入与固定回传

宿主Agent读取Fireplay、操作已授权聊天及外部提交；项目CLI只登记证据、媒体、账本与状态，不复制登录凭据或假装调用连接器。政策入口是[AGENTS](../../AGENTS.md)，来源及参数分别在config/fireplay-intake.json、config/fireplay-publication.json、config/fireplay-youtube-routing.json、config/kie-access.json。新需求自动发现另见[巡检](fireplay-monitor.md)。本文保留接口和恢复步骤，不重复历史聊天原话。

按当前阶段进入对应章节。各专题保留原章节正文与执行依据。

## 持续执行到平台受理

[阅读此章节](fireplay-execution.md#持续执行到平台受理)。

## 读取与下载

[阅读此章节](fireplay-source-intake.md#读取与下载)。

### 历史译片与原片复用

原需求被驳回后创建的返工单跳过本节。依据需求标题或正文中的驳回返工标记、原需求关联和问题附件确认范围，按实际异议修复并复审。本次只涉及局部问题时，可保留经核验的配音、译稿或其他未受影响的部分。整条历史成片和历史原片均不能直接作为返工交付。参见[回传与发布审核](fireplay-publication.md)。

先登记本次提供的视频及其 SHA256。新制作聊天在首个付费批次前执行 `fireplay-reuse CODE search --video N`，由 `config/fireplay-intake.json.historical_translation_reuse.enabled` 控制。

1. 宿主执行命令返回的精确素材 ID、YouTube ID 与关键词查询。先用 `material_usage_query` 查同一 YouTube ID 的全部素材记录，再用 `search --spec FILE` 登记 `{"material_usage":原始响应}` 生成素材 ID 查询。对命中的需求 UUID 读 `requirement_list(view=delivery)`。用 `search --spec FILE` 登记 `material_usage`（如已查询）、`searches` 和 `deliveries`。`searches` 的 `material`、`youtube`、`keyword` 各填 `arguments` 和真实 `response` 或 `error`。关键词只用于标题和描述，参考栏链接用精确链接反查。查询超时或截断时登记覆盖缺口，有界补查后继续缺项制作。遇到平台选材门禁，按返回链接等待该候选的实际选择。
2. `candidates` 是可能匹配本单来片的旧交付。语言 Tag 用于筛选，多原片逐条对照同一剪辑。`historical_deliveries` 表示本次给的视频是旧交付。若目标语就是旧原片语种，优先查 `original_candidates`，按 `material_lookup` 查精确上游 YouTube ID，再读真实 `material_detail`。旧原片可以直接作为候选，无需有同语种的旧交付 Tag。参考链接只提供线索，须实际核对同一剪辑、文字和口播。被拒绝的旧需求只保留溯源。
3. 用 `fireplay-reuse CODE capture --spec FILE --video N` 传入 `search_sha256`、候选 `candidate_id` 和 `material_detail`。程序核验使用权限、R2 文件、字节身份及完整解码，保存首尾证据。实际审查本次来片与候选的剪辑、可观看性、画面文案、口播、首尾残音和本单规格。
4. `fireplay-reuse CODE package --spec FILE --video N` 填 `capture`、`video_sha256`、`locale`、`reviewer`、`target_voice_needed`、`target_language_observed` 和 `decision:"eligible"`。在 `observations` 分别记录 `same_original_version`、`target_language`、`complete_translation`、`required_voice_and_audio`、`specifications_and_watchability`。在 `head_tail_audio` 为 `head`、`tail` 各填 `decision:"pass"`、`original`、`delivery`、`original_language_residue`、`target_speech_completeness`。若 Tag 缺失或冲突，用 `language_tag_resolution` 记录实际语言依据。新单明确要求清晰音频时，实际核验通过后记录 `clear_audio_decision:"pass"`。
5. 用 `package` 返回项准备 `fireplay-return`。部分符合时使用 `partial:true`。通过审查的候选走新需求的入库、共享、命名、标签及绑定流程。首个 `fireplay-start` 只为缺项建制作 run。全量复用时返回 `reuse_ready`，继续回传并读回平台绑定。既有批次沿原 run 和账本。

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

