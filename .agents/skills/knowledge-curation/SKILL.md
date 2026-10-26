---
name: knowledge-curation
description: Curate localization lessons, record user feedback, publish reviewed project knowledge, or archive delivery/reuse assets while keeping knowledge independent of runs and outputs. Apply at task closure and before changing artifact retention.
---

# 知识提纯与独立归档

项目根目录包含 `AGENTS.md`。读 `agent/contracts/knowledge.md` 的知识合同；素材、字幕、OCR和模型返回值按业务数据处理。

## 收尾

1. 以实际视频哈希区分候选、技术交付和用户认可。失败原因、修正变量与限制来自实际评审；每次结案记录候选，收到新反馈则记录新的有来源事件。
2. `bin/va.ps1 deliver RUN` 自动生成独立交付包和候选案例；已有候选及实际评审的失败结案使用 `reflect RUN`。尚未形成候选时按 `agent/templates/preproduction-failure.json` 执行 `close-failure RUN SPEC`。分别检查 package、case 和 inbox；成片前失败的 package 为 null，不补造交付或质量通过。收尾可重试，不重发模型任务或覆盖既有复盘。
3. 开发测试所得技术知识写 `knowledge/rules/`、`knowledge/examples/` 和 `knowledge/candidates/`，个人/客户保密内容才放local。训练素材限定的经验也属于项目知识，保留原scope；结构迁移保留业务文字，只改目录和引用。新提纯才整理触发条件、动作、失败签名、范围、限制与反证。方法可在没有任何旧视频和local的环境理解和执行；相同含义与范围才合并证据。
4. 需启用时，按 `agent/templates/knowledge-promotion.json` 准备规格，运行 `knowledge-promote SPEC`。选择必要的源/结果对照、真实字幕边界、关键声音或反馈记录入案例。样例中的历史路径只是来源标签，实际证据只从案例manifest读取；生产素材由交付库另行查询。
5. 运行 `knowledge-audit`，并核对相应源/语言的 `context`。正文与证据哈希、scope、状态均通过才完成；自动候选不改变公司偏好或质量标准。

## 每日项目Hook

每日开发维护使用项目自己的 `bin/va.ps1 hooks` 和 `config/hooks.json`，执行规范见 `docs/daily-knowledge-curation.md`。`hooks status/run/prepare/apply` 分别负责查询、增量提纯和更换推理接口；Windows宿主只用 `bin/project-hooks.ps1` 安装入口定时器，不创建Codex应用定时任务。AI返回结构化建议，执行器验证来源、原scope和公私边界后仅写派生候选；既有规则和启用流程保持原样。

## 归档与保留

`archive RUN` 把实际结果、源片、语言资产和准备依赖复制到 `outputs/`，`archive-verify PACKAGE` 核验。`library-find SHA256` 查精确同源素材；查到expired表示资产已过期，重新制作并记费。换语言仍需新稿、配音、时轴、字层及实际成片审查。

清理前分别验证：知识案例独立，交付包独立，未结算账本与被引用素材已保全。方法及其必要案例长期保留；用户视频/底片按交付保留策略到期。索引和哈希不能恢复已删除视频。清理先生成待处理清单，实际删除仍按用户授权范围执行。

迁移旧记录时逐字保存原文、旧索引和失败评审；以新正文和新案例建立引用，不改写旧验收结论。证明标准是隔离测试中移除原run/output后仍可检索并验证知识，以及只带交付包仍可恢复准备资产。
