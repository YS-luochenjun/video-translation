# 项目自身的知识提纯 Hook

开发者于2026-10-20授权每天北京时间09:00整理新增项目经验、合并重复内容，保留来源和适用范围；已验证翻译规则保持原样，不调用付费视频模型。2026-10-27用户进一步要求巡检、经验总结、存储整理各用独立定时任务，2026-10-28用户将执行时区调整为Asia/Shanghai，当前由独立应用经验任务每天上海时间18:00唤醒，见[三项定时职责](scheduled-tasks.md)。项目保留提纯角色、检查点与写入控制，调度与推理解耦。

## 运行链路

```text
deliver / reflect → 项目候选与inbox
                              ↓
独立经验定时任务 / 可选Windows宿主触发器
                              ↓
config/hooks.json → curation.py：锁、到期判断、文件哈希增量
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

当前文本适配器是 `codex_cli`，通过命令行使用当前登录的AI推理能力。当前独立应用任务负责唤醒，不能在关闭应用后宣称会继续运行。Windows可选择已核验的系统触发器，但不与应用经验任务重复启用。换AI时可使用相同的packet/schema与prepare/apply接口；预算边界和存储规范保持在项目内。

## 操作

```powershell
.\bin\va.ps1 hooks status
.\bin\va.ps1 hooks run                 # 手动执行一次
.\bin\va.ps1 hooks run --due           # 按config/hooks.json的上海时区到期判断执行
.\bin\project-hooks.ps1 -Action Install
.\bin\project-hooks.ps1 -Action Status
.\bin\project-hooks.ps1 -Action Uninstall
```

新机器首次部署必须显式运行 `hooks baseline`，登记当时已经整理的历史输入；已有检查点不能重建覆盖。来源为knowledge/candidates及knowledge/local下的candidates、inbox、feedback，排除目录索引和生成报告。安装定时器不会调用推理或视频模型。

Windows可选任务计划程序，按带UTC+08:00时区的每日触发器执行，并在当前用户登录时检查补跑；此路线需要电脑开机、用户登录和有效CLI/Python，可不依赖桌面应用。当前macOS使用应用定时任务，需要应用运行，没有独立系统触发器的安装证据。其他宿主可显式配置系统定时器调用 `va.py hooks run --due`；仓库配置本身不会唤醒关机电脑。迁移机器后重新核对调度，不重建旧检查点。

更换推理接口或人工检查建议时：

```powershell
.\bin\va.ps1 hooks prepare             # 输出packet与JSON schema位置，不请求AI
.\bin\va.ps1 hooks apply --response work/curation-response.json
```

新回复必须覆盖当前packet的每个event_id；过时、重复、来源不明、跨scope或跨公私范围的合并会被拒绝。若配置engine为packet，定时任务只准备资料并明确报告awaiting_reasoning，不声称已自动提纯。

## 保存与执行边界

- 检查点、锁、任务包、推理用量、pending与报告保存在 `knowledge/local/curation/`；这些是本地运行状态，不是项目经验正文。已整理技术候选保存在可版本管理的 `knowledge/distillations/`；私有来源的提纯保存在本地private-candidates。
- 每条候选继承原scope，保存全部原始观察快照、来源路径/哈希、限制、失败和反例。路径只是来源标签；读取方法不依赖runs/outputs。原始记录保持不变，修订使用新内容哈希文件，旧版本继续保留。
- 新回复须提出 adoption 目标及缺证据项；旧缓存回复仍可读取，不假装已有采纳决定。已通过审查关闭的来源不再进入增量提纯。Hook报告指出待审队列，主控通过knowledge-review落实处理结果；Hook自身仍不能发布正式规则。
- AI只返回受schema约束的数据。CLI适配器在隔离目录运行，禁用shell、MCP、应用、浏览器、图片生成、其他Agent及宿主hooks；执行器不向其传递媒体模型密钥。工具调用结果会被拒绝。
- 相同含义、完全相同scope及相同可见性才允许合并。同一素材返工不算独立复验。缺证据或有冲突保留pending/待审，不自动启用。未变化的pending保留待办，不每天重复调用AI；补充或修订来源后再次进入增量。
- 执行前后核验正式索引、规则、案例、agent 执行依据、docs 开发说明、config（含偏好和 Hook 提示词）与技能的哈希，并运行knowledge-audit。全部成功后，检查点一次提交源进度与候选版本；目录索引仅是可重建视图。并发锁、缓存回复和不可变版本防止重试重复；失败不推进检查点。
- 本hook没有视频、图片或语音模型提交接口，不读取.env，不制作视频、不清理runs/outputs、不提交Git、不修改全局记忆。外部媒体模型credits为0；文本推理使用当前AI账户额度，实际用量记录在engine-receipt.json，不能表述为完全无计算消耗。

当前上限与时间在 `config/hooks.json`；角色提示词在 `config/hooks/knowledge-curation/prompt.md`；宿主安装回执在 `knowledge/local/curation/schedule.json`。代码与配置可随项目管理，机器路径和运行凭据保持本地。

日常主动检查不依赖用户提醒：每次制作/修复/反馈结束记录本次经验，独立经验任务读取`knowledge-queue`与`hooks status`；每日到期时运行`hooks run --due`，再按知识技能处理本轮待审。Fireplay巡检不兼做全局知识整理。`new_records`表示尚未进入提纯的输入，`adoption_queue_open`和`review_required`表示尚未闭合的审查，`pending`表示Hook保留的具体缺口，三者不能混为一谈。来源已直接审查结清时，不再重复生成提纯候选。电脑/宿主未唤醒或推理失败时保留实际缺口，不声称定时处理成功。

2026-10-27知识暂存整理修复：知识队列和增量Hook均排除独立案例包内副本与原始ASR证据，原文件继续保留。inbox指向已归档公开候选时，按实际候选哈希及原案例/已采纳目标核验已闭合状态，不仅按名称丢弃；无需反复提纯旧指针。当前本机在实际队列与未处理增量均归零后建立基线，不将未审来源伪装成已总结。此处不宣称已安装独立系统调度器，应用监控仍由既有定时唤醒执行。
