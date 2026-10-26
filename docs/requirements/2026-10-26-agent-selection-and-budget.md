# 场景选路、知识冲突与按时长预算

来源：项目用户要求修正已识别的八类歧义，保留 Agent 自主选择，并写明适用条件、首选/备选、切换和停止依据；同步索引、工作流并提交一次。预算原话：“目前的预算是60credits，目前卡太死了，视频如果很长可以增加预算。大概1s最多限制3credits吧。”用户随后要求跳过 Penny。本次仅本地整理、验证和 commit。

## 八类问题的处理

| 问题 | 统一决定 | 现行入口 |
| --- | --- | --- |
| 模糊兜底前置条件冲突 | 静态底面优先自然重建；复杂运动/遮挡依据连续帧主体风险或实际候选，允许较早比较最小局部兜底 | content-aware-text-restoration-20261026 |
| 快速与严格门禁混用 | 共同内容/音频/时序要求；fast 基本检查及风险证据；strict 完整逐实例连续审计 | neutral-visual-and-animation-gate-v4 |
| 音频必需与字幕兜底冲突 | 必需配音的请求直接报告不可用，字幕不能算完成；新请求显式记录 require_target_audio | always-output、audio 合同及 finalize |
| 多方法重叠、优先级不清 | 用户要求→合同/政策→条件方法；按实例选主修复，叠加运动、水印和音频检查 | agent-method-selection-v1、route-selection-v3 |
| 场景标签不明确 | 按实际轮换、短句、独白、运动、遮挡检索；同义标签归一，剧情地点不推导方法 | config/content-features.json |
| 角色独立声线降级模糊 | 身份疑点、漏句、临时故障、实际能力/授权边界分别处理；最低男女声要有真实可辨声音 | short-drama-character-voices-v2 |
| 时间伸缩、识别分歧无退出条件 | 测量源轮次和实际声音；裁静音、核实空隙、有限变速、等义缩译/补录；分歧保留原结果局部补证 | short-drama-audio-scenes-v2、spoken-caption-v4 |
| 基础语言与地区范围不一致 | 明确 BCP47 标签优先保留；案例默认完整匹配，base 须显式审查；范围外同源线索单列 | language-aliases-v2、related_source_references |

新请求总额度＝原视频实际时长×3 credits，向下保留三位小数，覆盖一次请求内全部目标语言、模型及重试；10秒30、60秒180、75秒225。没有最低60，不乘语言数。旧账不自动改额或清除费用/未知占位；主控可按真实授权 budget-amend。任务名额随原时长分段和已确认角色有限增长，两轮返工仍保留。长视频普通导入/解析移除旧180秒演示限制，模型输入仍须分段并遵守各接口合同。

## 项目职责与可追溯性

AGENTS 为入口；agent/contracts 约束权限、证据、声音和交付；workflows 组织阶段；knowledge/index 选现行方法，cases/index 约束同源案例；config 是机器参数源；src/bin 执行媒体、预算和绑定；runs/outputs/state/work 存本地过程、交付与回执。workbench 的独立未提交内容保留原状，不纳入本次整理。

本次发布九条新政策/方法，保留替代链；旧正文和未索引草稿按原字节入 history，原例证 manifest、历史费用及视频质量结论保持原范围。迁移指纹见 knowledge/curation/selection-alignment-20261026.json。新正文证据是本次授权和开发者方法审阅，不代表新增真实视频、母语听审或公司验收。

Agent 仍需根据新素材实际证据判断，未知情况明确补证或退出。索引命中、说明采用、实际 knowledge-use 和视频质量通过是不同事实；规则无法保证所有未见素材自动判断正确。
