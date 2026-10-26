# 目录与干净导出

源码、安装资产和任务数据分开保留。清空运行数据不会卸载模型；导出源码不会携带旧视频或本机授权。

| 目录 | 内容 | 进入源码 |
| --- | --- | --- |
| `bin/`、`src/`、`tests/` | 正式入口、实现、测试 | 是 |
| `workbench/` | 本机只读工作台及其测试、静态资源 | 是 |
| `.agents/skills/` | AI 制作和知识整理的操作入口 | 是 |
| `config/` | 公共参数、`profiles/` 偏好档案、`workflows/` 流程配置、`hooks/` 提示词 | 是，递归收集并排除 `*.local.json` |
| `agent/` | `contracts/` 执行规则、`workflows/` 操作步骤、`integrations/` 工具约定、`templates/` 填写格式 | 是 |
| `docs/` | 架构、安装维护、实现原理、开发测试和历史说明 | 是，排除一次性 `verification/` 报告 |
| `knowledge/` | 方法、源参考、独立证据、候选和历史版本 | 是，排除 `local/` |
| `.runtime/`、`.venv/`、`assets/fonts/` | 本机工具、依赖、模型和字体 | 否，由安装流程准备 |
| `runs/` | 本次现场、模型任务、候选和评审 | 否 |
| `media/` | 原片、源帧、音轨和中性观察快照 | 否 |
| 根 `outputs/` | 可离开 run 恢复的交付/复用包 | 否 |
| `state/` | 预算、批次、锁、保全、清理和维护回执 | 否 |
| `work/` | 可重建缓存、开发实验、测试和临时导出 | 否 |
| `.env`、`.codex/`、`*.local.json` | 凭据、宿主配置和本机授权 | 否 |
| `dist/`、`.archive/` | 明确生成的分发包或本地归档 | 否 |

`runs/<任务>/outputs/` 是现场的一部分；根 `outputs/` 是独立交付库。`media/` 保存源解析，不是已验收的去字底片。它们可能保留相同字节来满足各自恢复合同，不能只按重复哈希删除。

## 生成源码副本

```powershell
bin/va.ps1 workspace-export dist/source
bin/va.ps1 workspace-verify dist/source
```

目标必须不存在。导出使用代码中的公开目录清单，不复制整棵工作目录；保留原始字节，并生成 `fresh-workspace.json` 供核验。`knowledge/history/` 随源码保留，确保替代链可追溯。本机授权、私有证据、生产视频、Git 历史、模型和字体不会导出。

副本安装方式见 [README](../README.md)。`workspace-init` 复制公共配置、操作文档、技能和知识，执行器仍在代码目录；配合 `VIDEO_LOCALIZER_WORKSPACE` 可隔离工作区。`workspace-export` 包含可独立安装的完整源码。

## 目录迁移与旧记录

2026-10-22 按职责统一布局：原 `core`、`systems`、`templates` 与执行步骤集中在 `agent/`；`designers` 和 Hook 提示词集中在 `config/`；流程的机器配置保存在 `config/workflows/`。`docs/` 专注开发说明。整理过程曾把执行依据放入 `docs/`，随后按项目拥有者要求分离，旧目录不保留重复副本。

当前操作说明、代码和模板使用新路径。历史需求、实验原文及案例证据保留原始来源标签；现行知识中的合同路径变更有 [首轮迁移记录](../knowledge/curation/layout-migration-20261022.json) 与 [Agent 目录迁移记录](../knowledge/curation/agent-layout-20261022.json)，原文和哈希均保留，没有改变规则含义或验收结论。

已有 run、交付包和账本不批量改写。旧计划或 Codex 工作包若因档案/合同路径及哈希变化而失效，续作时用 `work-packet` 核对缺口，重新生成计划或工作包，并按门禁重新绑定实际检查；不能修改旧审核哈希让它继续通过。

## 发布前核查

```powershell
.venv/Scripts/python.exe bin/check_repository.py
bin/va.ps1 knowledge-audit
bin/va.ps1 check
```

仓库检查核验现行文档链接、知识索引、历史正文哈希和发布边界；知识审计核验现行正文及证据。隔离副本中执行 `demo --id smoke-001` 可检查合成媒体链路，需要真实观察的字段继续 pending。

流程图保留离线来源快照。修改被引用的合同、实现或命令后，运行 `.venv/Scripts/python.exe bin/sync_flow_reference.py` 刷新快照与 CLI 帮助，再运行仓库检查；`--check` 只核对快照。流程解释本身仍需人工/Agent 审查，不由同步脚本推断。

导出不带 Git 历史；直接发布现有 Git 仓库时还应核查历史。仓库尚未声明开源许可证，源码可上传不等于已授予第三方再分发权。模型和字体遵守各自来源许可。

## 本机清理

运行产物按 [存储合同](../agent/contracts/storage.md) 保全、预览和删除。`work/` 不承载唯一正式能力或唯一案例证据：有价值的脚本先提入 `src/`/`bin/`，参数进模板，观察进知识，再清理临时副本。没有活跃进程、恢复依赖或唯一证据时，普通临时内容可删，缓存按需重建。

当次清理结果以本地回执和目录检查为准，长期文档不声明运行目录“永远为空”。实际账单未核清时保留记录和预算占位。
