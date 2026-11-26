# 模型及工具资产

总入口见 [model-routing](model-routing.md)。

## 下载、安装与历史资产

`bin/setup.ps1` 调用统一安装器。安装器先读取模型路由并校验完整清单，再安装依赖与模型；不再提供选择旧 ASR 型号或安装旧声音包的参数。已有 Python 时，`.venv/Scripts/python.exe bin/install_dependencies.py --plan` 可只读查看实际清单。

- 本地权重只有 Whisper small 与 UVR Inst HQ3。Whisper 的 VAD 和 ONNX Runtime 属于必要音频依赖；UVR 下载必须与当前注册表的模型身份、路径、地址及哈希完全一致。
- 图片依赖只有 `bin/requirements/vision.txt`，统一放在 `.runtime/deps/vision/`；不从旧 OCR 目录回退加载。基础依赖、ASR 和分轨分别使用 `core.txt`、`asr.txt`、`separation.txt`。
- Gemini Flash、Gemini TTS、Wan 3.0 通过远端 API 调用，项目不下载它们的权重；Codex 图像能力由宿主提供。
- 旧模型文件、旧声音和历史记录保持原样。`config/local-voices.json` 只记录历史声音身份与哈希，没有安装或新合成入口。旧文件缺失、损坏或参数不匹配时停止复用，转到当前能力，不重新下载安装旧模型。

下载的完整性检查、下载锁和断点恢复继续保留。真实网络下载、当前机器安装、隔离源码检查和真实媒体质量是不同验证范围，报告分别说明。

