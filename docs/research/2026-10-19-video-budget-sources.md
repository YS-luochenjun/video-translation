# 100 KIE credits 视频预算：官方视频价卡与能力边界

核验日期：2026-10-19（Asia/Shanghai）。本次仅访问公开网页、文档和价格页使用的只读价目表接口；没有读取 `.env`，没有提交、重试模型任务，也没有重新处理视频。以下均为 KIE credits，不是其他平台同名积分；不把充值赠送积分计入保证预算。

## 结论

**完整广告可以设计成 100 credits 内的混合流程，但尚不能保证任意 23～30 秒广告在此预算下达到本轮效果。**关键是仅将确有必要的短片段交给视频模型，其余保留原视频并本地处理。完整重做画面通常会超预算，且参考生成不能等同于精确编辑。

本轮最终预览仍用到已付费的 Seedance 底片：局部修补脚本读取其结果并在字形内修补。不能从旧账单直接删去 450 credits，就声称同效果已能低价复现。将困难片段限制在 2 秒、或换用原片直接修补，均属于后续待验证方案；本次没有测试。

## 已核对的模式价格

| 精确模式 | 720p 价卡 | 能力边界 |
|---|---:|---|
| Wan 2.6 Flash video-to-video，`audio:false` | 5 秒 20；10 秒 40 | 官方将其解释为参考视频生成；不是带 mask 的逐像素修补接口 |
| 同上，`audio:true` | 5 秒 40；10 秒 80 | 音频生成费翻倍，不等于保留原配乐、仅翻译人声 |
| Veo 3.1 Lite，reference-to-video | 每次 30 | API 的参考输入是 `image_urls`；官方列出的素材参考指图像，不能当成上传原视频编辑 |
| Wan 2.7 **videoedit** | 每输出秒 16 | 真正接受 `video_url` 的编辑模式；2 秒预算 32，5 秒 80 |
| HappyHorse-1.0 **video-edit** | 每计费秒 28 | 官方说明编辑按输入+输出时长计费；按5秒输入+5秒输出算280，不把仅输出的140当完整请求费用 |
| Kling 3.0 Omni **transformation** | 每秒 20 | 5 秒即 100，尚未计其他环节 |

来源：[KIE 完整价格页](https://kie.ai/pricing)、[Wan 2.6 Flash 说明](https://kie.ai/wan-2-6-flash)、[Veo 3.1 价卡](https://kie.ai/veo-3-1)、[HappyHorse编辑计费说明](https://kie.ai/happyhorse-1-0)。Wan Flash 无音频 1080p 为 5 秒 30／10 秒 60，带音频为 60／120；Veo Lite 1080p 为 35／次、4K 为 150／次，不能混用这些档位估价。

为排除产品页默认模式误价，本次通过价格页公开前端使用的 `/client/v1/model-pricing/page` 只读查询，取得全部 **347 条 video 价卡**（每页 100，4 页，无鉴权）。已逐行核对上述 `videoedit`、`video-edit` 和 `transformation` 项，未将默认 T2V 价格套到编辑模式。原始临时抓取文件在系统临时目录，未写入运行证据。该接口虽以 POST 承载查询，但不创建模型任务。

## 整段处理要花多少

下表为单轮画面处理的算术估算，不含音频、ASR、TTS、评审、失败重试、片段重叠；23 秒代表当前约 22.99 秒素材向上覆盖到 23 秒。

| 路线 | 5 秒广告 | 23 秒广告 | 30 秒广告 | 60 秒广告 |
|---|---:|---:|---:|---:|
| Wan Flash 无音频 720p，按 5／10 秒段覆盖 | 20 | 100（25 秒覆盖） | 120 | 240 |
| Veo Lite 720p，假设每次取 8 秒 | 30 | 90（24 秒覆盖） | 120（32 秒覆盖） | 240（64 秒覆盖） |
| Wan 2.7 videoedit 720p，按总输出秒数 | 80 | 368 | 480 | 960 |

Veo 这一行只是生成费用对比，**没有证明其能准确保留原广告动作、文字位置和配乐**。三条路线都不能据此承诺“整条广告完整成本小于 100”。按镜头切分产生的补帧、重叠和重试还会增加费用。

## 参数合同和避免误价

- **Wan Flash V2V**：`video_urls`、`duration:"5"|"10"`、`resolution:"720p"|"1080p"`、`audio`、`multi_shots`。产品页宣传最多 15 秒，但 V2V 表单只有 5／10 秒；15 秒是 I2V 档，不应套用。官方将 V2V 描述为 R2V 参考生成，无法据此保证原视频逐帧编辑。[官方文档](https://docs.kie.ai/market/wan/2-6-flash-video-to-video)
- **Veo 3.1**：官方 API 列出文本生成、首尾帧图像生成、素材图像参考生成；`REFERENCE_2_VIDEO` 的示例使用 `image_urls`。产品页时长选项 4／6／8 秒，具体模式可用组合须以实际合同为准。本次没有验证调用，也不把“参考视频”中文标签当作源视频编辑能力。[生成 API](https://docs.kie.ai/veo3-api/generate-veo-3-video)
- **Wan 2.7 videoedit**：源 `video_url`，`duration:0` 表示原长度；显式截取允许整数 2～10 秒。`audio_setting:"origin"` 强制保留输入音频，`auto` 让模型决定是否重生。保留模式会连原英文人声一起保留，中文对白仍需要独立音频链路。2 秒 32 credits 是费用推算及此前单词短片实际扣费的一致结果，不代表 2 秒内一定能完成复杂修补。[产品页编辑表单](https://kie.ai/wan-2-7-video)、[编辑 API](https://docs.kie.ai/market/wan/2-7-videoedit)

## 100 credits 内更合理的组合

保留原画面与原配乐／音效资产；中文文字精确排版和时间跟踪在本地完成，只对少量难以清理的动态文字使用模型。示例：沿用 12 轨分离预留 50、中文 TTS 预留 5、仅 2 秒 Wan 2.7 编辑 32、评审与其他调用预留 10，合计 **97 credits**。这是预算方案，不是验收结果；若困难区分散于多个片段，或需要再次编辑，预算会不足。音频分离替代模式见附录，不能为省费默认牺牲音效保留。

同一源广告再做其他语言，可以复用经确认的分轨、文字轨迹及无字底片，只增加翻译和配音的边际成本；必须分别记录首次资产制作成本与后续语言成本。复用不能降低首次真实账单，也不能假定第一次制作已经达标。

在此次检索的公开 video 价卡中，没有找到比上述短片路线更明确、已标价的专用 mask 视频去字／修补模型。2026-10-19继续核验发现：Runway 的介绍页虽然仍宣传 Aleph，但当前官方API文档已明确标记 Deprecated / Discontinued，KIE不再提供该模型；应移出现售候选。页面 **12 credits** 对应 Gen-4 的生成／延长，也不能套到 Aleph 去字。[Runway介绍](https://kie.ai/market/runway)、[Aleph停用说明](https://docs.kie.ai/runway-api/generate-aleph-video)

以上价格是本次公开资料快照，效果、可用性及单条成功率未通过新测试确认。普通广告、复杂动画广告和 60 秒长片不应共用一个“必达 100”承诺。

## 附录：当前音频价卡复核

同一公开价目表查询接口的 `interfaceType:"music"` 本次返回全部 31 条价卡，明确列出以下三项，故高级分离 20 不是仅靠旧索引推断。

| 当前价卡名称 | credits／次 | 预算注意 |
|---|---:|---|
| Suno, Vocal Separate | 10 | 默认两轨分离；不能据其价格认定已有独立 FX 轨或音效无损 |
| Suno, Multi-Stem Separation, without stemName | 50 | 多轨分离；本轮 12 轨路线按此档计价 |
| Suno, Advanced Split | 20 | 指定单轨路线；是否足以单独拿掉对白且保留游戏音效，尚未测试 |

来源：[KIE Suno 模式页](https://kie.ai/suno-api?model=ai-music-api%2Fseparate-vocals)、[分离合同](https://docs.kie.ai/suno-api/separate-vocals)、[完整价卡](https://kie.ai/pricing)。Gemini 2.5 Pro TTS 当前输入价为 140 credits／百万 tokens，音频输出为 2800 credits／百万 tokens，具体按用量计费；上文 5 credits 是建议预留，非固定单条报价。[TTS 模式页](https://kie.ai/gemini-2.5-pro-preview-tts)
