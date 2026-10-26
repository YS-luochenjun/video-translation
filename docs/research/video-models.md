# KIE 视频模型与翻译路线核对

查证日期：**2026-10-16（Asia/Shanghai）**。依据 KIE 当前官方文档、公开价格卡及 schema；本报告没有提交付费生成任务，也没有读取 `.env`。接口支持不代表文字替换质量已经通过测试。

## 当前接口与 legacy 分开

当前任务提交为 `POST /api/v1/jobs/createTask`，查询为 `GET /api/v1/jobs/recordInfo?taskId=...`。Veo 旧接口在 `/old-model/` 文档中，使用 `/api/v1/veo/generate`、`imageUrls`、`generationType`；不能把旧字段直接拼进新版 `input`。[当前 Veo](https://docs.kie.ai/veo3-api/generate-veo-3-video)、[legacy Veo](https://docs.kie.ai/old-model/veo3-api/generate-veo-3-video)、[统一查询](https://docs.kie.ai/market/common/get-task-detail)

## 四个模型的能力边界

| 模型 | 当前合同中确认的参数与限制 | 对本项目的意义 |
| --- | --- | --- |
| Veo 3.1 | 顶层 `model: "veo-3-1"`；档位 `input.model: "veo3_fast"`，另有 Lite/Quality。`REFERENCE_2_VIDEO` 输入 **1–3 张参考图、仅 8 秒**，支持 Fast/Lite；普通生成时长为 4/6/8 秒。 | 当前生成接口接收图片，不接收待编辑的源视频。适合关键帧重建或参考图生成，不能称为保留原视频所有动作的直接翻译。 |
| Kling 3.0 Omni Transformation | `model: "kling-3.0-omni/transformation"`；`video_urls` **恰好 1 段**；MP4/MOV、3–15.5 秒、≤200MB；宽高各 700–4553px、总像素≤8,294,400、比例0.4–2、24–60fps。 | 可直接提交源视频做语义编辑。仅视频时 `aspect_ratio: "auto"`；有视频时按说明设 `audio: false`，这表示不生成音频，不能据此承诺保留源音轨。 |
| Seedance 2.0 | `model: "bytedance/seedance-2"`；首帧、首尾帧、多模态参考为互斥场景；`first_frame_url`/`last_frame_url` 不得与任何 `reference_*` 混传。最多9图、3视频、3音频；参考视频合计≤15秒，输出4–15秒或`-1`自动。 | 可用源视频作参考重建，也能首尾帧生成；参考视频不等于逐帧保真编辑。这里核对的是 **2.0**，没有用2.5参数替代。 |
| Wan 2.7 Video Edit | `model: "wan/2-7-videoedit"`；`video_url` 单视频，MP4/MOV、2–10秒、宽高240–4096px、≤100MB；可加 `reference_image`，输出720p/1080p。 | 明确的视频编辑接口。`duration: 0`沿用完整输入时长；`audio_setting: "origin"`强制保留输入音频，`auto`由模型决定是否重生音频。 |

来源分别为 [Veo schema](https://docs.kie.ai/veo3-api/generate-veo-3-video.md)、[Kling schema](https://docs.kie.ai/market/kling/v3-omni-transformation.md)、[Seedance 2.0 schema](https://docs.kie.ai/market/bytedance/seedance-2.md)、[Wan 2.7 Video Edit schema](https://docs.kie.ai/market/wan/2-7-videoedit.md)。Veo/Kling 同时核对了本地已下载的 [Veo](C:/Users/Echo/Desktop/图片翻译/work/veo.md) 与 [Kling](C:/Users/Echo/Desktop/图片翻译/work/kling.md) 文件。

补充两个容易误读的字段：Veo `enable_translation` **只把 prompt 翻译成英文后生成**，不是翻译画中文字。Kling schema 的 `audio` 枚举虽然列出布尔值，字段说明明确要求有视频时为 `false`，应遵循场景约束。[Veo 当前文档](https://docs.kie.ai/veo3-api/generate-veo-3-video)、[Kling 当前文档](https://docs.kie.ai/market/kling/v3-omni-transformation)

## 路线选择

以下是根据接口合同做出的工程建议，效果仍需用真实素材验证。

| 路线 | 优先采用的条件 | 必须检查的边界 |
| --- | --- | --- |
| 本地精确合成 | 字幕、价格、CTA、固定贴字；要求译文逐字准确、时间段确定、保留原动作 | 使用时间轴和字体排版覆盖。复杂背景的原字擦除、运动跟踪、遮挡仍需处理；遮盖不等于无痕修复。FFmpeg 支持 `drawtext`、图层合成与时间条件。[官方滤镜文档](https://ffmpeg.org/ffmpeg-filters.html#drawtext-1) |
| 模型编辑 | 文字嵌入复杂背景，需要同时调整画面；优先试 Kling Transformation 或 Wan VideoEdit | 校验文字内容、位置、时序及非目标区域变化；保留可回退的原片。模型支持视频输入，不等于承诺逐字排版或仅修改指定像素。 |
| 关键帧重建 | 允许重新生成运动；没有合适直接编辑接口，或要重做视觉场景 | 先制作已翻译关键帧，再用 Veo/Seedance 等生成。首尾帧约束不能锁住中间每帧，必须检查人物、产品、镜头及文字稳定性。 |

建议 Demo 默认选择本地合成；复杂去字可单独试模型编辑；关键帧重建需明确标注会重新生成画面。模型调用前先确定文本实例、区域和出现时间，调用后逐项核对，不能仅以任务 `success` 判定翻译完成。

## 两个小样的 credits

价格来自当日公开模型价格卡，以下均不计充值赠送、重试、其他模型调用和额外升清。

| 小样假设 | 官方单价 | 估算 credits |
| --- | --- | --- |
| Veo Fast、720p、`REFERENCE_2_VIDEO`、8秒、1条 | Fast 的文生/图生/参考图生视频均为 **60 credits/条** | **60** |
| Kling Transformation、720p、按8秒计费、1条 | 该模式为 **20 credits/秒**，不是默认文生卡的14/秒 | **160** |
| 上述各1条 | 60 + 20 × 8 | **220 credits，约 $1.10** |

Veo Fast 的1080p为65、4K为180 credits/条；Transformation 的1080p为27、4K为67 credits/秒。来源：[Veo 官方价格卡](https://kie.ai/veo-3-1)、[Kling Transformation 官方价格卡](https://kie.ai/kling-o3?model=kling-3.0-omni/transformation)。后者专属 `pricingDesc` 已在 KIE 公共页面内容中直接核对，不能套用页面默认 `text-to-video` 的报价。

**220 是上述假设的预算，不是已经发生的扣费。** 若 Kling 片长不同，或计费有取整，结果会变化；本次没有查证小数秒取整规则。实跑后读取 `recordInfo` 的 `creditsConsumed` 并与账单核对。[官方任务详情](https://docs.kie.ai/market/common/get-task-detail)

## 查证限制

agent-reach 的 Jina 路径实试遇到 DNS 错误；随后通过 Web 与获准的只读公开网页请求查证。Seedance/Wan schema 已直接读取；价格没有使用第三方转述。浏览器交互表面不可用，因此没有在登录态 Playground 操作或消费额度。所有数字均为查证日的公开合同或报价，不保证未来不变。
