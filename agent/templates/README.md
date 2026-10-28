# 模板与填写示例

本目录提供操作规格的填写格式。先复制到本次任务指定的输入位置，再填写真实来源、哈希、时间和观察，最后把实际文件交给相应命令。模板不会自动执行，示例值不构成授权、证据或审核通过。

| 模板 | 用途 |
| --- | --- |
| [预算请求](budget-request.json) | 主控为真实用户请求登记共用预算 |
| [实例清单](inventory-example.json) | 记录镜头、文字、人声与覆盖范围 |
| [水印与片尾同标](publisher-marks-example.json) | 记录发布者身份、大小写变体、分立实例及去除不补字 |
| [图像任务](codex-visual-task.json)、[图像回执](codex-visual-report.json) | Codex 看图和编辑任务及真实产物登记 |
| [字幕对齐](caption-alignment-example.json) | 记录实际最终混音中的字词时间 |
| [动态文字](motion-typography.json) | 标题/CTA/关键词强调的明确动效与字体绑定，失败回退记录见文字适配器文档 |
| [修复配方](local-repair-example.json) | 填写源绑定的局部程序操作 |
| [失败结案](preproduction-failure.json)、[质量异议](quality-hold.json) | 保存实际失败或用户反馈及哈希证据 |
| [知识条目](knowledge-entry.json)、[证据](knowledge-evidence.json) | 候选登记与独立证据规格 |
| [方法发布](knowledge-promotion.json)、[同源参考](source-reference.json) | 按知识合同发布已审查内容，保持范围 |
| [候选审查](knowledge-review.json)、[使用反馈](knowledge-use.json) | 决定采纳目标与剩余内容；记录本次真实使用或未使用、效果和反证 |
| [版本选择](prune-versions-example.json) | 清理预览时明确选择历史完整视频 |
| [实验记录](experiment.md) | 记录问题、单一变量、观察、限制与后续验证 |

执行规则见 [制作工作流](../contracts/workflow.md)、[知识合同](../contracts/knowledge.md) 和 [存储合同](../contracts/storage.md)。字段校验由执行器负责，命令参数以 CLI 帮助为准。

实例清单示例采用自然底面与透明字层；`model_edit` 是实例动作，不代表已经调用视频模型。先按[底面与运动难度](../../knowledge/rules/content-aware-text-restoration-v2.md)填写实际 reason/evidence，再判断图片编辑、本地合成、Wan 或局部模糊兜底。示例的静态特征、时间和坐标均须替换为实际观察。

选择记录继续用清单 reason/evidence：实际条件及证据、命中方法版本、首选理由、备选与切换观察、停止理由、检查及未审范围。未知条件保留疑点；不要求为填字段进行多余试验。多人对白按角色记录稳定身份和声音证据，剧情地点不能代替技术特征。

knowledge-promotion 的 delivery_modes 仅限定适用模式；language_match 默认 exact，只有审查为基础语言通用的条目才用 base 且 scope 填基础标签。原地区/文字系统案例保持原范围。新方法可经审阅显式写 retrieval_role=required；普通修订省略该字段时继承上一版的必要角色和审阅来源，避免套模板意外丢失必要召回。首次未声明时为 optional；显式改变仍须有来源的正式审阅。

## 历史兼容

[local-tts.json](legacy/local-tts.json) 仅描述已有 Piper 声音的参数身份，供核验和复用旧产物；新配音使用当前 Gemini TTS 路径。它不属于新任务的默认模板，历史结果缺失时不重新启动旧模型。

routing_assessment 的三类条件与保留源内容分支见 [信息载体方法](../../knowledge/rules/content-led-localization-v1.md)。清单中的 pending 示例不能直接通过：替换实际 primary_type、reason、evidence，按 speech/visual 填 method_choices 的首选、备选、切换及停止依据；每句 speech_role 标明旁白/对白等职责及稳定 character_id。retrieval_role=required 的方法在适用时完整返回，选择调用仍由 Agent 判断。

Fireplay YouTube 显式账号选择使用 `fireplay-youtube-route.json`：只填写实际界面选中的账号、真实账号组、观察时间与任务目录内截图哈希，再执行 `fireplay-youtube-route CODE SPEC --video N`。它不执行外部上传。导入回执另附 `youtube_task_verification` 的实际素材、任务、账号及账号组/任务组；共享组不能代替此核验。详见 [按编号接入](../workflows/fireplay-intake.md)。
