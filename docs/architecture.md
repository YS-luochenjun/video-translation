# 架构与职责

这个项目像一间制作工作室：Codex 看图识字、直接处理图片并决定怎么做，执行器操作媒体工具，运行目录保存现场，知识库保存以后还能用的经验。

## 谁负责什么

| 层 | 项目位置 | 责任 |
| --- | --- | --- |
| AI 主控入口 | `AGENTS.md`、`.agents/skills/` | 理解请求、翻译、选路、实际观察、判断返工 |
| 执行合同 | `agent/contracts/` | 质量、声音、字幕、知识和证据的共同约束 |
| 专项方法 | `agent/workflows/`、`knowledge/rules/` | 按内容条件选择步骤和检查方式 |
| 偏好与参数 | `config/profiles/`、`config/` | 有来源的偏好、质量阈值、预算、模型策略 |
| 调用入口 | `bin/`、`agent/integrations/` | CLI/MCP 适配及外部工具使用约定 |
| 实现 | `src/video_localizer/` | 媒体计算、任务账本、缓存、审核门禁、归档 |
| 独立知识 | `knowledge/` | 方法、同源参考、反例、证据和未启用候选 |
| 本机资产与状态 | `.runtime/`、`runs/`、`media/`、`outputs/`、`state/`、`work/` | 安装资产、现场、复用素材、账务及临时工作 |

目录按责任和生命周期划分，通常由同一个执行器读取，并不是每个目录各有一个 Agent。

## 一次任务的循环

```mermaid
flowchart LR
    U[视频与语言] --> A[AI 解析和定稿]
    A --> P[计划与预算预览]
    P --> E[本地工具或外部模型]
    E --> V[实际成片与证据]
    V --> R[AI 逐实例审查]
    R -->|缺陷且仍可返工| A
    R -->|quality 通过| D[独立交付包]
    R -->|达到返工边界| F[当前最佳完整译片及缺陷记录]
    D --> K[候选经验]
    F --> K
    K --> H[有来源的审查与启用]
    H --> A
```

`workflow.py` 承担计划、制作与质量的主要合同；`production.py`、`batches.py`、`work_packet.py` 负责阶段导航、恢复和语言编排。媒体、排版、修复、声音和视觉采证是可复用模块。执行成功只说明产生了结果；语义、残字、运动、音色和同步由真实观察决定。

## 实现边界

| 责任 | 主要模块 | 边界 |
| --- | --- | --- |
| 制作计划与执行 | `workflow.py`、`fast_delivery.py`、`production.py` | 冻结输入、调度媒体能力、绑定成品与审核 |
| Fireplay发现与接入 | `fireplay_monitor.py`、`fireplay.py` | 需求版本、聊天/预算、源文件和提交操作状态 |
| 素材参数与归属校验 | `fireplay_materials.py` | 对已解析的数据检查共享组、标签、设计师、命名和实际归属；不读写账本、不执行外部调用 |
| 平台发布与恢复 | `fireplay_publication.py`、`fireplay_youtube.py`、`fireplay_submission.py` | 发布可接受性、平台路由及持久提交进度分别处理 |
| 知识闭环 | `learning.py`、`curation.py`、`knowledge_review.py`、`knowledge_usage.py` | 记录、提纯、审查、使用反馈分开，当前状态由索引和不可变审查链产生 |
| 保全与维护 | `bundles.py`、`retention.py`、`maintenance.py` | 独立包核验、删除门禁、已登记临时缓存清理 |

Fireplay主模块保留原命令和锁定的提交状态机，素材规则集中在一个无I/O模块，避免归属写入与最终读回各维护一份判断。批次冻结后设计师身份/创作类型不能通过再次准备偷偷改变；相同身份的重复请求沿原操作和授权记录恢复。设计师DID命名和另有明确授权的用户ID写入是不同路线，均以实际平台读回为准，详见[提交流程](../agent/workflows/fireplay-intake.md)。

调整架构优先抽出已有清晰职责，不批量移动正在执行的run或改写旧账本。文档导航、模板格式、知识结论和本机回执各留一处；方法论解释长期流程，历史数字进入[维护历史](history.md)，动态状态由命令生成。

## 对外连接

宿主通过 CLI 或 stdio MCP 调用项目；项目通过受控适配器调用 KIE，凭据只由执行器读取。预算、任务号、未知状态和结果哈希落在项目账本中。Codex 的图像工作包绑定实际图片、规则、知识和产物；ASR 与分轨读取 `.runtime/` 安装资产，TTS、音频理解及视频编辑使用受控 KIE 入口。见 [模型分工](../agent/contracts/model-routing.md)。

每日知识提纯由项目 Hook 持有调度配置、提示词、输入和检查点，Codex CLI 是可替换的推理接口。Hook 形成候选；启用方法和改变偏好遵守项目知识合同。

## 复用与失效

源解析按完整源哈希和参数复用；制作缓存还核对定稿、参数、实现与工具版本。底片、声音、字幕和审核具有各自的适用范围。新语言重建稿件、声音、时间轴和检查；质量异议按实际哈希阻止旧版本继续生产。

独立证据包保留自身文件和 manifest，不要求旧 run 永久存在。现行方法与源限定参考分开检索，旧版本集中保留。详细生命周期见 [存储合同](../agent/contracts/storage.md)。

`fireplay_submission.coverage`用原片各自的目标语种对比已验证绑定，提供`delivery_coverage/submission_complete`；巡检直接消费同一结果，避免手工returned标志或某批次成功遮住漏交。`fireplay_retry.py`单独持有超时重传准备：只处理未入库的文件上传，保留旧尝试、以新超时证据有界恢复，不执行外部调用。媒体传输、素材归属、发布判断和需求完整性各有自己的校验。
