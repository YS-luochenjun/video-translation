# KIE 视频请求

总入口见 [kie](kie.md)。

## 视频请求与结果

2026-11-09用户明确要求将当前和在制视频处理从Wan2.7切换为Wan3.0。新调用使用`wan/3-0-video`，不将旧packet字符串替换后直接提交；旧taskId、响应、预算及unknown原样保留、只查原结果。五个在制负责聊天沿各自原池试用，不自动增额或重做已提交成片。

Wan3.0采用`reference_video_urls:["ASSET:video"]`，可选`reference_image_urls:["ASSET:image"]`，720P大写、固定整数duration、`audio:false`。本项目先限定单源1–15秒参考与同长整数2–15秒输出（总时长不超过30秒），非整数段须显式重新安排，不能拉伸凑时长；源/结果运动与时轴仍实际审查。保持原音及目标配音在独立音频链路回混，不能沿用2.7的`video_url`、`audio_setting`、`prompt_extend`或`negative_prompt`字段。参考图片不能有透明像素。费用按输入视频加输出视频时长：480P/720P/1080P分别8/16/32 credits每秒，预留向上取整；不使用自动duration=-1避免不确定预算。真实费率/响应仍需对账。当前参数校验见`src/video_localizer/wan3.py`；官方合同https://docs.kie.ai/market/wan/3-0-video ，价格https://kie.ai/wan3.0-video 。

以下2.7参数仅供旧请求恢复，不能用于新制作：

当前 Wan 输入合同为源视频2–10秒、宽高240–4096px、最大100MB，可附绑定文件哈希的 `reference_image`。`duration: 0` 沿用输入长度，`audio_setting: origin` 保留输入声音，`prompt_extend: false` 保留精确提示。保留原声也会保留原语言对白；需要翻译对白时另走配音、分轨和混音流程，不能把声音保留开关当作配音成功。

参考图可以来自已审ImageGen结果，须实际上传并绑定哈希，提示词明确其作用；当前适配器是单图，不将原生供应商多图合同直接套入KIE载荷。参考只表达目标，连续运动、遮挡和字幕仍须实际审核，见[ImageGen优先政策](../../knowledge/rules/imagegen-first-v4.md)。

`model-task`将附件分别校验：video核对实际片段时长，Wan的image核对静态PNG/JPEG/WebP、正尺寸、完整解码和原文件哈希，不要求图片具有视频时长。`ASSET:image`必须绑定image附件；未绑定的额外附件不上传。`duration:0`是Wan沿用源视频长度的参数，与静态参考图是否有时长无关。已提交任务沿原指纹恢复，不因校验修复重发；本地回归、真实参考图受理与视频质量分别举证。

超出输入合同的素材必须明确拆分与安排时间轴，不能静默变速。`packet RUN SEGMENT` 只生成本地可审查请求；`submit RUN SEGMENT --execute` 才上传并提交。估价与可用合同可能变化，必要时核对供应商当前说明；旧实验价格不是当前账单保证。模型结果仍需逐实例检查原字、背景、人物动作、产品、声音和字幕，再进行质量审查与交付。

