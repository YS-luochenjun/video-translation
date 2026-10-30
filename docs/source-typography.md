# 视频源文字样式：先记录，再重建与审核

来源：项目拥有者要求改善视频字体效果，并参考单图片翻译的样式分析与分层设计；不迁移逐图像素修补、专用重画脚本或逐帧生图。目标是保留可观察的风格与信息层级，允许有依据的语言适配，不承诺恢复原字体文件或任意艺术字完全一致。

## 先保留原片依据

新 `init/ingest` 请求带 `source_style_contract_version=1`。Agent在擦字和选路前查看实际原帧，按相同风格分组全部待译文字；去除发布者标记与保留原字项另走原合同。参考[样式模板](../agent/templates/source-style-capture.json)，由Agent填写原文清单、样式事实及疑点，不向用户追加表单或询问字体ID。

记录字形类别/粗细/斜体、填充、描边层次、阴影/材质/弧度、行宽与换行、位置与容器关系；运动另分static/rigid/complex，并说明实际观察。`font_class`是视觉类别，不能把推测的字体文件名当成事实。坐标与线宽按原尺寸记录，语言变化需重新适配。

```sh
python bin/va.py style-capture RUN inputs/source-styles.json --apply
python bin/va.py style-reuse TARGET --from-run SOURCE
```

capture从当前run的**原始视频**提取每组1至3个必要时刻，去重相同时间；不接受任意底片冒充源帧。快照位于run的analysis/source-styles内容寻址目录，包含源哈希、原文/时间/几何、实际帧及设计观察。重跑复用未变字节，新观察生成新目录；不会重写旧快照。其存在不证明Agent观察正确或连续运动通过。

`--apply`只绑定inventory.source_style_snapshot及实例source_style_id。目标文案、字体、布局、route与审核仍分别建立。style-reuse仅复制精确同源、同实例/几何的原观察与帧，清除目标style_treatment，绝不复制语言认可或直接调用付费模型。源run不存在时先按交付恢复合同恢复包，不根据路径/哈希假装资产还在。

## 每实例选择目标路线

inventory实例填写 `style_treatment`：route、reason、adaptations；typeset另写font_choice_reason。adaptations为“改变的方面→具体理由”，没有变化填空对象。颜色、斜体、字重、分行、描边、对齐变化必须说明；承认变化不使质量自动通过。宽高、材质、视觉分量、运动和保护对象仍须实际看成片。

原文擦除几何保留在实例bbox/source_interval，不为移动译文改写原观察。需要调整静态译字位置时用display.bbox并记录layout适配；display.line_height控制显式多行间距。固定目标框不能暗中替代动态轨迹。

| 观察与目标 | route与执行 | 切换及限制 |
| --- | --- | --- |
| 常规字或可用字体/描边/阴影表达的造型 | typeset：真实font_asset，display填写字体效果与明确换行，走已审底片或erase_then_overlay | 字形缺失/粗斜体不实/最小可读字号放不下时停止，不隐式换字体、不无限缩小；先等义断行或换合适字体 |
| 少量复杂艺术标题、CTA | imagegen_asset：按ImageGen优先政策制作局部目标字/装饰资产，逐字核对，再绑定现有surface_typography透明视频层 | 不自动生图，不重画整帧人物；复合容器资产如实标注，保留原字清底与保护对象审核 |
| 跟随移动、表面或遮挡的字层 | tracked_layer：现有外部surface字层及真实轨迹/遮挡来源 | 路线名称不能证明跟踪完成，每个覆盖镜头都须有实际字层与来源回执；内置Remotion仅支持其原有简单动效 |
| 连续变形/复杂遮挡确需视频编辑 | wan_reference：实际同镜头参考图与Wan替换文字任务 | 原片控制运动；去字参考与译字参考用途分开，erase-only不能宣称已按参考生成译字，仍实际审字形与连续帧 |

复杂度与运动是两个维度：静止艺术字可只制作一次资产；普通字也可能有复杂遮挡。不逐帧制作图片，不要求所有字体都试失败后才用ImageGen，不预设必须付费。全部文字仍翻译，额外视觉设计优先用于显眼标题/CTA/场景艺术字。沿用原预算与两轮有界返工，不重开费用池。

### 绑定真实字体，而不是默认Arial

原有font-bind --family可继续用于已登记字体家族。新增明确字体文件入口，支持实际存在的装饰/粗斜体或TTC字面；不自动下载、安装、购买或合成假斜体。

```sh
python bin/va.py font-bind RUN --font-path "/available/font/BoldItalic.ttf" --text "Final target copy"
# TTC可加 --face-index 具体字面索引；返回的path/sha256填到display.font_asset。
```

目标例：display.font_asset绑定真实粗斜体，bold=true、italic=true、color=#000000、outline=5、outline_color=#FFFFFF、font_size与min_font_size按区域填写，译文用显式换行保留两行构图。不同语言各自核验字形；原字体不含中文时，选择视觉类别合适的中文字体并说明适配。min_font_size不能作为“足够可读”的自动证明。

普通字层的FFmpeg合成实际加载绑定字面，按同一字面测量，支持原有多层描边、阴影、倾斜与轨迹；指定斜体却提供直立字面会报错。复杂弧形/材质/透视不因这些字段存在就称已实现，应选艺术素材/专用表面字层或有据披露降级。

## 计划、样片与交付

普通plan与fast-register都冻结source_style_contract，重新核验源快照、帧、字体和目标选择；任一被改动都须重新计划。实际文件随独立交付包保存，不只留下旧run路径。旧请求没有新版本标记且未主动绑定快照时保留原合同与历史判断，不重做已交付视频。

先完成一个代表语言的完整样片，再按既有batch-approve扩展。新审核模板source_style_review逐实例检查lettering/layout/motion/protected_content，附实际观察和当前视频capture里的图片。仅凭原帧、音频、旧版本图片或勾选“通过”不能放行；缺证据/明显失败阻断quality通过。轻微差异按原质量标准记minor，记录适配不等于风格一致，完整输出与质量通过继续分开。

本功能没有自动识别并复原任意字体，没有新增跟踪模型，也不会自动调用ImageGen或Wan。保存一次源设计、复用源观察和现有字层机制是为了控制重复分析与生成次数；实际节省时间/改善程度须用具体视频验证，不能由单图认可推断。
