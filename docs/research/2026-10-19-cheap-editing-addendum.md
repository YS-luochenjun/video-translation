# KIE 低价视频修改：遗漏型号补充核验

日期：2026-10-19，Asia/Shanghai。本次仅查公开资料，没有提交模型任务、重新处理视频、安装依赖、读取 `.env` 或改变模型策略。价格为 KIE credits；只估画面调用，不含音频与返工。基于本日已取到的完整 347 条公开 video 价卡，进一步核对旧型号和专用编辑合同。

## 结论与优先级

| 优先级／适用目的 | 模型与真实模式 | 720p 的 5 秒费用 | 最低片长／关键边界 |
|---|---|---:|---|
| 1：要保留原片动作、只改内容，优先研究短片编辑 | `wan/2-7-videoedit` | 80 | 显式输出时长最短 2 秒，2 秒 32；能传 `video_url`，局部翻译成功率仍未验证 |
| 2：更在意低价，能接受参考改版 | `wan/2-6-flash-video-to-video`，无音频 | 20 | 5／10 秒输出档；接原视频参考，但官方定位是 R2V 生成，不能当作精确保真编辑 |
| 信息候选，当前禁止新调用 | `bytedance/seedance-2-mini`，视频参考 | 50（5 秒输入＋5 秒输出） | 输出 4～15 秒；单参考视频 2～15 秒，全部参考视频合计≤15 秒；输入和输出都计费 |
| 后备，费用没有优势 | `kling-3.0-omni/transformation` | 约 100 | 源视频最短 3 秒、最长 15.5 秒；输入额外计费规则未明确，不能承诺 100 为账单上限 |
| 排除 | Runway Aleph | 不报价 | 官方已明确停用 |
| 暂不列入可用候选 | Kling O1 | 未核实 | 未找到当前有效价格与独立调用合同；产品入口 404 |

前两项价卡与能力边界见[上轮源资料报告](2026-10-19-video-budget-sources.md)。它们均未在本次重新测试；“有视频输入”不代表“中文文字原位替换已成功”。

## Kling O3：必须选 Transformation 的价，不能套默认页

KIE 官方 O3 页的默认文生视频档显示 720p 无音频 14 credits／秒；**Transformation 专属档是 20／秒**，1080p 为 27／秒、4K 为 67／秒。公开价卡的完整名称为 `kling 3.0 omni, transformation, 720p`。因此不能报成 5 秒 70 credits 的编辑。

官方 OpenAPI 明确：`model:"kling-3.0-omni/transformation"`，`video_urls` 必须恰好一个 MP4／MOV，源视频 3～15.5 秒，24～60 fps；仅视频输入时只能用 `aspect_ratio:"auto"`，提供视频时不生成音频，应设置 `audio:false`。纯视频输入合同没有输出 `duration` 参数；有参考图像的分支另有 `duration` 字段。

按 5 秒×20 估算画面 100 credits，已不适合“完整音画本地化每条 100 内”。公开页面没有明确说明是否另加输入视频秒数，因此不套用 Seedance 的输入＋输出公式，也不保证此估算就是最终全额。

来源：[O3 产品及模式页](https://kie.ai/kling-o3?model=kling-3.0-omni%2Ftransformation)、[编辑 API](https://docs.kie.ai/market/kling/v3-omni-transformation)、[包含完整参数的官方 OpenAPI Markdown](https://docs.kie.ai/market/kling/v3-omni-transformation.md)、[KIE 完整价卡](https://kie.ai/pricing)。

## Kling O1：有历史文案，不等于有低价现售接口

KIE 的 O3 页面会对比 Kling VIDEO O1，其他 Kling 产品介绍也仍会提到 O1。但本次当前官方接口索引未列出 O1 独立编辑接口，完整价格表也无 O1 项，`https://kie.ai/kling-o1` 返回 404；旧模型文档入口亦未提供可核实的独立低价 O1 合同。

证据仅支持“当前没有核实到可用型号和价格”，不足以断言供应商所有渠道已停用 O1，更不能引用其他平台价格作为 KIE 报价。

来源：[KIE O3 对比介绍](https://kie.ai/kling-o3)、[当前文档索引](https://docs.kie.ai/llms.txt)、[旧模型入口](https://docs.kie.ai/old-model)。

## Seedance 2.0 Mini：更便宜，但双边计费、仍属参考生成

当前公开价卡与产品页一致：720p 有参考视频为 **5 credits／秒×（参考视频总时长＋输出时长）**；无参考视频为 8.2／秒×输出时长。480p 两档分别是 2.4 和 3.8／秒。例：5 秒原片→5 秒输出，720p 为 **50**，480p 为 **24**；不是只按 5 秒输出报 25。若使用 2 秒参考＋4 秒输出，720p 为 30，但无法据此保证完整还原被截掉的内容。

官方合同支持 `reference_video_urls`，最多三个参考视频，总长≤15 秒；单视频 2～15 秒；输出显式时长 4～15 秒，或 `-1` 自动决定。参考模式与首帧／首尾帧模式互斥。它提供动作、主体、风格参考生成，不是专用 mask 去字合同；未验证其中文翻译和精确保真表现。

Mini 属于 Seedance 2.0 家族，项目禁止 Seedance≥2 新调用的策略继续有效，本次仅把它作为价格信息研究。中文旧页面提到截至 10 月 7 日的促销文字，本报告没有用该促销承诺价格，而以本日完整价卡和当前产品模式价为依据。

来源：[Mini 产品页](https://kie.ai/seedance-2-0-MINI)、[官方 API](https://docs.kie.ai/market/bytedance/seedance-2-mini)、[完整 OpenAPI 参数](https://docs.kie.ai/market/bytedance/seedance-2-mini.md)、[KIE 完整价卡](https://kie.ai/pricing)。

## Runway Aleph：应从当前可用候选排除

本次进一步打开实际 API 文档，看到 `Deprecated` 和明确声明：**Runway Aleph 已不再通过 KIE 提供**。这是对上轮“有文档但没有当前价卡”的补充纠正。产品营销页仍描述 Aleph，不应据此判断可调用。页面 12 credits 的 Gen-4 生成／延长价格更不能套到已停用的 Aleph 编辑。

来源：[KIE Aleph API 的停用说明](https://docs.kie.ai/runway-api/generate-aleph-video)。

## 其他低价生成卡不能直接当原片修改

Grok Imagine Video 1.5 产品文案会提视频编辑工作流，但当前 API 请求只有 `image_urls` 等图像/文字输入，没有原片视频字段；低价图生视频不能据此认定能直接改已有广告。Veo Lite 的参考模式同样是图像输入。本项目若改走关键帧重建，应另记为生成路线，逐帧保持、文字翻译和源背景声均不由这些便宜生成价格保证。[Grok当前合同](https://docs.kie.ai/market/grok-imagine/1-5-preview)、[Veo当前合同](https://docs.kie.ai/veo3-api/generate-veo-3-video)。

目前没有找到既明确提供源视频精确修改、又明显低于 Wan 2.7 的新增 720p 编辑候选；Wan Flash 20／5 秒可以用于更便宜的参考改版。预算可控制，效果合格率尚待用户允许后另做小额验证，本次不测试。
