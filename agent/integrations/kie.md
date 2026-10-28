# KIE 适配器

新任务只使用 [模型分工](../contracts/model-routing.md) 与 `config/model-routing.json` 中的三个远端模型。文字识别、翻译和图片编辑由 Codex 执行；Whisper small 与 UVR 在项目本地运行，不通过 KIE 下载模型或分轨。

| 能力 | 当前模型 | 进入条件与命令 |
| --- | --- | --- |
| 真实音频理解与比较 | `gemini-3-8-flash-openai` | 转写存在疑点、无法直接听音，或需比较原音与成片时使用 `audio-analyze RUN --execute`；成片比较加 `--candidate` |
| 目标语言配音 | `google/gemini-2-5-pro-tts` | 口播定稿后用 `tts-packet` 生成请求，再用 `model-task --execute` 提交 |
| 原视频编辑 | `wan/2-7-videoedit` | Codex 图片处理与本地合成无法满足连续运动要求时，使用 `model_edit` 路线，先 `packet` 再 `submit --execute` |

不自动切换或升级到其他模型。先根据真实错误或缺陷修正输入、定稿、素材或当前模型参数，在现有次数和预算内返工；仍不能满足要求时保留未完成项。历史模型仅可查询原任务、取回原结果或按原请求及附件哈希复用，不能借历史参数重新发起任务。

## 授权、预算与凭据

执行前运行 `kie-authorization`。工作区返回 `automatic_use=true` 时，在既有范围、预算和模型限制内直接执行必要调用，不重复询问。主控用 `budget-open` 登记真实用户请求；所有语言、短片、run、批次和返工共用请求账本。新请求按 targets 中去重后的每个目标语言60 credits建共享总池，首次/新复用同价；旧账限额及未知占位不自动变更；新建run或拆分任务不能扩大额度。新请求任务名额按原时长/角色数有限规划，两轮返工不变，见 [批次与预算](../workflows/batch-production.md)。

Fireplay需求沿用[接入流程](../workflows/fireplay-intake.md)和config/fireplay-intake.json.kie中的持久用户同意。用户明确交办后，fireplay-start绑定本需求独立聊天、真实请求、语种、内容版本和账本，追加独立授权记录；不再重复询问KIE或必要媒体上传。P0优先不阻塞P1制作。仍按当前模型合同、原需求额度、未知计费与宿主审批执行。

三个付费入口共用预留与实际计费记录，直接绕过执行器的 KieClient 写入被阻断。逐run预算调整不能提高请求总上限。估算不构成供应商的硬账单上限；状态或计费未知时继续占位，结算超估算后停止新增调用。额度或授权范围确需扩大时再说明具体缺口并取得用户授权。

凭据仅由执行器读取。当前适配器提交使用 `/api/v1/jobs/createTask`，查询使用 `/api/v1/jobs/recordInfo`；上传 host 为 `kieai.redpandaai.co`。鉴权只发送给适配器允许的供应商 host，下载结果不携带 API key。新部署不继承当前拥有者的本机授权。

## 音频请求与结果

`audio-analyze` 使用 `/gemini-3-8-flash-openai/v1/chat/completions`，音频 URL 放入媒体结构的 `image_url` 字段；比较时分别标明原音和成片。`--transcribe-only` 是单轨转写，不代表音乐、音效或字幕同步已通过。当前 Flash 请求由提示词约定 JSON；先保存原始回执、响应身份、用量和计费，再解析结构，无法解析时记为 `response_invalid`，不丢弃证据或自动重发。最长请求等待180秒不代表失败后可以另发一笔。

用户明确允许本次素材更换复核模型时，可用 `--model gemini-3.1-pro --model-authorization inputs/授权.json`。授权绑定真实用户原话、音频分析能力、源哈希、语种和原请求预算；不改变默认模型，旧请求未知费用继续占位。该接口按官方文档接收同一 `image_url` 音频结构，单笔保守预留20 credits，成功回执再结算。

配音使用定稿的 `speech_segments[].target_text`，`tts-packet` 绑定实际稿件和语言。Gemini TTS 的 `speaker_id` 使用 `Speaker 1` 格式，必须指定 `voice_name`。可选控制字段只能按实际接口合同填写，不把语言名当作口音枚举。声音生成后核对是否完整说出定稿，按实际混音对齐字幕；模型返回音频不等于时长、发音或同步通过。流程见 [音频](../contracts/audio.md) 与 [字幕](../contracts/captions.md)。

## 视频请求与结果

当前 Wan 输入合同为源视频2–10秒、宽高240–4096px、最大100MB，可附绑定文件哈希的 `reference_image`。`duration: 0` 沿用输入长度，`audio_setting: origin` 保留输入声音，`prompt_extend: false` 保留精确提示。保留原声也会保留原语言对白；需要翻译对白时另走配音、分轨和混音流程，不能把声音保留开关当作配音成功。

参考图可以来自已审ImageGen结果，须实际上传并绑定哈希，提示词明确其作用；当前适配器是单图，不将原生供应商多图合同直接套入KIE载荷。参考只表达目标，连续运动、遮挡和字幕仍须实际审核，见[ImageGen优先政策](../../knowledge/rules/imagegen-first-v1.md)。

`model-task`将附件分别校验：video核对实际片段时长，Wan的image核对静态PNG/JPEG/WebP、正尺寸、完整解码和原文件哈希，不要求图片具有视频时长。`ASSET:image`必须绑定image附件；未绑定的额外附件不上传。`duration:0`是Wan沿用源视频长度的参数，与静态参考图是否有时长无关。已提交任务沿原指纹恢复，不因校验修复重发；本地回归、真实参考图受理与视频质量分别举证。

超出输入合同的素材必须明确拆分与安排时间轴，不能静默变速。`packet RUN SEGMENT` 只生成本地可审查请求；`submit RUN SEGMENT --execute` 才上传并提交。估价与可用合同可能变化，必要时核对供应商当前说明；旧实验价格不是当前账单保证。模型结果仍需逐实例检查原字、背景、人物动作、产品、声音和字幕，再进行质量审查与交付。

## 失败、恢复与验证边界

任务指纹绑定计划、附件内容和参数。同指纹重复提交返回原任务；断线或建任务结果不明记为 `ambiguous`，禁止盲目重复 POST。先核对供应商日志的时间、模型、参数和 taskId，再恢复对应本地任务并记录依据。处理遗留锁前确认没有活跃执行。`reused_model_job` 只复用完整请求和素材哈希均相同的成功结果。

HTTP 200 仍可能包装业务错误。供应商业务码、`failCode` 与 `failMsg` 原样脱敏留档；连接/鉴权、上传、建任务、模型执行和内容质量分别报告。服务端5xx业务错误可能已计费，保留未知状态。只有供应商已确认终态失败、存在taskId且 `creditsConsumed=0`，才允许显式 `--retry-failed --execute` 做有账本的重试，仍受笔数与预算约束。

音频上传阶段的连接失败可显式 `audio-analyze ... --retry-upload --execute`，最多两轮。执行器保存旧尝试快照，并由总账确认尚无付费模型 dispatch 后复用原预留；不重复预留，也不允许借此重发结果不明的模型请求。

轮询每次最多45秒。成功后下载并检查实际媒体；计费缺失继续占位，不能把账户余额变化单独当作某笔任务的费用。`doctor` 仅检查本机状态，`doctor --online` 额外证明鉴权和余额读取；两者都不证明这次视频模型生成或内容验收成功。真实结果以任务账本、媒体哈希和审核证据为准。历史实验另见 [历史说明](../../docs/history.md)，不得从旧报告恢复已停用模型的制作入口。

用户只有API调用权限而不能登录后台时，不要求其登录或提供后台截图。先检查实际taskId、响应和本地日志；同步音频请求没有返回可恢复标识、且当前API不支持请求日志查询时，如实保留未知费用。只有用户在知晓旧请求状态后明确要求重试，才可用 `audio-analyze RUN --candidate --retry-authorization inputs/实际授权.json --execute` 另建一次尝试。授权绑定原journal哈希、原请求指纹、源/成片/音轨、语种、模型和原预算，`maximum_additional_attempts=1`；新尝试沿原笔数和额度预留，原未知请求不覆盖、不清零。同一原请求重复执行返回同一次重试；有可恢复taskId/response时继续恢复，不能用此入口重复扣费。此例外不是后台无法访问时的自动重试许可。 第二轮须绑定第一轮journal及其哈希，并有新的明确用户指令（retry_attempt=2、previous_retry、previous_retry_sha256）；每条授权仍只允许一次新增尝试，总计最多两轮，不因换授权文件突破限制。

本项目访问约束的机器来源是 `config/kie-access.json`，`kie-authorization.task_verification` 和新聊天prompt均带出该约束。所有后续对话只用API及本地日志核查，不再要求后台登录；不得因用户无后台权限而停止其他不依赖该未知请求的工作。正式知识见 [API与本地核查](../../knowledge/rules/kie-api-local-verification-v1.md)。
