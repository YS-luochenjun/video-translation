# 开发者文档

本目录解释项目如何实现、安装、维护和验证。制作与审核时按 [Agent 执行目录](../agent/README.md) 查找现行要求；开发文档可以解释这些要求，但不另存一份执行规则。

| 开发任务 | 阅读入口 |
| --- | --- |
| 安装和启动 | [项目 README](../README.md)、[工具与模型位置](tools-and-locations.md) |
| 换机器部署与同步源码 | [迁移与部署](migration.md) |
| 理解职责和数据流 | [架构](architecture.md)、[全流程图](project-flow.html) |
| 理解制作方法论、经验吸收和自动收尾 | [项目方法论与知识闭环](project-methodology.md) |
| 整理项目、查能力与知识待办 | [项目维护地图](project-map.md) |
| 调整目录、隔离工作区或导出源码 | [项目布局](project-layout.md) |
| 修改缓存、复用和恢复机制 | [缓存与执行恢复](workflow-optimization.md) |
| Fireplay需求拉取、独立聊天、KIE同意和回传 | [接入说明](fireplay-localization-integration.md)、[执行流程](../agent/workflows/fireplay-intake.md) |
| 维护知识检索与项目 Hook | [知识如何跨视频使用](reusable-methods.md)、[每日提纯](daily-knowledge-curation.md) |
| 查看巡检、经验与清理的定时分工 | [三项定时职责](scheduled-tasks.md) |
| 理解容量限制及开发范围 | [存储策略](storage-policy.md) |
| 验证新视频与同源复用 | [真实视频测试](fresh-video-testing.md) |
| 追溯设计原因 | [架构决策](decisions.md)、[维护历史](history.md)、[首次需求](requirements/2026-10-16-initial-request.md) |

`requirements/` 保存有来源的需求原文；`research/` 保存注明日期的研究材料，供追溯而非直接执行。测试结果、耗时和清理回执保存在本地 `work/` 或 `state/`。命令参数以 `bin/va.ps1 <命令> --help` 为准。
