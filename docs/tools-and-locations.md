# 工具、模型和文件位置

路径相对于项目根目录。使用 `bin/setup.ps1` 安装，运行 `bin/va.ps1 doctor` 核对实际位置。模型和依赖属于安装资产，`work/` 只放可重建缓存与临时工作。

| 能力 | 正式入口/实现 | 安装资产或结果 |
| --- | --- | --- |
| Python / CLI / MCP | `bin/va.ps1`、`bin/va.py`、`bin/mcp_server.py` | `.venv/`；基础 Python 在 `.runtime/python/` |
| FFmpeg / ffprobe | `media.py`、合成与采证模块 | `.runtime/ffmpeg/bin/` |
| Codex 识字/图片编辑 | `codex-packet`、`codex-result`；兼容 `bin/ocr.py` | 宿主图片能力；run 的 `analysis/codex/` 记录 |
| Whisper small ASR，含 VAD | `asr RUN`、兼容 `bin/asr.py` | `.runtime/deps/asr/`、`.runtime/models/asr/small/` |
| UVR 分轨 | `bin/separate_local_audio.py` | `.runtime/deps/separation/`、`.runtime/models/separation/` |
| 历史本地声音 | `local-tts` 仅复用完整既有结果 | 旧 `.runtime/models/tts/` 和实际声音保留；新声音用 Gemini TTS |
| KIE 配音/视频/声音分析 | `tts-packet`、`model-task`、`submit`、`poll`、`audio-analyze` | 远端服务；任务和费用保存于项目账本 |
| 本地混音 | `audio-mix RUN`、`local_audio.py` | run 中版本化声音、配方和哈希 |
| 本地图片/帧工具 | `repair-preflight`、`repair-run`、`repair-reconcile` | OpenCV 在 `.runtime/deps/vision/`；LaMa 新推理停用 |
| 文字层与合成 | `layout.py`、`compositor.py`、`surface.py` | `assets/fonts/`；目标字层逐实例核验 |
| 视觉/字幕检查 | `visual-evidence`、`visual-pages`、`visual-review`、`caption-check` | run 的实际哈希证据；展示不等于已审 |
| 恢复和批次 | `work-packet`、`production`、`batch-run` | run 状态、`state/batches/` |
| 最终必须输出 | `compose-best RUN`、`finalize RUN SPEC` | 完整翻译视频及瑕疵说明；根 outputs 标记已输出/有瑕疵，保留原质量结果 |
| 成片前失败 | `close-failure RUN SPEC` | 独立案例与候选，不虚构最终片 |
| 知识、交付与保全 | `knowledge-audit`、`deliver`、`archive-verify`、`run-preserve` | `knowledge/`、`outputs/`、`media/`、`state/` |
| 项目知识 Hook | `bin/project-hooks.ps1`、`hooks` | 项目提示、配置和检查点；只生成候选 |

配音与失败结案的完整步骤见 [本地制作入口](../agent/workflows/local-production.md)。

安装器按 `config/model-routing.json` 安装 Whisper small 与 UVR，拒绝清单之外的模型；`bin/install_dependencies.py --plan` 只展示经过校验的安装计划。图像依赖清单只有 `vision.txt`，ONNX Runtime 保留在音频依赖中用于 ASR/VAD，不代表启用了 OCR。

历史本地声音注册表只保留身份、来源和文件哈希，供核验现有声音。旧声音安装入口已移除；缺失、改稿或参数变化时使用 Gemini TTS，不补下载旧声音包，也不重新启动 Piper。实际声音仍需经过混音与字幕同步检查。

配方字段见 [修复配方](../agent/workflows/repair-recipes.md)，缓存边界见 [执行恢复](workflow-optimization.md)。一次性脚本中的坐标和审核结论不作为正式工具默认值。新源码不携带本机模型、声音包、字体、密钥或自动授权。
