# Hermes Agent 与 OpenClaw：记忆、技能与经验提升机制

查证日期：**2026-10-16（Asia/Shanghai）**。范围：官方在线文档与官方公开仓库 `main` 源码的静态核对；没有安装、运行或验收两个 Agent，也没有验证某个已发布版本的行为。`main` 和在线文档会变化，以下不是版本锁定的运行证明。

## 可以直接采用的结论

两者都把“跨会话记住信息”拆成小型常驻上下文、按需检索和可复用过程。当前两者也都有自动复盘机制，不能把 OpenClaw 概括为只有 Markdown 文件和搜索。这里的自我改进主要是**保存、检索、修订文件和记忆记录**；本次查证的机制没有证明模型权重会随业务使用自动训练。

**自动生成的成功总结不等于公司偏好。** 一次调用成功、一个产物生成成功、一次复盘判断“值得保存”，分别只是执行、产出和模型判断。公司偏好还需要明确的来源、适用范围与有权人员确认。检索次数和候选评分也不能代替翻译质量验收。

## Hermes Agent：真实存在的机制

### 常驻记忆与历史检索

内置记忆分为 `MEMORY.md`（环境、约定等）和 `USER.md`（用户画像、偏好）。默认容量分别为 2,200 和 1,375 字符；会话开始时取快照放进系统提示，保持前缀缓存稳定。会话中写入立即落盘，但快照在下一会话更新。模型说“记住了”不算保存，必须确实调用 `memory` 工具。容量超限会拒绝写入，再由模型处理；这不是自动无损压缩。[官方记忆文档](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory)

`session_search` 从 SQLite 会话库做 FTS5 检索，也能按会话和消息锚点继续阅读。它返回数据库消息，不通过另一次模型总结生成搜索答案；它与始终注入的短记忆是两个通道。当前实现有结果和阅读窗口预算，不能把它理解为一次调用把完整历史塞回上下文。[检索源码](https://github.com/NousResearch/hermes-agent/blob/main/tools/session_search_tool.py)

### Skills 与自动复盘

Skills 采用逐层加载：先发现名称和描述，按需读 `SKILL.md`，再读具体参考文件。保存一个技能文件只有在发现、加载机制接入后才会影响执行。[官方 Skills 文档](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills#progressive-disclosure)

当前代码在回合收尾检查 memory/skill 复盘条件，再派生后台评审。技能触发计数涉及工具迭代，并非“每条用户消息必总结”。评审重放会话快照，使用受限工具白名单，可保存记忆、修订技能；默认不重跑用户任务。提示把通用身份与环境信息、任务过程、用户纠正路由到不同位置，要求优先修正已有技能。**这些选择主要由模型判断，不是独立的业务成功评测器。** 当前技能评审提示仍鼓励积极沉淀，因此存在过度保存的可能。[收尾触发源码](https://github.com/NousResearch/hermes-agent/blob/main/agent/turn_finalizer.py)、[后台评审源码](https://github.com/NousResearch/hermes-agent/blob/main/agent/background_review.py)

### 写入控制、升级与失效

`memory.write_approval`、`skills.write_approval` 可把写入放到待审批队列；默认关闭。当前记忆工具还有更窄的保护：无人值守评审中的 `patch`/`remove` 会进入待审，审批时核对当时匹配的完整条目，避免对已经变化的条目误写。[审批说明](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory#controlling-memory-writes-write_approval)、[记忆工具源码](https://github.com/NousResearch/hermes-agent/blob/main/tools/memory_tool.py)

Curator 记录技能使用活动，可把管理范围内的长期不用技能从活跃变为过时、再归档，并提供恢复与变更记录。模型参与的大规模合并是可选项。**不用、常用与是否正确是不同信号**：归档机制不会证明一条翻译规范仍符合品牌要求。官方页面部分段落的时长示例不一致，实施时应核对所用版本配置，而不复制某个数字作为质量规则。[官方 Curator 文档](https://hermes-agent.nousresearch.com/docs/user-guide/features/curator)

## OpenClaw：真实存在的机制

### 文件层、检索层与偏好

当前架构区分指令、精选记忆、事件记录和供人审阅的复盘产物：`USER.md`、`MEMORY.md` 是受预算限制的精选层；日记和会话是详细记录；`DREAMS.md` 是审阅产物。记忆写入磁盘与被注入上下文仍是不同环节，来源资格、预算与运行配置会影响加载。[官方架构说明](https://docs.openclaw.ai/concepts/memory-architecture)

`memory_search` 可组合向量检索与 BM25 关键词结果，并用新鲜度、重要性和 MMR 调整排序；也支持明确的纯关键词模式。搜索增强解决“找到相关信息”，并不让内容自动成为可信规范。不同 embedding 配置的故障退化行为也不同，不能只用“有搜索工具”来宣称语义检索已工作。[官方检索文档源码](https://github.com/openclaw/openclaw/blob/main/docs/concepts/memory-search.md)

`USER.md` 的当前文档建议把稳定偏好写成行为指令，附观察日期和 `active`/`superseded` 状态；偏好改变时原位替代，避免同时留下冲突的有效条目。这是有用的偏好维护格式，**不是公司批准流程**。[官方 User model 文档源码](https://github.com/openclaw/openclaw/blob/main/docs/concepts/user-model.md)

### 自动保存、Dreaming 与提升

上下文压缩前的 memory flush 是一个静默回合，给模型保存重要上下文的机会；默认文件路径会写日记。它不能保证每条重要事实一定被保存，应检查实际持久化结果。[官方 Memory 文档](https://docs.openclaw.ai/concepts/memory#automatic-memory-flush)

当前 Dreaming 是默认后台整理路径，分为 light、REM、deep；前两阶段整理和反思，deep 才做长期提升。实现不是“写一段漂亮总结就加入记忆”：候选要通过分数、信号次数和不同交互查询等条件，并考虑时间衰减；来源为 `untrusted` 或 `system` 的候选被过滤。当前评分是相关性、频率、多样性、新鲜度等信号的组合，**没有等价的广告翻译正确率或公司偏好认可度指标**。[候选评分源码](https://github.com/openclaw/openclaw/blob/main/extensions/memory-core/src/short-term-promotion.ts)、[来源过滤源码](https://github.com/openclaw/openclaw/blob/main/extensions/memory-core/src/dreaming-consolidation-candidates.ts)

通过候选门槛后，整理模型给出合并、替代等操作决定；写入器根据可验证来源组成记忆，校验旧条目保留、来源引用和容量，失败时退回较保守的追加路径。`DREAMS.md` 供人阅读，不能把它生成的叙述再当成候选来源，避免循环学习自己的总结。[官方 Dreaming 文档](https://docs.openclaw.ai/concepts/dreaming#consolidation-safety)、[运行编排源码](https://github.com/openclaw/openclaw/blob/main/extensions/memory-core/src/dreaming.ts)

### Skills、自学习与恢复

当前 Skill Workshop 保存单个 Agent 学到的重复任务流程。官方当前说明：自学习默认 `auto`，累计足够模型迭代后排队，在空闲时评审完成的会话；只读证据工具可用，修改通过 `skill_workshop`。常规回合也能修正误导它的已有技能。代码把“某个代码库的知识”与可重复执行的技能分开，并要求后台评审修改已有技能前先读取，检查来源回合仍有效、学习开关仍允许写入。[当前自学习文档源码](https://github.com/openclaw/openclaw/blob/main/docs/tools/self-learning.md)、[技能提示源码](https://github.com/openclaw/openclaw/blob/main/src/agents/skill-workshop-prompt.ts)、[工具实现](https://github.com/openclaw/openclaw/blob/main/src/agents/tools/skill-workshop-tool.ts)

Workshop 变更保存前一版本，能撤销、归档和恢复；当前文档也有长期不用技能的自动归档。它们是恢复和减噪机制，不能证明自动修改经过质量评审。[当前 Workshop 文档源码](https://github.com/openclaw/openclaw/blob/main/docs/tools/skill-workshop.md)

## 给本项目的最小落地建议

以下是对广告视频翻译 Demo 的设计建议，不是声称上述项目原样实现了本项目的业务审批。

| 层 | 保存内容 | 使用与升级条件 |
| --- | --- | --- |
| 常驻规则 | 已确认的任务职责、权限边界、质量底线、资料入口 | 保持短小；只有明确批准的规则进入默认上下文 |
| 按需资料与技能 | 品牌术语、语言规则、平台限制、可重复流程、API 使用说明 | 按品牌、语种、素材类型和版本检索；命中后再加载全文 |
| 单次运行证据 | 输入与输出、模型/工具版本、检查结果、人工纠正 | 可检索、可回放；保留失败和未验收状态，不作为默认指令 |
| 候选经验 | 某一步成功、失败原因、复用假设、适用条件 | 自动总结只能到这里；附来源运行、时间、证据与待验证条件 |
| 已验证流程 | 经可比案例验证的步骤与检查方法 | 有证据才提升为技能；保留版本、回滚点和失效条件 |
| 已审业务偏好 | 术语口径、品牌语气、保留/替换标准等规范 | 由有权人员明确确认，记录审批者、范围和生效版本；模型不能自行提升 |

建议的一条闭环是：**运行 → 留证据 → 提出候选 → 复验或人工评审 → 提升到对应层 → 后续命中时复用 → 条件变化时重新核验或失效**。不要把全部历史不断追加到一个永久提示中。

对视频翻译，证据至少要能把“源文本实例 → 区域 → 出现时间段 → 译文 → 擦除/覆盖动作 → 结果检查”串起来。API 返回成功或产物可播放，都不足以证明没有漏字、时序正确或符合公司偏好。候选经验应保存对应证据位置，不能只存“这次效果很好”。

偏好和技术经验应分开：例如“某种字幕参数在此片段通过检查”可以成为参数经验；“所有品牌都喜欢这种字幕风格”仍是未经证实的推断。新纠正应替代旧的有效规则，而不是把相反要求都标为有效。模型、供应商接口、品牌规范或素材类型变化时，对受影响经验标记待复验；不要把时间衰减分数当作唯一失效机制。

## 证据与环境边界

- 实际使用了 research 与 agent-reach 技能流程。`agent-reach doctor --json` 可运行；本地 CLI 为 v1.5.0。Doctor 的配置或可执行状态不等于目标网页已联网读取成功。
- 实际尝试 `gh search repos`，返回连接 `api.github.com` 失败；尝试 agent-reach 的 Jina Reader 路径，返回 DNS 解析失败。随后使用本会话的 Web 工具读取上述官方文档和官方 raw 源码，没有把搜索摘要当作最终实现依据。
- `agent-reach check-update` 因 DNS 失败，不能确认是否有新版。没有安装、升级工具，没有读取密钥或私有配置，没有写入用户外部账号。
- 搜索缓存可能落后于 `main`：本次 OpenClaw 的旧搜索摘录仍提到提案队列，直接读取的当前文档和 `skill_workshop` 源码则是版本化的直接修改机制。因此不能从旧文章或旧摘录推断当前默认审批模式。
- 本报告核对了文档与关键代码路径，没有进行端到端实验、性能测试、翻译质量评测或公司业务验收；不能据此声称长期正确率、成本或速度一定改善。
