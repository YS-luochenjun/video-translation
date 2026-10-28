# 项目知识如何跨视频使用

知识提供有适用条件的处理程序；案例提供判断这些程序的证据。方法不等于模型权重，也不能把旧素材的坐标、声音或验收直接套给新视频。

## 当前读取方式

`context.knowledge` 返回适用政策和有界方法，`context.source_references` 单独返回同源参考。`plan` 分别冻结命中正文和依赖。输入语言政策按输入阶段使用；当前数量以 `knowledge-audit` 为准。

| 方法入口 | 触发与可复用内容 | 仍需重新判断 |
| --- | --- | --- |
| [气泡排版与动态自然去字](../knowledge/rules/container-layout-and-local-motion-repair-v1.md) | 原生卡片、移动人物/纹理上的文字；分层字形测量、保护对象、原帧覆盖与局部融合；[代码入口](container-motion-repair.md) | 容器尺寸、字体塑形、运动表面、修复范围及实际模型效果；不固定 Wan |
| [选择与冲突处理](../knowledge/rules/agent-method-selection-v2.md) | 全部任务；实际条件、政策优先级、主/辅助方法组合及退出 | 新素材证据与用户硬性要求 |
| [多人固定声线](../knowledge/rules/short-drama-character-voices-v2.md) | speech 且多角色/短剧；同角色固定、不同角色区分、最低男女声 | 实际身份、音色、跨次一致及降级边界 |
| [短剧声音事件](../knowledge/rules/short-drama-audio-scenes-v2.md) | 轮换、短回复、重叠、长句、独白和片尾；按源轮次安排时间 | 实际生成时长、空隙、清晰度及句尾 |
| [实例与时间轴](../knowledge/rules/text-instance-timing-v1.md) | 每个位置、出现区间单独记录，覆盖全部镜头 | 新视频的实际边界与漏检 |
| [路线选择](../knowledge/rules/route-selection-v4.md) | 按背景、运动、保真要求选本地修复、模型编辑或重建 | 路线效果、预算和素材限制 |
| [图片修复与连续视频](../knowledge/rules/method-source-neutral-preparation-v5.md) | Codex定修复参考和译文字形，按源帧合成；需要连续重建的区域交给Wan，声音单独翻译 | 逐帧合成与逐帧生成的区别，原运动/前景/特效，模型实际采用范围，独立音频检查 |
| [文字、前景与遮挡](../knowledge/rules/method-animated-text-occlusion-v8.md) | animated_text、artistic_typography、filmed_phone_ui、foreground_occlusion、surface_typography 任一命中；分层、排版和连续编码检查 | 实际字体、取帧范围、原文字平面、背景失焦、片尾时长、动态承载面及有条件的透明资产导出 |
| [口播与字幕](../knowledge/rules/method-spoken-caption-verification-v4.md) | speech；定稿、识别分歧、句间停顿及实际混音边界 | 新语言文案、音色、时间轴与听感 |
| [水印与片尾同标](../knowledge/rules/publisher-watermark-removal-v2.md) | 识别发布者身份，默认去除静态/移动水印及匹配片尾商标；检查模糊入场、边缘、旋转和切镜 | 实际身份关联、产品品牌区别、用户保留例外、轨迹和干净供体 |

共同政策包括 [视觉门禁](../knowledge/rules/neutral-visual-and-animation-gate-v4.md)、[口播字幕统一](../knowledge/rules/user-caption-audio-sync-20261019.md)、[请求总预算](../knowledge/rules/user-language-budget-60-20261026.md)、[语言别名](../knowledge/rules/language-aliases-v2.md) 和 [不以实色块盖字](../knowledge/rules/user-no-solid-text-panels-20261022.md)。参数与状态由当前配置及索引决定。

## 证据与推广边界

多源观察至少来自两个不同源视频；同源多语言或多轮返工不增加独立来源数。这一等级包含反例，不等于多次成功验收。旧“通过”被反证推翻时，同时保留原评审、追加观察及当前使用限制。

`examples/` 保存独立图片、音频、原始观察及 manifest。案例正文与通用方法可能谈同一主题，但前者限定某个来源，后者规定条件和步骤。逐字相同的旧兼容副本已去除；被替代版本集中在 `history/`。详见 [知识目录](../knowledge/README.md)。

候选部分采纳的关系记录在 `curation/`。相同含义且范围一致时合并证据；特定阈值、遮罩、字体、模型成功与未验证细节保留原范围。结构整理不自动启用候选，也不修改公司偏好。

## 按信息载体选择制作重点

[三类广告](../knowledge/rules/content-led-localization-v1.md)：音频主导先处理完整人声、角色与时间，画面文案主导先处理文字/底面/动画，混合型两条链路合成；所有类型都翻译旁白和对白并保留音乐音效。分类依据与方法首选/备选、切换/停止条件进入 routing_assessment，普通/快速模式均冻结。程序补齐可从角色/文字事实得到的标签，适用 required 方法完整返回，Agent 保留实际方法选择权。
