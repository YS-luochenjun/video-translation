# 源样式记录与字体候选

总入口见 [source-typography](source-typography.md)。

## 先保留原片依据

新 `init/ingest` 请求带 `source_style_contract_version=1`。Agent在擦字和选路前查看实际原帧，按相同风格分组全部待译文字；去除发布者标记与保留原字项另走原合同。参考[样式模板](../agent/templates/source-style-capture.json)，由Agent填写原文清单、样式事实及疑点，不向用户追加表单或询问字体ID。

记录字形类别/粗细/斜体、填充、描边层次、阴影/材质/弧度、行宽与换行、位置与容器关系；运动另分static/rigid/complex，并说明实际观察。`font_class`是视觉类别，不能把推测的字体文件名当成事实。坐标与线宽按原尺寸记录，语言变化需重新适配。

## 剪映字体的参考边界

根据设计师对当前素材的来源说明，原片字体多数来自剪映（CapCut）字体库。后续选字体时，先将剪映中与原片字形、字重、宽窄、圆角/棱角、倾斜、描边承载能力和视觉重量接近的字体作为优先候选，并在样式记录中注明候选来源。这里是候选来源和比对方向，不是要求所有译片强行使用剪映字体。

只有实际原帧比对和目标语字形测试支持时才采用某个候选。若剪映候选缺少目标语字形、无法承载原有描边/阴影、破坏RTL连写、造成越界或明显改变视觉重量，应记录淘汰原因，再选择其他可用字体或艺术字路线。不能因为“剪映字体”这一来源说明就跳过原片观察，也不能随意换成系统默认字体；无法确认具体字体时，记录“剪映候选/近似方案”及具体依据，不把推测的字体名称写成事实。

```sh
python bin/va.py style-capture RUN inputs/source-styles.json --apply
python bin/va.py style-reuse TARGET --from-run SOURCE
```

capture从当前run的**原始视频**提取每组1至3个必要时刻，去重相同时间；不接受任意底片冒充源帧。快照位于run的analysis/source-styles内容寻址目录，包含源哈希、原文/时间/几何、实际帧及设计观察。重跑复用未变字节，新观察生成新目录；不会重写旧快照。其存在不证明Agent观察正确或连续运动通过。

`--apply`只绑定inventory.source_style_snapshot及实例source_style_id。目标文案、字体、布局、route与审核仍分别建立。style-reuse仅复制精确同源、同实例/几何的原观察与帧，清除目标style_treatment，绝不复制语言认可或直接调用付费模型。源run不存在时先按交付恢复合同恢复包，不根据路径/哈希假装资产还在。

