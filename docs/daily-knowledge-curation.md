# 项目自身的知识提纯 Hook

经验总结由用户手动触发。`config/hooks.json` 保留旧调度配置，`automatic=false` 关闭定时运行。Fireplay巡检和存储整理各用自己的入口。见[任务职责](scheduled-tasks.md)。

## 运行链路

```text
deliver / maintain → 基于当前成片评审的经验候选或结案回执
                              ↓
工作台「总结新增经验」/ 在项目中手动运行
                              ↓
config/hooks.json → curation.py：锁、自动模式开关、文件哈希增量
                              ↓
config/hooks/knowledge-curation/prompt.md + 有界packet
                              ↓
可替换的文本推理接口 → 分组、合并建议、pending
                              ↓
执行器检查来源、原scope、可见性、保护文件哈希
                              ↓
knowledge/distillations/候选 + 原子检查点 + 审计记录
                              ↓
knowledge-queue → 主控审查采纳目标/缺证据 → knowledge-promote / knowledge-review
                              ↓
正式方法与独立候选召回 → knowledge-use 使用反馈 → 修订审查队列
```

当前文本适配器是 `codex_cli`。工作台「总结新增经验」优先通过在线桥接派发给负责会话，否则提供使用工作台 Python 的命令。整理完成后审查拟采纳的内容。

工作台默认显示现行方法与政策。「现行同源案例」按原片和语种匹配。「待审经验」把同源同文的记录折叠展示，展开可查看各语种条目。「历史与已审结」可查询已替代版本和已归档候选。

历史按[知识合同](../agent/contracts/knowledge.md#候选退出队列与归档)保留有追溯价值的条目。无内容的已审结占位在授权清理、核对引用并实删后退出历史计数。

交付维护根据成片哈希查找对应评审。实质 `lesson` 进入经验候选，空白复盘只保存结案回执。可用 `knowledge_no_new_reason` 写明沿用既有方法的原因。运行归档保留证据包和恢复材料。

## 操作

```powershell
.\bin\va.ps1 hooks status
.\bin\va.ps1 hooks run
```

新机器首次部署必须显式运行 `hooks baseline`，登记当时已经整理的历史输入；已有检查点不能重建覆盖。来源为knowledge/candidates及knowledge/local下的candidates、inbox、feedback，排除目录索引和生成报告。安装定时器不会调用推理或视频模型。

新工作区没有可核验且完整的检查点，已有来源仍待处理时，使用 `hooks baseline --include-existing` 初始化。现有审查决定继续生效，未审来源保持增量待处理。已有检查点需沿原历史恢复。

旧宿主若调用 `hooks run --due`，项目在手动模式下返回 `manual_only`。手动执行沿用原检查点。

更换推理接口或人工检查建议时：

```powershell
.\bin\va.ps1 hooks prepare             # 输出packet与JSON schema位置，不请求AI
.\bin\va.ps1 hooks apply --response work/curation-response.json
```

新回复必须覆盖当前packet的每个event_id；过时、重复、来源不明、跨scope或跨公私范围的合并会被拒绝。每条来源只能出现在groups、pending或no_new_knowledge之一；no_new_knowledge需要具体理由，记录来源哈希及处理理由但不生成候选。缺证据仍留pending，不能通过此出口结清审查队列。若配置engine为packet，定时任务只准备资料并明确报告awaiting_reasoning，不声称已自动提纯。

新生成schema要求analysis：observations逐来源引用event_id、record内JSON pointer和原文quote；causal_hypothesis单列尚未证实的原因；action_basis区分proposed、observed_comparison及independent_sources，动作仍在action。执行器检查原文定位、引用覆盖及独立源身份数；同源返工不能算独立复验，宽scope方法建议仅有一个已知视频源时保留候选、将采纳建议降为pending并记录原建议与缺口，整批仍可提交。无视频源身份的开发技术观察不强制双视频证据，可凭单个确定性回归提出候选；身份未知的视频经验仍由主控保守审查，不能据此扩域。引用可核对不代表修复对照充分、整体好评支持细节结论或因果成立，这些仍须主控读证据后判断。原scope、公私范围和候选权限不变。

旧缓存回复允许缺省analysis、adoption和no_new_knowledge；读取旧候选或检查点不触发迁移/重跑。缺省analysis的回复新生成候选时标记legacy_unassessed并在limitations提示审查缺口；原有候选召回和检查点提交机制保持兼容。新字段不补造旧记录的证据。

## 保存与执行边界

- 检查点、锁、任务包、推理用量、pending与报告保存在 `knowledge/local/curation/`；这些是本地运行状态，不是项目经验正文。已整理技术候选保存在可版本管理的 `knowledge/distillations/`；私有来源的提纯保存在本地private-candidates。
- 每条候选继承原scope，保存全部原始观察快照、来源路径/哈希、限制、失败和反例。路径只是来源标签；读取方法不依赖runs/outputs。原始记录保持不变，修订使用新内容哈希文件，旧版本继续保留。
- 新回复须提出 adoption 目标及缺证据项；旧缓存回复仍可读取，不假装已有采纳决定。已通过审查关闭的来源不再进入增量提纯。Hook报告指出待审队列，主控通过knowledge-review落实处理结果；Hook自身仍不能发布正式规则。
- AI只返回受schema约束的数据。CLI适配器在隔离目录运行，禁用shell、MCP、应用、浏览器、图片生成、其他Agent及宿主hooks；执行器不向其传递媒体模型密钥。工具调用结果会被拒绝。
- 相同含义、完全相同scope及相同可见性才允许合并。同一素材返工不算独立复验。缺证据或有冲突保留pending/待审，不自动启用。未变化的pending保留待办，不每天重复调用AI；补充或修订来源后再次进入增量。
- 执行前后核验正式索引、规则、案例、agent 执行依据、docs 开发说明、config（含偏好和 Hook 提示词）与技能的哈希，并运行knowledge-audit。全部成功后，检查点一次提交源进度与候选版本；目录索引仅是可重建视图。并发锁、缓存回复和不可变版本防止重试重复；失败不推进检查点。
- 本hook没有视频、图片或语音模型提交接口，不读取.env，不制作视频、不清理runs/outputs、不提交Git、不修改全局记忆。外部媒体模型credits为0；文本推理使用当前AI账户额度，实际用量记录在engine-receipt.json，不能表述为完全无计算消耗。

当前上限与时间在 `config/hooks.json`；角色提示词在 `config/hooks/knowledge-curation/prompt.md`；宿主安装回执在 `knowledge/local/curation/schedule.json`。代码与配置可随项目管理，机器路径和运行凭据保持本地。

制作和修复结束时记录本次观察。用户要求全局整理时读取 `knowledge-queue` 和 `hooks status`，优先审反例和有效修正，再手动提炼需要归纳的来源。`new_records` 是下次可提炼的新增或修订来源数，`pending` 是仍对应当前来源版本的提炼待补证项。人工已审查的版本沿 `knowledge-queue` 的待办处理。`adoption_queue_open` 是尚未审结的记录数。

2026-10-27知识暂存整理修复：知识队列和增量Hook均排除独立案例包内副本与原始ASR证据，原文件继续保留。inbox指向已归档公开候选时，按实际候选哈希及原案例/已采纳目标核验已闭合状态，不仅按名称丢弃；无需反复提纯旧指针。当前本机在实际队列与未处理增量均归零后建立基线，不将未审来源伪装成已总结。此处不宣称已安装独立系统调度器，应用监控仍由既有定时唤醒执行。
