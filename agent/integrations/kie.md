# KIE 适配器

已授权音频重试自身的上传失败，可以保留同一 `--retry-authorization` 并加 `--retry-upload` 恢复；只允许本地证据确认尚未派发的任务，保留原job、授权、预留及上传历史。实际已派发或unknown请求仍先核查，详见[接续与上传恢复](../../knowledge/rules/resumable-intake-and-audio-upload-v1.md)。

新任务使用 [模型分工](../contracts/model-routing.md) 与 `config/model-routing.json` 的默认模型及已授权备选。文字识别、翻译和图片编辑由 Codex 执行。Whisper small 与 UVR 在项目本地运行。

| 能力 | 当前模型 | 进入条件与命令 |
| --- | --- | --- |
| 真实音频理解与比较 | `config/model-routing.json` 的 `audio_analysis` 与 `audio_analysis_recovery` | `audio-analyze RUN --execute`，成片比较加 `--candidate`；独立实音转写用 `audio-transcribe` |
| 目标语言配音 | 以 `config/model-routing.json` 的 `tts` 为准 | 口播定稿后用 `tts-packet` 生成请求，再用 `model-task --execute` 提交 |
| 原视频编辑 | `wan/3-0-video` | Codex 图片处理与本地合成无法满足连续运动要求时，使用 `model_edit` 路线，先 `packet` 再 `submit --execute` |

主用模型失败后，按 `config/model-routing.json` 中 `tts_recovery.fallbacks` 的顺序选择兼容目标语种的备选。`poll` 确认配置中的临时错误、终态失败且实扣为零，或同一 run 收到配置列明的明确建任务拒绝且未返回 taskId 时，运行 `tts-fallback RUN CURRENT_GEMINI_PACKET FAILED_JOB --speech-id LINE_ID --voice LINE_ID=VOICE_ID`。明确拒绝须核对原请求包与账本派发指纹，旧费用未知预留继续占用原账本，直接切换下一不同模型。每句使用经官方接口核对的声线 ID。`--failed-run` 可引用同一原片、同一请求账本的已结算故障证据。已有合格录音直接复用，已受理任务查原 taskId。费用未结算时保留预留，原请求包哈希能证明句子不重叠时可继续其他句。准备回执列出预计费用，用 `model-task RUN PACKET --execute` 沿原账本提交。

第一备用是 [Dialogue V3](https://docs.kie.ai/market/elevenlabs/text-to-dialogue-v3)，支持一次请求指定多角色。第二备用是 [Multilingual v2](https://docs.kie.ai/market/elevenlabs/text-to-speech-multilingual-v2)，按角色分别使用固定声线。费率、观察到的单笔预留底线与支持语种维护在路由配置。可用 `--combine` 把连续缺失句合在一笔并在实际音轨上重新对齐。v2 的合并限制为同一声线，越南语和泰语由支持这两种语言的 V3 处理。繁中普通话 API 传 `zh`，保留原定稿和语种，并实际听审地区口音。先用代表句验证声音和实扣再扩批。两条备用共用 KIE 和 ElevenLabs，故障可能相关。

备用录音也逐句检查发音、完整性、角色声线及新旧音色衔接，混音后检查字幕时间和首尾。旧路线保留原任务查询、账本和已经生成的可复用录音。

KIE 的只读余额和 `recordInfo` 查询遇到临时 408、425、429、500、502、503、504 或 524，以及连接层超时，会做最多三次读取尝试，失败后退避。创建任务、上传附件和音频生成请求不自动重发，建任务响应不明确时保留 `ambiguous` 并先核对已保存回执，有原 taskId 时查询原任务。

提交、音频分析及状态检查使用[本机存储准入](../contracts/storage.md#正常保留与自动清理)。维护等待超时时，该次命令尚未请求 KIE，维护完成后恢复同一操作。已受理任务继续查询原 taskId。

空间拼带修复若有`inputs/source-derivation.json.mapping`和`packed_video`，视频任务包必须用`source_derivation`路径/哈希冻结该文件；每行绑定实际`instance_ids`。执行器在上传/扣费前核对父源哈希、原生区间和`parent_crop`是否完整覆盖各实例`bbox`及已观察的`source_effect_bbox`（描边、阴影、缩放残影）。禁止仅用title/body类别或统一窄裁带代替实例范围；范围不足须重建输入，不能靠译文覆盖裁带外旧字。此校验只检查声明几何，未登记效果仍须实际看源片补齐；不代表模型去字成功。旧任务的查询、结果和费用保留。

拼带`mapping_scope`默认`complete_instances`：按原生帧的半开区间汇总各实例覆盖，包含未另行绑定修复实例的残影时段，不能把2.367秒截为`[0,71)`而漏掉30fps第71帧。只做局部时段试验须明确`partial_probe`，不因此获得完整实例修复或底片认可。

按当前阶段进入对应章节。各专题保留原章节正文与执行依据。

## 授权、预算与凭据

[阅读此章节](kie-authorization.md#授权预算与凭据)。

## 音频请求与结果

[阅读此章节](kie-audio.md#音频请求与结果)。

## 视频请求与结果

[阅读此章节](kie-video.md#视频请求与结果)。

## 失败、恢复与验证边界

[阅读此章节](kie-recovery.md#失败恢复与验证边界)。

