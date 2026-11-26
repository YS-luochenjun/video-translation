# KIE 授权与预算

总入口见 [kie](kie.md)。

## 授权、预算与凭据

执行前运行 `kie-authorization`。工作区返回 `automatic_use=true` 时，在既有范围、预算和模型限制内直接执行必要调用，不重复询问。主控用 `budget-open` 登记真实用户请求；所有语言、短片、run、批次和返工共用请求账本。新请求按 targets 中去重后的每个目标语言60 credits建共享总池，首次/新复用同价；旧账限额及未知占位不自动变更；新建run或拆分任务不能扩大额度。新请求任务名额按原时长/角色数有限规划，两轮返工不变，见 [批次与预算](../workflows/batch-production.md)。

Fireplay需求沿用[接入流程](../workflows/fireplay-intake.md)和config/fireplay-intake.json.kie中的持久用户同意。用户明确交办后，fireplay-start绑定本需求独立聊天、真实请求、语种、内容版本和账本，追加独立授权记录；不再重复询问KIE或必要媒体上传。P0优先不阻塞P1制作。仍按当前模型合同、原需求额度、未知计费与宿主审批执行。

三个付费入口共用预留与实际计费记录，直接绕过执行器的 KieClient 写入被阻断。逐run预算调整不能提高请求总上限。估算不构成供应商的硬账单上限；状态或计费未知时继续占位，结算超估算后停止新增调用。额度或授权范围确需扩大时再说明具体缺口并取得用户授权。

凭据仅由执行器读取。当前适配器提交使用 `/api/v1/jobs/createTask`，查询使用 `/api/v1/jobs/recordInfo`；上传 host 为 `kieai.redpandaai.co`。鉴权只发送给适配器允许的供应商 host，下载结果不携带 API key。新部署不继承当前拥有者的本机授权。

