# 媒体与编辑器

当前安装入口面向 Windows x64，由 `bin/setup.ps1` 准备项目 Python、FFmpeg/ffprobe、图片处理依赖，以及 Whisper small（含 VAD）和 UVR 的模型与音频依赖。它不安装 OCR 或本地配音模型。`bin/va.ps1` 使用项目虚拟环境；具体位置见 [工具清单](../../docs/tools-and-locations.md)。

本地修复、透明文字层、遮挡、表面贴合和编码由项目模块完成。字体需要覆盖目标语言并实际检查回退。原背景中的按钮和原有底板按实例保留；新加实色矩形覆盖原文字不作为去字方案，见 [视觉政策](../../knowledge/rules/user-no-solid-text-panels-20261022.md)。

Codex 直接看图识字并使用宿主图像工具编辑图片；项目工作包提供规则和知识，回执绑定实际产物。ASR、TTS、分轨及必要的视频编辑使用 [统一模型分工](../contracts/model-routing.md)。识别结果、执行成功和内容验收是不同状态。

项目未内置 Photoshop、剪映的工程控制或自动目标语言口型同步。若新增编辑器集成，沿用源/结果身份、任务记录和实际审核合同，不以配置文件存在声称已连接。
