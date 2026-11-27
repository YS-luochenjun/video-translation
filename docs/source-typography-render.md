# 目标字层、渲染与审核

总入口见 [source-typography](source-typography.md)。

## 每实例选择目标路线

inventory实例填写 `style_treatment`：route、reason、adaptations；typeset另写font_choice_reason。adaptations为“改变的方面→具体理由”，没有变化填空对象。颜色、斜体、字重、分行、描边、对齐变化必须说明；承认变化不使质量自动通过。宽高、材质、视觉分量、运动和保护对象仍须实际看成片。

原文擦除几何保留在实例bbox/source_interval，不为移动译文改写原观察。调整屏幕固定的译字区域时用display.bbox并记录layout适配；静态确定性排字可用display.line_height控制显式多行间距。固定目标框不能暗中替代动态轨迹。

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

目标例：display.font_asset绑定真实粗斜体，bold=true、italic=true、color=#000000、outline=5、outline_color=#FFFFFF，按实际区域填写font_size与min_font_size。目标文案需要两行时显式填写自然断点；短译文可单行。不同语言各自核验字形；原字体不含中文时，选择视觉类别合适的中文字体并说明适配。min_font_size不能作为“足够可读”的自动证明。

普通字层的FFmpeg合成实际加载绑定字面，按同一字面测量，支持原有多层描边、阴影、倾斜与轨迹；指定斜体却提供直立字面会报错。复杂弧形/材质/透视不因这些字段存在就称已实现，应选艺术素材/专用表面字层或有据披露降级。

## 渲染时的工程核验

绑定字面在FFmpeg/libass中使用按字体哈希生成的局部唯一家族名，保留物理字重和字形；原始绑定资产不改名、不覆盖。这样同一家族的Regular/Bold或不同粗体字重不会只凭bold布尔值相互替代。局部导出字体及来源哈希保存在渲染回执中，缓存被改动时报错。

静态排字测量计入最外层描边、阴影和实际字形边界；容器放不下时先等义断行、调整有据的布局或字面，不能低于显式最小可读字号。测量通过仍须查看最终编码短语及相邻实例，不能证明透视、复杂变形或所有字体的视觉一致。

多行或多层描边的文字优先使用现有排字路线。自定义合成先按实际字面、目标语断行和最外层占位确定每行的字形位置与基线，再由填色和各层描边共用同一布局。阴影仅应用设计所需的偏移。使用 Pillow 时避免用不同 `stroke_width` 多次调用 `multiline_text` 叠画同一段落，因为各次计算的行距可能不同。扩语种前用实际多行、最粗描边的代表镜头查看原尺寸编码帧，尤其核对第二行及以后是否重影。实际成片的发布判定见[标题审核](../agent/contracts/quality-visual.md#标题与转场审核)。

清底对照除区间首/中/末帧外，追加前后各一个实际原生帧，捕捉擦除范围外的单帧残字；source_ghost_interval另行覆盖。每区间最多5帧，未变输入复用，不逐帧生图，也不自动延长修复区间或判通过。工程回归与适用边界见[原生渲染与取证](../knowledge/rules/native-render-evidence-guards-v1.md)。

## 计划、样片与交付

### 批量生成字层

使用 `agent/templates/style-layer.json`，正文的 `display.timed_fragments` 来自已审实际配音对齐，`font_asset` 由font-bind取得；`artwork`只引用少量已实际生成、逐字检查的透明PNG。目标框在display.bbox，源擦字框不变。无需每次编写素材专用PIL字层或逐帧管线。

艺术字和去字参考可从[提示词模板](../agent/templates/style-artwork-prompts.json)填入实际原帧观察与目标定稿，二者用途分开。只继承结构与保护约束，不照搬056日语文本或造型。正式plan的surface路线仍要求已核验的prepared底片；字层生成不承担去字，也不批准底片。

```sh
python bin/va.py style-layer RUN inputs/style-layer.json --apply
```

命令复用现有真实字体排版，批量生成所选镜头的透明surface字层；静态或有据的简单pop适配可一次渲染，复杂轨迹/遮挡继续走既有专用surface/Remotion路线。绑定源、定稿、短语、字面、输入图及原生帧时轴；未变输入复用，不擅自去字或发模型请求。`--apply`绑定实例与镜头surface，保留之前inventory；随后重建计划或fast-register并审核。要求透明素材、完整定稿及不覆盖显式保护对象；不提供视觉pass，也不将模型参考图自动变成正确的译文。

普通plan与fast-register都冻结source_style_contract，重新核验源快照、帧、字体和目标选择；任一被改动都须重新计划。实际文件随独立交付包保存，不只留下旧run路径。旧请求没有新版本标记且未主动绑定快照时保留原合同与历史判断，不重做已交付视频。

先完成一个代表语言的完整样片，再按既有batch-approve扩展。新审核模板source_style_review逐实例检查lettering/layout/motion/protected_content，附实际观察和当前视频capture里的图片。仅凭原帧、音频、旧版本图片或勾选“通过”不能放行；缺证据/明显失败阻断quality通过。轻微差异按原质量标准记minor，记录适配不等于风格一致，完整输出与质量通过继续分开。

本功能没有自动识别并复原任意字体，没有新增跟踪模型，也不会自动调用ImageGen或Wan。保存一次源设计、复用源观察和现有字层机制是为了控制重复分析与生成次数；实际节省时间/改善程度须用具体视频验证，不能由单图认可推断。
