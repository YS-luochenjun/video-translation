# 动态标题、CTA与关键词强调

用户于2026-10-26明确要求正式接入Remotion。现有`render`的prepared_video、reference_composite和erase_then_overlay路径已调用统一文字适配器。简单文字没有`display.motion`时继续现有FFmpeg流程。底片审核、真实配音、字幕同步和最终质量门禁保持原职责。

## 选择与输入

只在实际标题、CTA、强调词需要动效时填写[文字模板](../agent/templates/motion-typography.json)：`display.motion.kind`为`title`、`cta`或`emphasis`，`effect`为`fade_scale`或`none`。强调字段`emphasize`必须唯一匹配定稿的目标文字，`emphasis_at`是原片绝对秒数；不填则在实例开始后0.4秒强调。其它实例继续FFmpeg；不能仅凭“是广告”就新增动效或文案。

每个动态实例需要run内单字体TTF/OTF的`font_asset.path/sha256`、实测`bbox`及`start/end`。TTC先提取实际需要的face，再哈希登记。程序检查实际字形覆盖，按真实字体在指定区域内从font_size缩至min_font_size，最低16px；可读性或换行仍需Agent按语言判断。不要依赖隐式字体替换。实际粗体/斜体需提供对应字体文件，不能要求引擎自行合成风格。

初版是固定屏幕区域的淡入/缩放与关键词变色；不接管口播字幕、已有独立surface字层、轨迹、遮挡、旋转、复杂描边或布料变形。这些输入会被明确拒绝，需回到原有专门路线处理。实例之间有同时发生的区域重叠也须先解决。CTA只渲染文字，不新增实心底板。

## 安装与本机配置

在项目Python环境安装可选`typography`依赖（Pillow、fonttools、numpy）。Node和浏览器由操作者提供，Remotion依赖固定在[src/remotion_renderer/package.json](../src/remotion_renderer/package.json)及锁文件中，安装到`.runtime/deps/remotion`，不进入源码目录。

```sh
python bin/setup_remotion.py --install --pnpm /absolute/path/to/pnpm
python bin/setup_remotion.py --configure --node /absolute/path/to/node --browser /absolute/path/to/browser
python bin/va.py doctor
```

`--install`才执行依赖安装；`--configure`才写本机`config/remotion.local.json`。Remotion/React、浏览器和node_modules由用户按需下载，不随GitHub源码发布；仓库仅保留本项目适配器和固定版本清单。bundler以`.runtime/deps/remotion`为rootDir，避免向src写依赖缓存。render过程不会下载浏览器、安装包或购买许可证。完整Chrome for Testing可加`--chrome-mode chrome-for-testing`。无可用Remotion环境时可用FFmpeg静态回退，前提是字体和内容检查通过。

本机Mac测试使用官方Headless Shell156.0.8078.47加项目内启动器`--disable-gpu --in-process-gpu`；默认157曾在ICU/GPU初始化阶段崩溃。这个兼容选项不作为其它平台默认，也不证明WebGL可用。参考[先前实测](research/2026-10-26-remotion-evaluation.md)。商业许可资格由部署方核对；正式适配器使用production渲染参数，不把开发模式视为许可豁免。

宿主执行沙箱也可能禁止Chrome启动。依据宿主现有授权策略运行本地媒体进程，不修改系统安全设置或在程序内绕过沙箱；如仍不可用，保留明确原因并审核静态回退。FFmpeg和浏览器的字形轮廓、字号度量可能不同，回退可读性必须看实际成片，不能只读数值。

## 正常与快速流程

正常流程：清单加入motion及字体资产→重新plan→核对无字底片放行→render。新plan冻结字体和政策哈希；内容、几何、字体或政策变化须重新计划。可选渲染受项目run锁、重任务名额、磁盘余量和180秒超时控制，超时终止渲染进程树。没有motion的旧计划继续原流程。

默认快速交付可以从已审核prepared_video镜头生成同一适配器的输出：

```sh
python bin/render_typography.py RUN --shot s001
```

清单覆盖与底片审核仍须完成。返回`output`和`typography_assets`，在fast recipe的`assets`中绑定实际输出和准备依赖，并将`typography_assets`原样放入recipe。再按既有音频流程合成完整成片，fast-register登记真实final output。注册器核验字层覆盖、实际合成输出绑定与来源；该命令本身不会生成验收。完整成片仍走capture/fast-review/quality，不把标题当作对白字幕。

## 检查、回退与交付

两种引擎都逐帧解码最终alpha，核对尺寸、30fps、帧数、指定时段、文字非空、区域外透明和边缘安全距离；输出为现有surface接口接受的qtrle/argb。Remotion先生成ProRes4444再转换。源、语种、清单、字体、参数、alpha、准备输入和实际输出均由哈希回执绑定，既有surface.verify再次检查。最终音轨由原项目合成流程选择，字层中不包含声音。

缺字、字体篡改、无法以可读字号适配、错误坐标/实例或不支持的复杂几何属于内容问题，明确报错。浏览器、Node、依赖、超时或Remotion输出异常时，只尝试一次FFmpeg静态字层并再次检查；回退也失败则保留明确错误，不跳过文字。回退不会调用新视频模型或增加KIE额度。按30fps映射半开帧区间，ASS边界向下取厘秒，避免结束时间向上舍入多显示一帧。

回退保留完整文字及时间，去掉淡入/缩放/定时变色。LTR静态强调可保留词色；RTL保留完整连写段落并使用原文字色，避免ASS行内颜色标签引发词序变化。这些损失写入绑定的fallback.json，不把静态输出称为动效完成。

candidate.json返回`typography_assets`与`typography_fallbacks`。普通/快速审核遇到静态回退必须在review的`typography_fallbacks`中写`receipt_sha256`、`accepted: true`和真实`observation`；未确认时quality阻断。只有在实际效果仍满足需求时接受，否则有界返工。来源/字号/alpha技术通过不代表语言、视觉或用户验收。

交付库沿回执复制字层、字体、参数及准备依赖；缓存签名包含实现和环境，动态实例不复用旧分段缓存，先前回退也不被production checkpoint长期缓存。重建bundle在`work/runs/RUN`，任务收尾登记缓存并maintain --close，不删除必要回执或未知费用记录。
