# Agent 执行目录

项目的执行要求集中在这里。[AGENTS.md](../AGENTS.md) 是总入口，[制作技能](../.agents/skills/video-localization/SKILL.md) 与 [知识整理技能](../.agents/skills/knowledge-curation/SKILL.md) 负责按任务引导阅读。本目录本身不会创建另一个 Agent 或自动运行任务。

| 位置 | 职责 |
| --- | --- |
| `contracts/` | 各阶段共同遵守的模型、质量、声音、字幕、知识与存储规则 |
| `workflows/` | 具体任务的操作顺序、条件分支和完成标准 |
| `integrations/` | CLI/MCP、编辑工具和 KIE 的使用约定、失败处理 |
| `templates/` | 复制到任务中填写的输入格式与示例 |

## 按任务读取

| 当前任务 | 阅读入口 |
| --- | --- |
| 新视频、恢复任务或切换阶段 | [制作工作流](contracts/workflow.md)、[选路](workflows/video-localization.md)、[制作收口](workflows/production-completion.md) |
| 看图识字、翻译或编辑图片 | [模型与图像合同](contracts/model-routing.md)、[文字识别](workflows/ocr.md) |
| 处理声音和口播字幕 | [音频](contracts/audio.md)、[字幕同步](contracts/captions.md) |
| 修复文字、水印或遮挡 | [修复配方](workflows/repair-recipes.md)、[逐实例视觉审核](workflows/visual-review.md) |
| 多语言制作或付费调用 | [批次与预算](workflows/batch-production.md)、[KIE](integrations/kie.md) |
| 审核、比较与交付 | [质量要求](contracts/quality.md)、[遮蔽比较](contracts/validation.md) |
| 失败结案或用户否定旧版本 | [失败结案](workflows/local-production.md)、[质量反馈](workflows/quality-feedback.md) |
| 提纯经验、归档或清理 | [知识合同](contracts/knowledge.md)、[存储合同](contracts/storage.md)、[知识入口](../knowledge/README.md) |
| 填写规格或接入宿主工具 | [模板目录](templates/README.md)、[编辑能力](integrations/editors.md)、[MCP](integrations/mcp.md) |

模板中的示例值需替换为真实来源和观察；运行结果保存在任务目录。机器配置在 `config/`，有适用范围的可复用经验在 `knowledge/`。架构、安装和实现维护见 [开发者文档](../docs/README.md)。
