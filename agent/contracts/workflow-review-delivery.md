# 检查、返工、交付及学习

总入口见 [workflow](workflow.md)。

## 4. 检查与返工

拼接后抽取成片证据，复制 review/template.json 填写 review/review.json。Agent 查逐实例翻译、漏字、原字残留、闪烁、时序、品牌与广告含义，实际听音或提供可核对音频证据。不能把未看的视频填为通过。

有人声时完成该视频哈希目录的 `caption-sync.json`，同时引用成片 WAV 和字幕边界帧，记录实际说出和实际显示的时间。完成后重跑 `capture` 冻结证据，再执行 `quality`；音频单独送审的同步结论不能替代视听同步检查。

概览拼图用于定位，不作为擦字验收的唯一证据。必须查看原尺寸问题区域、无字底片和透明字层，并核验实际编码的连续运动与首末边界。OCR为空、哈希正确、单张关键帧干净都不能证明去字成功或运动保真。制作门禁的签字和检查字段须来自真实观察。

失败时先记录观测和待验证原因，再选一个变量：单实例、短片段、明确时间区域、更换路线。最多两轮；无法合格时按 always-output 输出当前最佳完整译片及瑕疵说明，明确尚未质量通过；用户必需配音且不可用时如实报告，不以字幕替代。

## 5. 交付与学习

正常质量通过路线通过 `quality` 后 `deliver`；有界返工后未通过的完整候选按 always-output 用 `finalize`，两者状态分开。正常路线得到 `outputs/` 中独立交付包的final.mp4与哈希证据，run内副本保留。交付函数自动归档并执行候选复盘，返回package/case/inbox；中途失败可重试收尾，不重发模型任务。有候选成片的失败结案运行 `reflect`；还没有候选的失败使用 `close-failure RUN SPEC`，记录实际观察、哈希绑定证据与未审范围，不伪造 candidate 或 quality。见 [本地配音与失败结案](../workflows/local-production.md)。

单次或批量收尾后运行 `delivery-index` 刷新 `outputs/index.html`，按任务和语言直接打开正式包中的视频。默认不给 outputs 根目录增加便捷视频副本、批次视频文件夹或 ZIP；只有用户明确需要下载打包时才导出到用户指定位置。批次独有字幕和说明可放 `outputs/reports/<批次>/`，不存媒体副本。参考/待改进版本保留原状态，不因打包而称为已交付。目录入口是可重建视图，`index.json` 和各交付包 manifest 才是定位依据。

知识提纯、用户反馈和素材保留按 `.agents/skills/knowledge-curation/SKILL.md`；方法和必要案例长期保存在knowledge，源片/底片/各语言成品保存在可到期的outputs，runs为执行过程。自动候选不改变正式知识或公司偏好。最终给用户视频、关键权衡、验证范围和待解问题。

用户否定或复现推翻某版质量时，按 `agent/templates/quality-hold.json` 运行 `quality-hold SPEC`，将具体成片及确认有缺陷的共享底片分别绑定实际哈希，保存有来源的反馈证据。随后刷新delivery-index。原评审和交付包保留历史原文；当前目录与library-find显示质量异议和production_eligible=false，制作及deliver入口阻断被否定的字节。新修复版本用新哈希重新审核，音轨和译稿是否可复用分别判断。不要只把反馈记进候选而让旧成功标签继续指导制作。详见 `agent/workflows/quality-feedback.md`。


每次运行开始与续作读取 `work-packet.maintenance`；外部交付及记录完成后执行 `maintain RUN --close`，检查删除/暂缓回执。临时缓存归属和自动整理见 [存储合同](storage.md)。

