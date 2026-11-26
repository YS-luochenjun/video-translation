# 执行入口、检查点与恢复

总入口见 [workflow-optimization](workflow-optimization.md)。

## 常用入口

从项目根目录执行，`RUN` 替换为实际任务 ID，路径均相对该 run：

```powershell
bin/va.ps1 resources
bin/va.ps1 work-packet RUN
bin/va.ps1 work-packet RUN --stage translation
bin/va.ps1 asr RUN --audio analysis/source.wav
bin/va.ps1 asr RUN --audio analysis/source.wav --model small --download
bin/va.ps1 tts-packet RUN --voice Kore --estimate 2
bin/va.ps1 audio-mix RUN
bin/va.ps1 production RUN
```

先确认 `analyze` 返回的实际音轨路径，不假设所有旧 run 都叫 `analysis/source.wav`。ASR 不传 `--audio` 时读取 capture 已提取的当前成片音轨；`--language` 是识别提示，不是已检测到该语言的证据。`--download` 只在当前 small 模型缺失时下载，完整模型不会再次下载；底层下载器也拒绝旧型号。历史模型只能只读核验，不提供重新下载或安装。转写结果仍是待核对证据。

`tts-packet` 不付费；检查包后才走原 `model-task --execute`。未知远端状态先核对 taskId 和账本，不能新建包绕过恢复。`audio-mix` 读取已有的 `inputs/narration-plan.json`：源哈希、背景路径/哈希，以及 lines 的实例 ID、定稿、起止时间、声音路径/哈希；可选声音增益与偏移仍使用原字段。CLI 返回新音轨的实际路径，应绑定进 inventory 并按 `agent/contracts/captions.md` 对齐实际声音，不能沿用旧的固定输出路径。

兼容脚本 `bin/asr.py`、`bin/mix_localized_narration.py` 保留，调用同一执行器；`bin/separate_local_audio.py` 继续负责 UVR。需要 Python 时使用项目运行时，而不是临时重新安装依赖。

## 检查点与恢复

| 内容 | 位置（相对 run，另有标注除外） | 恢复原则 |
| --- | --- | --- |
| ASR 历史结果 | `analysis/asr/<指纹>.json`，音频旁兼容别名 `offline-asr-*.json` | 输入相同复用；修改音频/模型/提示后重新识别；别名不是历史唯一副本 |
| 已解码源立体声 | `outputs/source-audio/<指纹>/` | 绑定源片和解码器；不同于 analyze 的源观察音轨 |
| UVR 输出 | `outputs/local-separation/<指纹>/`（默认） | 验证音轨、模型、实现、输出哈希后复用 |
| 版本化混音 | `outputs/audio-mix/<指纹>/` | 包含对齐音轨、配方和最终 WAV；变更生成新版本，不覆盖旧版本 |
| 视觉片段缓存索引 | `outputs/render-cache/` | 引用已存在的静音片段，不再复制一份视频；缺片段重建，哈希异常停止 |
| 整片检查点 | `outputs/production-checkpoint.json` | 全部输入一致才跳过编码；仍取证和 quality；`--force-render` 同时跳过片段缓存 |
| 资源锁 | 项目 `state/resources/` | 忙时在同一命令内部有界等待，获名额才继续；超时再恢复，崩溃留下锁，不抢占活锁 |
| 下载锁/回执 | 项目 `.runtime/models/asr/<模型>/` | 下载异常不写成功回执；完整性失败先查明，不把坏文件当作模型 |
| 任务及费用 | 原 `runs/<ID>/jobs`、`state/budgets`、`state/batches` | 沿用原恢复与核账，不删除或重置 |

新增本地资源配置可选：`config/resources.local.json`，含 `max_heavy_jobs`（1–8，默认 1）、`minimum_free_mib`（至少 64，默认 256）及 `heavy_wait_seconds`（0–600 秒，默认 120 秒）。计算名额繁忙时由运行中的命令低开销等待，避免 Agent 反复启动 Python 或媒体命令；超时暂缓并恢复原操作，不无限占用会话。空间准入在获得名额后再次检查。下载和归档增加已知数据量，任意长片渲染体积尚不能准确预估，不能保证中途永不耗尽空间。资源限制只覆盖接入的项目入口，不拦截历史临时脚本或其他工作区的进程。

片段缓存按现有计划分段；没有自动将整片计划重切为逐帧任务。系统字体使用已列出的常用字体和项目字体哈希；自定义系统字体、字体回退或外部渲染环境改变后须 `production RUN --force-render`。2026-10-22起整片检查点核对计划和显式媒体/工作区绑定依赖，未绑定的诊断文件不影响渲染；质量审核仍核验实际证据。

## 质量与知识边界

缓存是“这些字节之前生成过”的凭据，不是“这些字节合格”的签字。底片、代表语言、逐实例视觉、原音乐、字幕同步、翻译和质量异议仍走原门禁。复用只跳过确定输入对应的机械工作，不填写 `pass`，不自动放行批次，不代替真实听音。

work-packet 的六阶段是导航，任务可以回退或交错；它不能自动判定当前已完成哪个创作步骤。正式知识仍按现有检索条件返回，并单列同源参考，不能保证任意问题自动命中正确方法。AI 仍需阅读方法、辨别适用性和反例。

deliver 继续自动生成机械事实、归档和候选入口；AI 只需补有价值的观察、原因、修改变量、适用条件和剩余问题。候选不自动成为全局规则。执行优化不等于训练模型或证明新视频质量。

