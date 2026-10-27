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
