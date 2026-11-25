# Fireplay 固定提交与原操作恢复

逐原片、逐语种核验正式成片和真实回执。提交前按[全项提交规则](fireplay-complete-delivery-v3.md)记录最佳完整成片的质量事实和有限停止条件。

1. 入素材库、共享到真实对应需求组并请求 YouTube 自动上传，核对名称、标签、共享与需求绑定。新批次的名称和标签按[当前上传规则](../../agent/workflows/fireplay-intake.md#上传命名与标签)读取，唯一参数来源是 `config/fireplay-intake.json.publication.upload_metadata`，设计师与二创见[归属规则](fireplay-designer-attribution-v3.md)。
2. 部分语种就绪时使用 `partial:true`，只列当前可提交成片，保存 `pending_locales`。沿原 outbox 补交和核验，保留历史绑定。已入库或提交结果未知时按原素材 ID、实际成片哈希和响应恢复，优先核对原操作。
3. 全部原片及语言入库、共享、标签和绑定核验后，按需求状态流程关闭。YouTube 队列、限额、任务组和后续执行由平台处理，报告真实已请求状态。既有批次按冻结的身份继续恢复。
4. 成品和账本保全后记录经验。复用旧原片的限定观察需核对本次任务范围；历史需求的未识别意图通过真实正文和状态验证，既有聊天和预算按原绑定继续。

修订依据为 evidence:previous、evidence:upload_policy。历史素材名和旧发布回执随原来源记录。
