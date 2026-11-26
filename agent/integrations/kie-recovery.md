# KIE 失败与恢复

总入口见 [kie](kie.md)。

## 失败、恢复与验证边界

任务指纹绑定计划、附件内容和参数。同指纹重复提交返回原任务；断线或建任务结果不明记为 `ambiguous`，禁止盲目重复 POST。先核对供应商日志的时间、模型、参数和 taskId，再恢复对应本地任务并记录依据。处理遗留锁前确认没有活跃执行。`reused_model_job` 只复用完整请求和素材哈希均相同的成功结果。

HTTP 200 仍可能包装业务错误。供应商业务码、`failCode` 与 `failMsg` 原样脱敏留档；连接/鉴权、上传、建任务、模型执行和内容质量分别报告。服务端5xx业务错误可能已计费，保留未知状态。只有供应商已确认终态失败、存在taskId且 `creditsConsumed=0`，才可按实际错误使用 `--retry-failed --execute`。`model-task` 的临时失败最多追加四次重试，仍占用原请求额度和任务名额。

音频上传阶段的连接失败可显式 `audio-analyze ... --retry-upload --execute`，最多两轮。执行器保存旧尝试快照，并由总账确认尚无付费模型 dispatch 后复用原预留；不重复预留，也不允许借此重发结果不明的模型请求。

带附件的 `model-task RUN PACKET --retry-upload --execute` 同样只恢复已失败且没有taskId、总账没有模型dispatch的原任务，适用于余额查询或附件上传时的失败。保留原指纹、原占位及旧尝试快照，最多两轮；已有taskId或ambiguous任务仅返回原记录。总账已有dispatch但缺taskId时拒绝恢复，继续核查原请求，不以此重发付费POST。

轮询每次最多45秒。成功后下载并检查实际媒体；计费缺失继续占位，不能把账户余额变化单独当作某笔任务的费用。`doctor` 仅检查本机状态，`doctor --online` 额外证明鉴权和余额读取；两者都不证明这次视频模型生成或内容验收成功。真实结果以任务账本、媒体哈希和审核证据为准。历史实验另见 [历史说明](../../docs/history.md)，不得从旧报告恢复已停用模型的制作入口。

用户只有API调用权限而不能登录后台时，不要求其登录或提供后台截图。先检查实际taskId、响应和本地日志；同步音频请求没有返回可恢复标识、且当前API不支持请求日志查询时，如实保留未知费用。只有用户在知晓旧请求状态后明确要求重试，才可用 `audio-analyze RUN --candidate --retry-authorization inputs/实际授权.json --execute` 另建一次尝试。授权绑定原journal哈希、原请求指纹、源/成片/音轨、语种、模型和原预算，`maximum_additional_attempts=1`；新尝试沿原笔数和额度预留，原未知请求不覆盖、不清零。同一原请求重复执行返回同一次重试；有可恢复taskId/response时继续恢复，不能用此入口重复扣费。此例外不是后台无法访问时的自动重试许可。 第二轮须绑定第一轮journal及其哈希，并有新的明确用户指令（retry_attempt=2、previous_retry、previous_retry_sha256）；每条授权仍只允许一次新增尝试，总计最多两轮，不因换授权文件突破限制。

本项目访问约束的机器来源是 `config/kie-access.json`，`kie-authorization.task_verification` 和新聊天prompt均带出该约束。所有后续对话只用API及本地日志核查，不再要求后台登录；不得因用户无后台权限而停止其他不依赖该未知请求的工作。正式知识见 [API与本地核查](../../knowledge/rules/kie-api-local-verification-v1.md)。
