# 制作选路与实际执行

总入口见 [workflow](workflow.md)。

## 3. 判断与执行

动态标题、CTA、关键词强调按[Remotion文字适配器](../../docs/remotion-typography.md)填写明确display.motion和绑定字体，重建计划后走现有render；简单文字沿用FFmpeg。快速流程可先用bin/render_typography.py生成已审底片上的文字，再把实际输出与typography_assets绑定进recipe。渲染失败回退静态字层，降级必须由真实成片审核确认；字体、内容和区域不合格不能借回退绕过。

图片编辑由 Codex 主动选取实际原图与方法，先完成 `codex-packet --stage image` 的知识读取和真实编辑，再登记产物。静态及移动/旋转水印按 [去水印规范](../../knowledge/rules/publisher-watermark-removal-v2.md) 操作。先用 `repair-preflight RUN` 对照实际产品/姿态切点、文字模糊入场和完整画面边缘；本地配方执行与受控试验见 [修复配方](../workflows/repair-recipes.md)。原尺寸查看优先使用 `visual-pages --layer final --limit 2` 与返回的 `--after-frame` 续看，不另写查看脚本。展示游标只记录展示，不代表已审。

匹配有效知识；生成可审查计划。图片工作由 Codex 完成，连续视频需要模型时统一使用 Wan 2.7；本地合成负责把已审图片/字层与原片结合。按模型实际限制合并/拆分片段，不把30秒直接塞进8秒接口。检查 payload、附件与成本估算后执行。

独立配音先确定目标稿件，再用 `tts-packet` 准备 Gemini TTS 任务。旧本地声音只复用已存在且匹配定稿的结果。改稿、语速、说话人或模型会使对应声音失效。裁切、变速、偏移与回混完成后取得实际字词/短语时间，运行 `captions RUN --alignment analysis/caption-alignment.json --apply`。按生成的时间片段排字幕、重建透明字层，然后生成计划。模型直接编辑路线可先生成，但仍要通过实际成片的字幕同步审查。

完成标准：每段有可定位输入与输出；付费任务有 taskId 或明确失败/未知状态。模糊网络失败保留账本，不能当作未提交自动重试。失败响应也消耗本地任务尝试名额。

共享视觉准备先按当前模式实际检查无字短片（fast 基本检查，strict 完整逐实例门禁），再制作一个代表语言的完整编码样片，最后扩展批次。原字清除、背景纹理、前景运动、动画与关联图形分别检查；静止参考图不能代替原本会动的头发、手部或物体。参考帧不可跨照片切换、姿态或遮挡直接复用。缺少可验证的修复效果时保留未通过，低费用或“多数区域正常”不能替代视觉要求。

严格路线开始文字替换前读取 [逐实例去字与呈现审查](../../knowledge/rules/neutral-visual-and-animation-gate-v4.md)。底片用`visual-evidence RUN --stage neutral --shot ID`生成pending证据，逐实例`visual-review`后`visual-release-neutral`放行并重建plan；成片用`visual-evidence RUN`（production自动执行），逐实例观察后重新capture/quality。动态区域检查连续原尺寸帧，各语言分别检查贴合与遮挡，不能批量填pass。具体操作见[视觉门禁](../workflows/visual-review.md)。

同源、同时间区间、已通过且无质量异议的无字底片，可用 `reuse-neutral TARGET --from-run SOURCE --source-shot ID --target-shot ID` 复制素材和独立证据并绑定目标镜头。重新建立目标译稿、配音、字层与评审，再重建plan；此操作不重新编码底片，也不把源语言的成片通过状态复制过去。

