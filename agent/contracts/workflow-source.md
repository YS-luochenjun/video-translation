# 制作收件与源解析

总入口见 [workflow](workflow.md)。

## 1. 收件

宿主/主控先按真实用户消息用 `budget-open SPEC` 登记一次请求：新请求总额为去重后的实际目标语言数×60 credits，budget-open 的 targets 必填并按语言别名规范化；首次与真实新复用请求同价。额度为各语言与共用底片的灵活共享池；新增语言须根据真实用户要求用 budget-amend 扩容，不能靠换批次自动增加。旧账本保持原额、费用与未知占位，主控按真实用户授权用 budget-amend 修订才生效。同一请求的所有语言、模型、短片、run、批次与返工共用账本；创建run不能重置额度。子任务不得编造新用户消息以开额度，派生短片用 `budget-bind RUN --parent-run PARENT` 继承。旧run在绑定总账本前不能新增付费调用。然后用 `batch-create ID VIDEO --targets ...` 编排语言，第一语言作为代表语言；复用批次加 `--reused`。先运行 `kie-authorization` 读取本项目拥有者授权：automatic_use=true时，现有预算、笔数、模型限制内必要的KIE调用不再逐对话询问。登记用户请求是主控内部操作，不增加用户确认步骤。它不强制模型路线，不替代质量审核或宿主独立审批。用法和信任边界见 `agent/workflows/batch-production.md`。

保存原片、哈希、原始简述、目标 locale、品牌例外。长视频按实际原时长计额并分段处理，普通导入/解析不再受旧演示180秒硬限制；合成 demo 仍保留自身测试范围。用户只需给视频与目标语言，其余由 Agent 判断并记录；缺少会改变结果的品牌/语气约束时再澄清。

目标语言先按 `knowledge/rules/language-aliases-v3.md` 解释；可调用 `language-resolve ja` 核对。用户给定的完整分组在 `config/language-aliases.json`，`init/ingest` 自动解析并保留原始输入。此为输入字典，不占制作方法检索名额；明确的地区、简繁和口音要求同时保留在任务简述中。

## 2. 解析

自动取得媒体信息、候选切点、最长8秒的候选片段、1秒抽帧、音轨。Agent 查阅有意义的画面、补查转场与文字边界，并分析声音。按实例记录文字与人声；用 `agent/templates/inventory-example.json` 对照字段。

`analyze` 先查独立源解析库，源哈希与解析参数一致时恢复抽帧、源音轨、已绑定的源OCR/转写和源观察；已有inventory不覆盖。复用源观察后，译文、目标配音、目标时轴和审核状态重新建立。完成新源观察后用 `source-save RUN` 保存；`deliver` 自动更新快照。内容特征在inventory的 `content_features` 中记录，供条件方法检索使用。

先按 [Agent 选路](../../knowledge/rules/agent-method-selection-v2.md) 判断政策、主方法和辅助检查；在现有 reason/evidence 说明适用条件、首选与备选、切换及停止依据。家庭/医院/校园等剧情背景不直接决定算法。特征定义及同义映射见 `config/content-features.json`，多人对白用 multi_character_dialogue（multi_speaker 同义），短剧用 short_drama；未知身份保留疑点。

全片及片尾执行[水印识别与同标去除](../../knowledge/rules/publisher-watermark-removal-v2.md)。确认的发布者水印/商标用text_role=publisher_mark、统一publisher_identity及mark_form单列，target_text为空表示去除不补字；publisher_mark_review保留片尾matched/no_match与实际帧证据。静态水印也补publisher_watermark特征，不能仅移动水印才召回；产品品牌与发布者标记分别判断。格式见[水印清单示例](../templates/publisher-marks-example.json)。

特征按观察填写：艺术字用 `artistic_typography`，拍摄手机界面用 `filmed_phone_ui`，前景遮挡用 `foreground_occlusion`，需要贴合表面的字层用 `surface_typography`。这些场景即使没有文字动画也可命中视觉方法；普通静态平面文字不必添加这些特征。

新请求按[源文字样式](../../docs/source-typography.md)在擦字前保存源样式快照：Codex观察后用style-capture登记实际原帧、字形/描边/构图、运动及保护对象。目标实例写style_treatment，绑定真实字体或艺术/表面字层，说明语言适配；共享同源观察，不复制目标语言认可。plan/fast-register冻结样式，代表样片及各语言的source_style_review核对当前视频。沿用原质量容差、预算与完整输出，不引入逐帧精修。

所有任务先按 `agent/contracts/audio.md` 明确音乐、音效与对白分工；控制 AI 无法听音时仍向视频模型传递声音要求，证据不足保留 pending。

有人声时读取 `agent/contracts/captions.md`：在实例清单区分口播字幕、场景标题/UI和保留项。`speech_segments[].target_text` 是口播和对应字幕的共同定稿；先确定稿件，再生成声音与动画。

完成标准：visual/speech/timeline 均有方法与证据；实例有区域、区间、译文与动作；所有镜头有描述，完整覆盖源时间轴。自动抽帧不等于已自动 OCR/ASR。

文字识别直接由 Codex 完成：运行 `codex-packet RUN --stage recognize`，读取工作包中的实际图片、规则、偏好与命中知识正文。查看原尺寸画面和边界帧，按实例记录文字、区域、时间与疑点；用 `codex-result` 绑定真实观察，再完善 inventory。`bin/ocr.py` 仅是该工作包的兼容入口，不运行 OCR 模型。图片编辑使用同一合同的 `--stage image`，由 Codex 使用宿主图像工具完成；具体方法由 Codex 按内容选择。见 [模型与图像工作合同](model-routing.md)。

