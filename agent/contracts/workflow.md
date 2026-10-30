# 制作、检查、返工、交付

当前用户授权的默认模式是[快速交付](../workflows/fast-delivery.md)。新请求记录 `delivery_mode=fast`，优先按该工作流完成基本效果、增量检查和轻量收尾；下文完整逐实例门禁仍用于严格路线。模式变更不改写旧候选的审核结果。

所有任务同时遵守[最终输出](../workflows/always-output.md)：下文门禁决定质量通过和返工；返工结束仍用 `finalize` 输出当前最佳完整翻译视频，不能因分数未达标而无视频结案。旧 `close-failure` 保留失败证据，但不代替新任务的最终视频。

续作和切换阶段时优先运行 `work-packet RUN [--stage source|translation|neutral|render|review|delivery]`，从现有状态取得待办、任务恢复提示与知识入口，不另写重复进度日志。它只导航，不替代知识正文、真实观察或审核。制作的缓存、资源限制和兼容入口见 [缓存与执行恢复](../../docs/workflow-optimization.md)。

工作包中的 `knowledge_advisories` 是待验证观察，和正式 `knowledge` 分开。按需读其原文，用作风险提醒或试验依据，不能直接作为通过标准。结案时按 `knowledge_followup` 用 `knowledge-use` 记录实际采用、未采用及效果，再审查 `knowledge-queue` 中本次新增或受反例影响的内容，具体见 [知识合同](knowledge.md)。

已有诊断预览、重复修复或正式候选尚未交付时，按 [制作收口](../workflows/production-completion.md) 处理：先完成 `next_action` 指出的当前缺口，复用已核验资产；当前候选待审则补实际审核，quality通过则直接deliver。水印／发布者标记默认去除，识别其文字/图形身份并检查片尾同标；用户本次明确要求保留的例外记录来源，旧评审不覆盖。

## 1. 收件

宿主/主控先按真实用户消息用 `budget-open SPEC` 登记一次请求：新请求总额为去重后的实际目标语言数×60 credits，budget-open 的 targets 必填并按语言别名规范化；首次与真实新复用请求同价。额度为各语言与共用底片的灵活共享池；新增语言须根据真实用户要求用 budget-amend 扩容，不能靠换批次自动增加。旧账本保持原额、费用与未知占位，主控按真实用户授权用 budget-amend 修订才生效。同一请求的所有语言、模型、短片、run、批次与返工共用账本；创建run不能重置额度。子任务不得编造新用户消息以开额度，派生短片用 `budget-bind RUN --parent-run PARENT` 继承。旧run在绑定总账本前不能新增付费调用。然后用 `batch-create ID VIDEO --targets ...` 编排语言，第一语言作为代表语言；复用批次加 `--reused`。先运行 `kie-authorization` 读取本项目拥有者授权：automatic_use=true时，现有预算、笔数、模型限制内必要的KIE调用不再逐对话询问。登记用户请求是主控内部操作，不增加用户确认步骤。它不强制模型路线，不替代质量审核或宿主独立审批。用法和信任边界见 `agent/workflows/batch-production.md`。

保存原片、哈希、原始简述、目标 locale、品牌例外。长视频按实际原时长计额并分段处理，普通导入/解析不再受旧演示180秒硬限制；合成 demo 仍保留自身测试范围。用户只需给视频与目标语言，其余由 Agent 判断并记录；缺少会改变结果的品牌/语气约束时再澄清。

目标语言先按 `knowledge/rules/language-aliases-v2.md` 解释；可调用 `language-resolve ja` 核对。用户给定的完整分组在 `config/language-aliases.json`，`init/ingest` 自动解析并保留原始输入。此为输入字典，不占制作方法检索名额；明确的地区、简繁和口音要求同时保留在任务简述中。

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

## 3. 判断与执行

动态标题、CTA、关键词强调按[Remotion文字适配器](../../docs/remotion-typography.md)填写明确display.motion和绑定字体，重建计划后走现有render；简单文字沿用FFmpeg。快速流程可先用bin/render_typography.py生成已审底片上的文字，再把实际输出与typography_assets绑定进recipe。渲染失败回退静态字层，降级必须由真实成片审核确认；字体、内容和区域不合格不能借回退绕过。

图片编辑由 Codex 主动选取实际原图与方法，先完成 `codex-packet --stage image` 的知识读取和真实编辑，再登记产物。静态及移动/旋转水印按 [去水印规范](../../knowledge/rules/publisher-watermark-removal-v2.md) 操作。先用 `repair-preflight RUN` 对照实际产品/姿态切点、文字模糊入场和完整画面边缘；本地配方执行与受控试验见 [修复配方](../workflows/repair-recipes.md)。原尺寸查看优先使用 `visual-pages --layer final --limit 2` 与返回的 `--after-frame` 续看，不另写查看脚本。展示游标只记录展示，不代表已审。

匹配有效知识；生成可审查计划。图片工作由 Codex 完成，连续视频需要模型时统一使用 Wan 2.7；本地合成负责把已审图片/字层与原片结合。按模型实际限制合并/拆分片段，不把30秒直接塞进8秒接口。检查 payload、附件与成本估算后执行。

独立配音先确定目标稿件，再用 `tts-packet` 准备 Gemini TTS 任务。旧本地声音只复用已存在且匹配定稿的结果。改稿、语速、说话人或模型会使对应声音失效。裁切、变速、偏移与回混完成后取得实际字词/短语时间，运行 `captions RUN --alignment analysis/caption-alignment.json --apply`。按生成的时间片段排字幕、重建透明字层，然后生成计划。模型直接编辑路线可先生成，但仍要通过实际成片的字幕同步审查。

完成标准：每段有可定位输入与输出；付费任务有 taskId 或明确失败/未知状态。模糊网络失败保留账本，不能当作未提交自动重试。失败响应也消耗本地任务尝试名额。

共享视觉准备先按当前模式实际检查无字短片（fast 基本检查，strict 完整逐实例门禁），再制作一个代表语言的完整编码样片，最后扩展批次。原字清除、背景纹理、前景运动、动画与关联图形分别检查；静止参考图不能代替原本会动的头发、手部或物体。参考帧不可跨照片切换、姿态或遮挡直接复用。缺少可验证的修复效果时保留未通过，低费用或“多数区域正常”不能替代视觉要求。

严格路线开始文字替换前读取 [逐实例去字与呈现审查](../../knowledge/rules/neutral-visual-and-animation-gate-v4.md)。底片用`visual-evidence RUN --stage neutral --shot ID`生成pending证据，逐实例`visual-review`后`visual-release-neutral`放行并重建plan；成片用`visual-evidence RUN`（production自动执行），逐实例观察后重新capture/quality。动态区域检查连续原尺寸帧，各语言分别检查贴合与遮挡，不能批量填pass。具体操作见[视觉门禁](../workflows/visual-review.md)。

同源、同时间区间、已通过且无质量异议的无字底片，可用 `reuse-neutral TARGET --from-run SOURCE --source-shot ID --target-shot ID` 复制素材和独立证据并绑定目标镜头。重新建立目标译稿、配音、字层与评审，再重建plan；此操作不重新编码底片，也不把源语言的成片通过状态复制过去。

## 4. 检查与返工

拼接后抽取成片证据，复制 review/template.json 填写 review/review.json。Agent 查逐实例翻译、漏字、原字残留、闪烁、时序、品牌与广告含义，实际听音或提供可核对音频证据。不能把未看的视频填为通过。

有人声时完成该视频哈希目录的 `caption-sync.json`，同时引用成片 WAV 和字幕边界帧，记录实际说出和实际显示的时间。完成后重跑 `capture` 冻结证据，再执行 `quality`；音频单独送审的同步结论不能替代视听同步检查。

概览拼图用于定位，不作为擦字验收的唯一证据。必须查看原尺寸问题区域、无字底片和透明字层，并核验实际编码的连续运动与首末边界。OCR为空、哈希正确、单张关键帧干净都不能证明去字成功或运动保真。制作门禁的签字和检查字段须来自真实观察。

失败时先记录观测和待验证原因，再选一个变量：单实例、短片段、明确时间区域、更换路线。最多两轮；无法合格时按 always-output 输出当前最佳完整译片及瑕疵说明，明确尚未质量通过；用户必需配音且不可用时如实报告，不以字幕替代。

## 5. 交付与学习

正常质量通过路线通过 `quality` 后 `deliver`；有界返工后未通过的完整候选按 always-output 用 `finalize`，两者状态分开。正常路线得到 `outputs/` 中独立交付包的final.mp4与哈希证据，run内副本保留。交付函数自动归档并执行候选复盘，返回package/case/inbox；中途失败可重试收尾，不重发模型任务。有候选成片的失败结案运行 `reflect`；还没有候选的失败使用 `close-failure RUN SPEC`，记录实际观察、哈希绑定证据与未审范围，不伪造 candidate 或 quality。见 [本地配音与失败结案](../workflows/local-production.md)。

单次或批量收尾后运行 `delivery-index` 刷新 `outputs/index.html`，按任务和语言直接打开正式包中的视频。默认不给 outputs 根目录增加便捷视频副本、批次视频文件夹或 ZIP；只有用户明确需要下载打包时才导出到用户指定位置。批次独有字幕和说明可放 `outputs/reports/<批次>/`，不存媒体副本。参考/待改进版本保留原状态，不因打包而称为已交付。目录入口是可重建视图，`index.json` 和各交付包 manifest 才是定位依据。

知识提纯、用户反馈和素材保留按 `.agents/skills/knowledge-curation/SKILL.md`；方法和必要案例长期保存在knowledge，源片/底片/各语言成品保存在可到期的outputs，runs为执行过程。自动候选不改变正式知识或公司偏好。最终给用户视频、关键权衡、验证范围和待解问题。

用户否定或复现推翻某版质量时，按 `agent/templates/quality-hold.json` 运行 `quality-hold SPEC`，将具体成片及确认有缺陷的共享底片分别绑定实际哈希，保存有来源的反馈证据。随后刷新delivery-index。原评审和交付包保留历史原文；当前目录与library-find显示质量异议和production_eligible=false，制作及deliver入口阻断被否定的字节。新修复版本用新哈希重新审核，音轨和译稿是否可复用分别判断。不要只把反馈记进候选而让旧成功标签继续指导制作。详见 `agent/workflows/quality-feedback.md`。


每次运行开始与续作读取 `work-packet.maintenance`；外部交付及记录完成后执行 `maintain RUN --close`，检查删除/暂缓回执。临时缓存归属和自动整理见 [存储合同](storage.md)。

## 信息载体与方法选择记录

新请求记录 routing_contract_version=1。按 [三类广告条件](../../knowledge/rules/content-led-localization-v1.md) 判断 audio_led、onscreen_text_led 或 mixed；只发现音乐/非语言音效且无待译文字时可有据写 preserve_only。全片有主类型，实际需要时记录片段例外；不按字数、镜头人数或剧情地点自动归类。旁白、对白、独白及片尾口播全部进入人声清单，不受主类型影响。

在 inventory.routing_assessment 填 version=1、primary_type、reason、真实 evidence，以及 method_choices：每个需要翻译的 speech/visual 域记录 domain、命中的 method_id、reason、alternative、switch_when、stop_when。程序在 plan/fast-register 前检查完整性及已适用方法，语义判断仍由 Agent 负责。每句 speech_role 区分 dialogue/narration/monologue/spoken_cta/unknown，character_id 未确认可写 unknown 并补证。

已确认不同 character_id 自动补多人检索，待译文字补 onscreen_text；context.feature_origins 说明补齐依据。required 方法及政策完整返回，六条上限仅限制额外可选方法。快速模式同样冻结计划、知识正文、选择和待反馈项目；旧计划缺记录时提示重新登记现有资产，不伪造旧事实或重发模型。
