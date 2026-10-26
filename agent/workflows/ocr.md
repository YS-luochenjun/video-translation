# Codex 文字识别

文字识别统一由 Codex 直接看图完成。先运行 `analyze`，再执行 `codex-packet RUN --stage recognize`，读取真实图片清单与项目知识。旧 `bin/ocr.py RUN` 也只生成该工作包，不启动 RapidOCR 或 GLM。

逐实例记录原文、译文、区域、出现/消失时间、保留理由与实际帧证据；小字、旋转、遮挡及动画边界补查原尺寸相邻帧。看过代表图不代表全片覆盖。分组工作包可通过 `--spec` 的 images 指定，每组结果由 `codex-result` 登记，最后由 Codex 汇总 inventory，未解决项保持 pending。

图片处理及回执格式见 [模型与图像工作合同](../contracts/model-routing.md)。旧 OCR 本机配置不再生效，历史报告保留为来源记录；其候选、空识别和旧 pass 都不代替本次观察或质量审核。
