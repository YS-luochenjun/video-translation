# KIE 音频请求及恢复

总入口见 [kie](kie.md)。

## 音频请求与结果

`audio-analyze` 使用 `/gemini-3-8-flash-openai/v1/chat/completions`，音频 URL 放入媒体结构的 `image_url` 字段；比较时分别标明原音和成片。`--transcribe-only` 是单轨转写，不代表音乐、音效或字幕同步已通过。当前 Flash 请求由提示词约定 JSON；先保存原始回执、响应身份、用量和计费，再解析结构，无法解析时记为 `response_invalid`，不丢弃证据或自动重发。最长请求等待180秒不代表失败后可以另发一笔。

2026-11-25 用户授权两条复核备用路线。当前 Flash 失败时，先核对原请求及原账本，有可恢复标识则优先恢复。需要另一笔独立模型证据时选择以下之一，原未知费用仍占位，沿原预算和笔数限制，重复同一指纹只返回原任务。已取得足够证据则停止。

- 完整双轨比较默认使用 `audio-analyze RUN --candidate --execute`，自动复用已登记主模型请求，并在调用故障或明确无法打开媒体的全空报告时切换一次 Hydrogen。显式 `--model` 用于单路线诊断。按 KIE 官方音频结构使用低推理档，单笔预留 5 credits，实际按 token 用量结算。公开费率为输入 120、输出 600 credits/百万 tokens。该接口文档标注 chat only，实际媒体请求和质量须验证；仍可能与 Flash 同时发生供应商故障。[接口](https://docs.kie.ai/market/gemini/gemini-4-hydrogen-openai) 和 [价格](https://kie.ai/gemini-4-hydrogen)。
- 独立语音识别用 `audio-transcribe RUN --candidate --execute`，原片去掉 `--candidate`。NVIDIA Nemotron 3.5 Transcribe 在 KIE 以真实 taskId 异步执行，按回执用 `poll RUN JOB` 取得逐词时间及说话人 JSON。确认原任务临时供应商故障、终态且实扣为零后，可用 `--retry-failed` 追加至多一次同素材转写。公开价格 0.005 credits/秒，单笔至少预留 1 credit。支持 40 种语言（含普通话），由模型自动识别，不传预期译稿。该证据用于核对疑似错词、遗漏、原语残留和句尾；音乐、音效、角色音色、地区口音、语义和实际同步仍按音频、字幕及首尾合同核验。不能以 ASR 一致代替完整音频审核。[接口](https://docs.kie.ai/market/nvidia/nemotron-3-5-transcribe) 和 [价格](https://kie.ai/nemotron-3-5-transcribe)。

首次实际验证（MOG-20261125-058 繁中）中，Flash 返回业务码 502，Hydrogen 返回 500，NVIDIA 原任务及一次有界重试均取得 taskId 后返回终态 500 且实扣为零。三条路线均未得到本次有效复核内容。主备完整复核均因供应商错误不可用时，执行[音频异常交付](../contracts/audio.md#独立配音与转写)，不等待 KIE 恢复、不强制本地复核、不重发未知费用请求。正常成功报告发现内容缺陷不属于调用故障。

同日独立短音频探针（中英混合、英语片段、中文片段）中，Hydrogen 三次均返回正确的测试句关键内容，实扣分别为 0.44、0.34、0.34 credits；但其对故意未翻译的双轨反例再次返回 500。Flash 单轨三次两次成功、一次 500，其中首个成功报告因旧共享路径被覆盖而不能复查；双轨反例成功并正确判定英语残留、翻译不完整，实扣 0.10 credits。Gemini 3.1 Pro 一次 500，NVIDIA 再次终态 500、实扣零。Hydrogen 可作单轨疑点补证候选，完整双轨复核稳定性未验证，NVIDIA 不作为常规生产推荐；不得因小样本成功替换当前完整质量门禁。新复核任务逐笔保存独立响应与报告，兼容的最新报告路径继续用于现有审核。

用户明确允许本次素材更换复核模型时，可用 `--model gemini-3.1-pro --model-authorization inputs/授权.json`。授权绑定真实用户原话、音频分析能力、源哈希、语种和原请求预算；不改变默认模型，旧请求未知费用继续占位。该接口按官方文档接收同一 `image_url` 音频结构，单笔保守预留20 credits，成功回执再结算。

配音使用定稿的 `speech_segments[].target_text`，`tts-packet` 绑定实际稿件和语言。Gemini TTS 的 `speaker_id` 使用 `Speaker 1` 格式，必须指定 `voice_name`。可选控制字段只能按实际接口合同填写，不把语言名当作口音枚举。声音生成后核对是否完整说出定稿，按实际混音对齐字幕；模型返回音频不等于时长、发音或同步通过。流程见 [音频](../contracts/audio.md) 与 [字幕](../contracts/captions.md)。

[Gemini 3.8 Flash TTS](https://docs.kie.ai/market/google/gemini-3-8-flash-tts) 将朗读要求放在 `dialogue_turns[].style`，`dialogue_turns[].text` 保存定稿。使用预设声线，填充词保持关闭。

