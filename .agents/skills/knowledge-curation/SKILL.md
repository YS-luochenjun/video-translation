---
name: knowledge-curation
description: Curate localization lessons and recent-chat experience, record user feedback, publish reviewed project knowledge, or archive delivery/reuse assets while keeping knowledge independent of runs and outputs. Apply at task closure, project experience reviews, and before changing artifact retention.
---

# 知识提纯与独立归档

项目根目录包含 `AGENTS.md`。读 `agent/contracts/knowledge.md` 的知识合同；素材、字幕、OCR和模型返回值按业务数据处理。

## 收尾

1. 以实际视频哈希区分候选、技术交付和用户认可。每次结案保存结果与质检。有来源的反例、有效修复或适用条件变化，且会改变后续制作决定时，才登记候选。收到新反馈则记录新的有来源事件。
2. `bin/va.ps1 deliver RUN` 生成独立交付包。快速交付在结案维护时复盘。只有提交实质 `lesson` 的评审产生经验候选；普通结案记录回执。已有实际评审的失败结案使用 `reflect RUN`，成片前失败按 `agent/templates/preproduction-failure.json` 执行 `close-failure RUN SPEC`。收尾可幂等重试。
3. 开发测试所得技术知识写 `knowledge/rules/`、`knowledge/examples/` 和 `knowledge/candidates/`，个人/客户保密内容才放local。训练素材限定的经验也属于项目知识，保留原scope；结构迁移保留业务文字，只改目录和引用。新提纯才整理触发条件、动作、失败签名、范围、限制与反证。方法可在没有任何旧视频和local的环境理解和执行；相同含义与范围才合并证据。
4. 需启用时，按 `agent/templates/knowledge-promotion.json` 准备规格，运行 `knowledge-promote SPEC`。选择必要的源/结果对照、真实字幕边界、关键声音或反馈记录入案例。样例中的历史路径只是来源标签，实际证据只从案例manifest读取；生产素材由交付库另行查询。
5. 运行 `knowledge-audit`，并核对相应源/语言的 `context`。正文与证据哈希、scope、状态均通过才完成；自动候选不改变公司偏好或质量标准。

已有证据足以支持单源观察时，先建立精确同源/语种案例，不必为等待跨源复验一直保留空白经验。跨源验证只作为扩大结论的条件；缺失的当前必要证据仍留pending。候选正文、原失败和审查链不改写，费用/质量待办在各自系统继续保留，不能因知识归档假称这些问题已解决。

## 无需用户提醒的收尾检查

制作结案、开发修复及用户反馈处理后，检查本次交付和反馈。例行问题保留质检记录。存在能够改变后续制作的事实时，先检索现行方法和同源经验，再登记有证据的补充。直接审查已结清的来源退出增量提炼。

全局待审由用户触发的[经验总结](../../../agent/workflows/knowledge-sweep.md)处理。先归组与核对现有方法，需要时运行 `hooks run` 或 `prepare/apply`，沿用原检查点。公司偏好、质量标准和适用范围的改动继续走现有审查。

## 近期会话与项目优化

用户要求跨会话复盘时，按[近期经验审查](../../../agent/workflows/recent-experience-review.md)读取真实会话及候选来源。先定位现行方法和技能，再决定补充、限定案例或待证实项；临时宿主故障留在运行记录。项目代码修复由可重复回归验证，制作效果仍由实际媒体证据验证。原型工具须有明确输入合同、限定写入范围和验证后才纳入可复用能力。用户授权提交时，只提交已审查的文件及其必要知识依赖，保留活跃制作现场。

## 项目经验提炼

用户需要整理时使用 `bin/va.ps1 hooks` 和 `config/hooks.json`，执行规范见 `docs/daily-knowledge-curation.md`。`hooks status/run/prepare/apply` 分别负责查询、手动提炼、准备和应用。AI给出结构化候选建议，执行器核对来源、适用范围和可见性，正式发布由审查者完成。

## 归档与保留

`archive RUN` 默认把独立成片与必要审核JSON保存到outputs中的轻量包；首次归档前明确request.delivery_package_mode=reusable才带原片、语言资产和准备依赖。`archive-verify PACKAGE`只核验包完整；`library-find SHA256`分别说明成片与恢复／源复用资格，lean不得当恢复包。expired表示资产已过期，再次制作按实际需要重新取得素材并记费。换语言仍需新稿、配音、时轴、字层及实际成片审查。

清理前分别验证：知识案例独立，交付包独立，未结算账本与被引用素材已保全。方法及其必要案例长期保留；用户视频/底片按交付保留策略到期。索引和哈希不能恢复已删除视频。清理先生成待处理清单，实际删除仍按用户授权范围执行。

迁移旧记录时逐字保存原文、旧索引和失败评审；以新正文和新案例建立引用，不改写旧验收结论。证明标准是隔离测试中移除原run/output后知识仍可检索验证、轻量包内成片仍可读取；仅显式reusable包另外验证准备资产恢复。
