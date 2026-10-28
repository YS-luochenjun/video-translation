# 定时经验总结

职责：处理已形成的制作、开发与反馈经验，使其进入可复用方法、限定案例或明确待办。默认每天上海时间18:00由独立应用定时任务唤醒；不依赖Fireplay巡检轮次。机器需开机且应用运行，聊天无需显示在前台。

1. 读AGENTS.md、知识合同及 `.agents/skills/knowledge-curation/SKILL.md`，使用doctor验证的Python。读knowledge-queue与hooks status；保留原检查点、既有审查、原scope和公私边界。
2. 每轮最多处理24条来源，先处理真实反馈/反例，再处理新增记录。Hook到期则运行hooks run --due；文本接口不可用时可由当前Agent按prepare/apply执行，不重建baseline、不调用付费媒体模型。超出本轮范围留明确下一步。
3. 逐来源读实际观察与必要证据，优先合并含义相同且scope相同的现行方法。源限定事实建案例；缺证据保留pending。需要新方法先knowledge-promote，再knowledge-review登记采纳/保留部分。只有全部处理的候选才按新预览指纹归档。
4. 读本次新增knowledge-use反馈及反例，不从命中推断使用，也不替活跃制作填写未观察的效果。普通开发者审查可在既有授权下自主完成；公司偏好/质量标准变化仍需明确授权。
5. 运行knowledge-audit并刷新project_health，保存输入/输出计数及真实审查回执到work/state。`new_records=0`不等于审查完成，同时核对adoption_queue_open和pending。不为清空队列伪造验证。

本任务不扫描或接入Fireplay、不调度制作、不做平台写回、不清理媒体/交付库、不自动commit/push。原始候选的指纹归档属于本任务的知识生命周期。仅在有新采纳、具体反例、明确失败或需要用户决定时通知；相同未变待办保持安静。
