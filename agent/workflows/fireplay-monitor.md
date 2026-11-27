# Fireplay新翻译需求巡检

宿主应用每30分钟唤醒主控；本流程不另装系统cron。用户授权范围、组/人员策略、并发和静默通知规则在config/fireplay-monitor.json；制作/回传执行[编号接入](fireplay-intake.md)，模型/费用/质量与固定提交政策读根AGENTS.md及对应config。全部可见组均覆盖，仅查询执行人包含邹彬（已核验ID `b2fbcgab`）的需求；不能只查APC/MOG或只搜“翻译”。

长期生命周期按config/fireplay-monitor.json.lifecycle：新需求巡检全天每30分钟持续开启，不因本批、当前全部会话完成或队列暂空而暂停/删除；只有用户明确要求停止需求巡检才调整。滚动范围的会话完成盯办是独立任务，后续人工新增并接入的需求也纳入；全部当前范围真实交付核验且无新接入负责项后只结束该盯办，不删除制作聊天，也不停止本长期巡检。旧批次停止记录不能充当长期巡检的停止条件。

本定时任务负责发现、范围判断、接入和调度。制作与回传由原需求聊天继续。用户手动触发经验总结，存储按自己的日程整理。各入口见[任务职责](../../docs/scheduled-tasks.md)。

新需求按原片拆分会话。读取 `source_capacity` 和 `ready_to_dispatch[].sources`，在每个原片建聊前占用全局10个名额之一。旧需求的聊天和已领取原片沿原执行者续作。派发、恢复和状态更新保留真实回执。操作未知时先查原记录。步骤见[并行制作](fireplay-parallel.md)。

自动接单同时检查执行人包含邹彬、AI承接交付为视频翻译、状态为未开始、具备绑定及状态权限。读取正文确认原片和实际语种。建聊和付费前按编号及UUID核对原聊天、请求、账本与平台绑定。其他状态保留日常跟踪和具体判断。

用户明确撤回或确认由同事接手的需求，在 `config/fireplay-monitor.json.excluded_requirements` 按编号和 UUID 记录。保留原需求、聊天及回执，排除后续接入、派发和完成盯办。

优先级不是接入条件。所有等级（含P2、其他值和未标等级）都按同一范围判断承接，排序与推进规则读取config/fireplay-intake.json.priority_policy；低优先级不得被静默丢弃或等待所有高优先级结束。排队须保留ready_to_dispatch，具体信息/权限/费用/质量缺口分别记录。普通单条语言确认不扩展为全局别名；用户2026-11-09已明确将sa统一为ar，按config/language-aliases.json及[语言解析政策](../../knowledge/rules/language-aliases-v3.md)执行，不再逐条询问sa。旧请求/账本/费用及历史确认保留。

发起规范在需求面板指派邹彬，可另加实际设计师。巡检用精确assignee_ids筛选，多执行人中包含该ID即可。按同一全局原片上限排队。需求数独立保留，原片的所有语言合占一个名额。

按当前阶段进入对应章节。各专题保留原章节正文与执行依据。

## 分层轮询与判断

[阅读此章节](fireplay-monitor-discovery.md#分层轮询与判断)。

## 需求面板的投放记录

[阅读此章节](fireplay-monitor-discovery.md#需求面板的投放记录)。

## 承接与调度

[阅读此章节](fireplay-monitor-dispatch.md#承接与调度)。

## 补交与经验收尾

[阅读此章节](fireplay-monitor-dispatch.md#补交与经验收尾)。

## 会话故障接替

[核实原制作聊天的工具故障并接替](fireplay-monitor-dispatch.md#会话故障接替)。

