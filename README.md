# 广告视频本地化 Agent

输入广告视频与目标语言，由 Codex 看图识字、翻译、处理图片并审查结果；项目中的 Python 执行器负责媒体操作、必要的专用模型调用、预算、证据和知识留存。输出是经逐实例检查的视频、实际审核结论和可复查记录。

默认尽力制作并输出完整翻译视频：评分决定有界返工，预算/尝试结束后用 `compose-best` 和 `finalize` 交付当前最佳版本，明确标记瑕疵，不因未达质量分数而只给失败报告。质量通过、已输出有瑕疵和用户验收分别记录。见 [最终输出规则](agent/workflows/always-output.md) 与 [2026-10-23 版本说明](docs/releases/2026-10-23-codex-led.md)。

项目通过 CLI 或 stdio MCP 配合 AI 宿主使用。当前没有普通用户上传网站或无人值守制作服务。模型分工以 [模型路由](agent/contracts/model-routing.md) 和 [可执行配置](config/model-routing.json) 为准。

## 安装与检查

当前安装入口面向 Windows x64。准备 `uv`、FFmpeg 和 ffprobe，并加入 PATH；在项目根目录执行：

```powershell
bin/setup.ps1
bin/va.ps1 doctor
bin/va.ps1 check
.venv/Scripts/python.exe bin/check_repository.py
```

安装资产位于 `.runtime/`，Python 虚拟环境为 `.venv/`。依赖版本见 [bin/requirements/](bin/requirements)，本地模型只安装 Whisper small（含 VAD 依赖）与 UVR Inst HQ3；模型选择由 [模型路由](config/model-routing.json) 约束，UVR 来源和校验和见 [本地模型注册表](config/local-models.json)。首次安装需要联网；已有资产校验后复用。可用 `-FfmpegBin <目录>` 指定媒体工具来源，迁移项目位置后重新运行 setup。

已有项目 Python 时，可运行 `.venv/Scripts/python.exe bin/install_dependencies.py --plan` 查看安装清单，不下载或安装。安装入口不提供旧模型选择或声音包安装。图片依赖统一安装在 `.runtime/deps/vision/`，不再从旧 OCR 目录加载；Gemini 音频分析、Gemini TTS 和 Wan 视频编辑使用远端 API，不下载权重。历史模型文件与声音产物不自动删除，但缺失旧资产时不会重新下载安装。

字体从本机导入 `assets/fonts/`；缺少目标语言字体时先安装再运行 setup。模型和字体二进制不随源码分发。AI 宿主需要能读取文件、查看图片、使用图像编辑工具和执行本地命令。

需要 KIE 时按 [.env.example](.env.example) 设置本机凭据，并运行 `bin/va.ps1 kie-authorization` 核对授权。新部署不继承本机拥有者的付费授权；doctor 只验证本地运行条件。

换机器安装见 [迁移与部署](docs/migration.md)，包含本项目远程仓库、首次安装、后续更新和历史任务的单独迁移方式。

## 开始制作

在本目录打开 AI 宿主，提供视频并提出要求，例如：

> 帮我把这个视频翻译成日语。

提供实际视频文件或可访问的视频链接，以及目标语言即可。Codex 会读取项目规则、知识和现有素材，自主选择方法，完成制作与审核；不需要用户指定模型或逐条执行命令。品牌、地区、语气等有特殊要求时一并说明。需要在本项目或其已安装的源码副本中发起任务，并具备前述宿主工具及所需的服务授权。

Fireplay需求可直接给编号，或指定组/日期等读取范围，例如“拉取这些需求并翻译，P0优先”。按[Fireplay接入流程](agent/workflows/fireplay-intake.md)自动读取每条需求、下载全部原片，并建立或复用每需求一个聊天和独立账本。P0在资源冲突时优先，P1同时继续制作。当前拥有者的KIE同意已持久保存到[接入配置](config/fireplay-intake.json)，明确交办的需求在既有模型与本需求额度内不再重复询问；新工作区仍需自己的本地授权。审核后按固定指令入库、共享需求组、请求YouTube自动上传、打语言/产品tag并绑定需求。用户已授权每小时由当前主控聊天定时检查新翻译需求，见[监控流程](agent/workflows/fireplay-monitor.md)；全部组按实际翻译意图筛选，负责人仅作提示。有限预算/返工内做到最好的完整译片可带普通不合格自动回传；大面积撕裂、无法观看、漏译或缺必需配音等严重问题仍阻断，内部质量记录保留。

这个入口支持直接开始工作，不保证任意素材一次成功。缺少必要素材或宿主能力、专用模型失败、现有预算不足，或质量审查未通过时，明确报告缺口并在允许范围内返工。达到边界后按最终输出规则给出当前最佳完整视频并标明瑕疵；质量通过仍须实际审核，外部提交另核对用户授权与平台回执。

[AGENTS.md](AGENTS.md) 是执行入口，[制作工作流](agent/contracts/workflow.md) 描述解析、定稿、制作、审查、返工和交付。目标语言支持别名，可用 `bin/va.ps1 language-resolve jp` 查询。每种语言独立定稿、配音、排版和审核，同源资产经核验后复用。

交付入口是本机 `outputs/index.html`，运行 `bin/va.ps1 delivery-index` 刷新。未通过的结果保留缺陷与失败案例，执行成功不会自动变为交付通过。

## 目录导航

| 位置 | 保存什么 |
| --- | --- |
| `bin/`、`src/`、`tests/` | 命令入口、执行器实现和回归测试 |
| `workbench/` | 本机只读工作台，启动方式见 [工作台说明](workbench/README.md) |
| `config/` | 模型、预算、质量等配置；`profiles/` 保存偏好档案，`workflows/` 保存流程配置，`hooks/` 保存项目提纯提示词 |
| `agent/` | 执行依据：`contracts/` 共同规则、`workflows/` 操作步骤、`integrations/` 工具约定、`templates/` 任务填写格式 |
| `docs/` | 开发者说明：架构、安装维护、实现原理、测试方法及设计历史 |
| `.agents/skills/` | AI 执行制作和知识整理时按需读取的技能 |
| `knowledge/` | 可复用方法、同源案例、独立证据、候选和历史版本 |
| `runs/`、`media/`、`outputs/` | 本机任务现场、源解析库、独立交付库 |
| `state/`、`work/` | 本机预算与恢复状态、临时工作与缓存；清理规则不同 |
| `.runtime/`、`.venv/`、`assets/fonts/` | 本机工具、模型、依赖和字体 |

`AGENTS.md` 和 `.agents/skills/` 是宿主发现执行要求的入口，按任务指向 `agent/`，规则正文只维护一份。模板是填写格式，配置是执行参数，知识是有适用范围的经验；运行数据保存每次执行的实际内容。详细说明见 [项目布局](docs/project-layout.md) 与 [存储合同](agent/contracts/storage.md)。

- [Agent 执行目录](agent/README.md)：按阶段查找规则、操作步骤和模板。
- [开发者文档](docs/README.md)：安装维护、实现说明和历史追溯。
- [项目维护地图](docs/project-map.md)：当前能力、知识待办和实测来源的统一入口。
- [项目方法论与知识闭环](docs/project-methodology.md)：制作判断链、经验吸收状态和自动沉淀机制。
- [三项定时职责](docs/scheduled-tasks.md)：新需求巡检、经验总结、存储整理分别调度。
- [全流程图](docs/project-flow.html)：阶段、分支、命令和离线来源。
- [架构与职责](docs/architecture.md)：Codex、执行器及外部服务的分工。
- [模板目录](agent/templates/README.md)：现行表单及历史兼容示例。
- [知识入口](knowledge/README.md)：现行方法与来源、候选、历史的关系。

## 维护与验证

```powershell
bin/va.ps1 check
bin/va.ps1 knowledge-audit
.venv/Scripts/python.exe bin/knowledge_maintenance.py check
.venv/Scripts/python.exe bin/check_repository.py
```

修改流程图引用的文件或命令后，运行 `.venv/Scripts/python.exe bin/sync_flow_reference.py` 刷新离线来源，再执行仓库检查。更改媒体链路时，额外在隔离工作区运行 `demo --id <新ID>`。合成测试、同一 Agent 自审和真实视频验收分别报告；未进行 Linux/服务器部署验证。

本 README 维护安装、使用和导航。命令参数以 `bin/va.ps1 <命令> --help` 为准，细节放入对应专题文档；修改目录、入口或配置时同步更新导航和验证。一次性测试、清理和迁移回执保存到 `work/` 或 `state/`。

知识证据按完全相同的内容哈希共享存储，原案例 manifest 和历史判断保持不变。迁移知识时连同 `knowledge/examples/_objects/` 与存储索引一起复制；旧证据路径的解析和候选状态说明见 [知识入口](knowledge/README.md)。候选索引记录部分采纳和重复文字分组，不自动启用候选；手动新增候选或采纳表后运行 `.venv/Scripts/python.exe bin/knowledge_maintenance.py reindex`。

候选学习流程为：复盘记录 → Hook 提纯并提出采纳目标 → `knowledge-queue` 审查 → 发布/修订正式方法或保留明确待办 → 制作按需召回 → `knowledge-use` 记录实际效果并返回修订队列。制作包中的 `knowledge_advisories` 最多3条，是有来源和范围的待验证观察；正式方法保持独立，检索命中不等于实际使用或验证通过。

`knowledge-review` 记录采纳部分、保留部分和目标版本。完全处理完的原始候选可用 `candidate-archive` 预览并归档到历史，从候选目录和默认队列退出；部分采纳不能直接整条删除。使用示例和边界见 [知识合同](agent/contracts/knowledge.md)。

## 源码导出

```powershell
# 目标目录必须不存在；导出不包含 Git 历史
bin/va.ps1 workspace-export dist/source
bin/va.ps1 workspace-verify dist/source
```

源码包含代码、公共配置、文档、模板和独立项目知识。凭据、本机授权、宿主设置、私有知识、生产视频、账本、模型和字体保留在本机。精选知识证据随自身 manifest 保留来源和适用范围。

进入导出目录后按上述安装步骤准备运行环境。发布边界见 [项目布局](docs/project-layout.md)；仓库尚未声明开源许可证，源码可上传不代表已授予第三方再分发权。

每次运行的增量整理由 `config/maintenance.json` 和 `maintain RUN --close` 管理；缓存登记后自动核验清理，制作现场保全后退出，正式 outputs 继续用于复用。详见 [存储合同](agent/contracts/storage.md)。
