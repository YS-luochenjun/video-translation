# Codex 图像工作与程序能力

总入口见 [model-routing](model-routing.md)。

## Codex 图像工作合同

2026-10-27用户明确偏好：图片能够使用ImageGen完成时，优先用宿主ImageGen进行创作、修复、重绘与图片内文字适配，尽量不使用脚本绘制或像素处理来替代。具体执行与Wan参考图的证据边界读[ImageGen优先政策](../../knowledge/rules/imagegen-first-v4.md)。FFmpeg抽帧、视频裁切/编码、混音及必要的确定性媒体操作继续保留。

1. `analyze` 后运行 `codex-packet RUN --stage recognize`。命令列出实际图片路径/哈希、任务、当前规则和命中的知识正文。逐图查看，按镜头和文字实例填写观察；原尺寸小字、遮挡和起止边界补实际帧，不用想象补齐。大量帧可用 `--spec` 指定一组图片，覆盖由 inventory 汇总。
2. 修改图片时使用 `codex-packet RUN --stage image --spec inputs/image-task.json`。spec 只有 `images` 和自由文本 `instructions`，不要求先套图片类别。查看原图后优先使用宿主ImageGen；需要透明字层时保留 alpha。将真实工具输出复制到 run 的版本化文件，保留原图。工具不可用或精确约束无法满足时，记录实际原因再选必要的确定性处理，不把脚本默认当作图片编辑器。
3. 先按返回的 stage_focus 查看当前检查动作和有适用范围的案例线索。修底使用 neutral，制作译文字面时在图片任务规格中填 `"focus_stage": "render"`。读取工作包里的规则和知识；参考案例只在其范围内适用。记录实际方法、逐图观察、`knowledge_read`、实际产物路径及未解决问题。运行 `codex-result RUN PACKET REPORT` 绑定输入、上下文和输出哈希。模板见 `agent/templates/codex-visual-task.json` 和 `agent/templates/codex-visual-report.json`。
4. 将识字结果写入 `analysis/inventory.json`，把回执的 `path` 与 `sha256` 放入 `codex_source_result`，仍逐实例保留区域、时间、译文、动作、证据和未完成覆盖。图像结果可作为现有 `reference_image`、参考底图或透明字层输入；在相关 shot 的 `codex_image_result` 填返回的 `path` 与 `sha256`，计划和渲染会重新验证，交付归档保留回执、工作包、输入与图片产物。改变任务、输入图片、知识或产物会使对应工作包失效，重新建立记录。
5. 图片产物登记只是 `needs_review`，不能自动放行底片。静态图不证明运动还原；按实际帧和音频执行原有 `visual-review → visual-release-neutral → render → capture → caption-check → quality`。配音稿不等于真实音频、ASR 空白不等于无人声、同一 Codex 自审不等于独立审查。

工作包由 Python 准备，认知和编辑由当前 Codex 宿主真实执行。项目没有假装存在一个可从 Python 直接调用的 Codex 图片 API；返回工作包不是已经完成识字或编辑。知识阅读回执也不证明实际理解，最终仍靠真实证据审核。

## 保留的程序能力

FFmpeg 抽帧、裁切、排版、透明字层、贴合、混音、编码、缓存及技术门禁继续提供给 Codex。现有修复配方是可选工具，不是固定图片分类或必须逐项尝试的阶梯。需要视频模型时统一 `model_edit`，计划默认映射 Wan 3.0，按Wan3.0单源参考与固定整数输出合同安排片段，输入加输出计费，实际细则见agent/integrations/kie.md。

无论由 Codex 还是专用模型产生，源片、知识、定稿、图片和实际视频都须可追溯；修改 inventory 后重建计划和审核。用户未要求生成新媒体时，开发验证不提交付费模型任务。

