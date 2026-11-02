# 第一期需求台账上报

来源：2026-10-27 用户确认在现有工作台落地第一期，关联已有需求和任务。台账不改变制作、质量、付费或外部提交授权。每个原视频的负责聊天沿用现有真实登记；读取聊天状态不算 Agent 心跳。

`work-packet` 的 `ledger_tracking.bindings` 返回已关联的 requirement_id、video_id、locale。由当前 Agent 在真实执行时上报，不把代理进程存活当作 Agent 工作。没有绑定时先 `ledger sync`；仍无明确归属则按实际源哈希和语言核对后 `ledger link`，不猜归属。

所有写操作使用 `bin/va.py ledger ACTION --spec work/台账规格.json`，Windows 可以用 `bin/va.ps1 ledger ...`。规格示例：

```json
{
  "operation_id": "为本次操作生成的稳定唯一ID",
  "data": {
    "requirement_id": "使用实际绑定ID",
    "video_id": "使用实际绑定video_id",
    "owner": "当前Agent或聊天标识",
    "session": "当前实际执行会话的稳定ID",
    "stage": "解析",
    "reason": "本次真实开始执行的依据"
  }
}
```

- 开始工作用 `claim`。按 video_id 认领，多原视频可由不同会话并行；整条需求认领与视频认领不能重叠。旧租约过期后，先恢复已有模型/提交回执，带真实原因交接，不能直接重做。
- 阶段变化用 `stage`；实际长时间工作时用 `heartbeat`，不以后台扫描或无实质事件定时续命。执行器单独每60秒报告实际阶段存活；两类状态分开展示。
- 等待时用 `block`，kind 为 user/model/resource/platform/unknown；reason 写当前缺口和下一步。恢复用 `resume`。仅因页面无新记录不判为失败。
- 信息确实齐备用 `ready`，保留首次齐备时间。
- `eta` 保存带时区的 lower_at/upper_at、reason、basis 和 assumptions。首次和调整均追加；新增范围有独立预测。规则估算是未校准的剩余工作估计，不是承诺。人工/Agent预测不会被自动规则覆盖；事后补录的预测不纳入准时率。
- 停止负责时用 `release`，保留本轮所有事件。释放不代表完成或质量通过。

`ledger register` 供非 Fireplay 的明确用户请求登记，data 包含 code、title、reason、received_at，以及 videos 列表（每项 source_sha256、targets、可选 title）。targets 使用项目规范化语言；登记不自动建制作run、开预算或调用模型。已有范围变化保留原记录并审查修订。

重复操作重用同一 operation_id 和相同输入。未知结果先查 `ledger detail --id ID`，不要换ID盲目重复；同ID不同内容会拒绝。UI 同时检查记录版本。

状态数据库和事件 inbox 属于 `state/ledger/`；不是临时缓存，不随run清理。`ledger backup` 使用 SQLite 一致性备份；完整恢复仍须携带交付库、质量异议和预算等原始证据。

## 后续真实需求的耗时采集

现有工作台按[Benchmark口径](../../docs/benchmark.md)自动积累后续新需求；首次同步建立永久排除基线，不补做历史需求。每次制作的开始、阶段、实际整项等待/恢复和停止均按上述动作报告，无需等用户提醒。已有执行器计时自动关联，但不能替代 Agent 活动；没有记录的间隔保留未知。源清单的真实 content_features 和 analyze 时长用于分组，不为统计填猜测。

首轮以当前范围全部原片/语种的首次完整输出为界，之前的有界试验属于首轮，之后属于返工。新增范围不覆盖旧样本；开始续作仍恢复原账本、任务和授权。若只有一个语言等待而其他语言仍推进，不用整项 block 冒充整项停工。费用、质量和提交证据各自保留，完整输出不等于质量/验收通过。命令行 `ledger benchmark` 只读查看，`ledger sync` 才采集本地落盘证据。

新需求登记后及全部语种交付/本轮停止前各运行一次 `ledger sync`，确保未打开工作台时仍能采集真实证据与冻结首轮；这只是同步本地记录，不启动制作或回传。工作台每15秒采集是补充，不代替制作聊天的开始/结束上报。
