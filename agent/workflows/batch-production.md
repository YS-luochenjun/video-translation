# 批次制作、预算与耗时

本入口串联已有制作步骤，不替代 Agent 的源观察、翻译、路线选择或实际视频评审。不改变擦字、运动、声音和字体算法，也不降低质量标准。

## 新任务

主控按 `agent/templates/budget-request.json` 填真实用户请求、原视频及宿主消息ID，执行 `bin/va.ps1 budget-open SPEC`，取得请求总账本ID。然后用 `bin/va.ps1 batch-create demo C:/media/source.mp4 --targets ja es pt` 编排语言。第一语言是代表语言，优先选择文字长度/字体与音频风险有代表性的语言。各语言独立run，但一次请求的所有批次/run/短片/模型/返工共用原视频实际时长×3 credits 的总限额（向下保留三位小数）；不能把额度乘以语言、模型或任务数。

单语言也可用此入口。旧的init及查询、下载、评审继续可用，但没有请求账本的run不能新增付费调用。同源新run自动加入现有预算；首次登记会收纳同源旧run的费用，不能换run跳过旧账。派生短片字节不同，先 `budget-bind CHILD --parent-run PARENT` 继承总预算。删除run不会返还总账本中的费用或未知占位。

只有用户后续真实提出新复用需求，主控才登记另一请求：`mode: reuse`、`reuse_of: 先前账本ID`、`reuse_confirmation: new_user_request`，使用新的真实宿主消息ID。旧账需全部对账，关闭后新请求按原视频实际时长×3 credits 登记，再 `batch-create ... --reused`。同一请求的失败、返工、拆片或新增worker不是新的复用额度。已结算的历史供应商回执复用不重计费用；新调用照常计入新请求总额。历史账本不自动改价；带用户来源的 budget-amend 保留费用及未知占位。任务名额按原时长/角色数有限规划，两轮返工与整请求预算同时约束。归档恢复的旧batch指针仅作来源，新部署须由自己的拥有者授权并登记请求。

1. 先对代表run执行analyze/context，建立真实inventory，使用已有source-save/source-find缓存原片观察。缓存不复制目标译文或验收。
2. 按原流程准备无字底片、音轨和字层。底片必须过原有prepared-video门禁。同源资产用交付库恢复/绑定，或 `reuse-neutral TARGET --from-run SOURCE --source-shot ID --target-shot ID` 复用同一源时间段的已审无字底片。它复制独立证据并校验哈希、质量异议与原评审；不重新编码，不复制目标语言译稿/音轨/成片审核。绑定后重建目标plan。
3. `tts-packet RUN --voice Kore --estimate 2` 从定稿speech_segments生成源绑定请求；可用 `--speech-ids id1 id2` 选择有序子集。声音选型、风格和保守估价仍按任务判断，此命令不付费。检查后用 `model-task RUN 包路径 --execute`。听感、语义覆盖和混音后对齐必做。
4. `production RUN` 串联计划、渲染、原尺寸视觉对照、抽证据、quality。新视觉证据默认pending；按[视觉门禁](visual-review.md)完成逐实例观察以及整片/字幕实际观测后重跑。缺inventory或实际评审时明确停止，不编造通过；加 `--deliver` 仅交付通过者。现有build_repair_master、mix_localized_narration、OCR/ASR和分离脚本继续共用。
5. 实际检查代表语言并填写评审后 `batch-approve demo`，重新过质量门禁，冻结成片、计划、评审及底片哈希。不将Agent自审改称用户验收；用户明确要求先确认时仍须等确认。
6. 各语言自己的译稿、音轨、时轴、字层就绪后 `batch-run demo --deliver`，在第一个待审或失败处停止。非代表语言的付费提交和渲染重新核验代表语言，变化后须重新审核，各语言依然逐一quality。

默认串行渲染，避免编码器争用磁盘/显存；未引入并发付费提交。原命令也可逐步使用，已绑定批次的预算、渲染门禁仍有效。新场景的遮罩、跟踪、字体和布局仍需判断，本次没有把单片坐标推广为通用算法。

## 可恢复执行

新增的 ASR / 分离 / 混音检查点、视觉片段复用和阶段导航见 [P0/P1 流程优化](../../docs/workflow-optimization.md)。优先 `work-packet RUN` 读取当前机械状态；`asr`、`audio-mix` 与旧脚本共用实现，采用返回的实际输出路径。默认同工作区一次一个重任务，资源忙时保留现场后重试，不主动删锁或重发付费任务。`production --force-render` 同时跳过整片和片段编码缓存。

production编码检查点绑定计划、inputs/analysis字节、模型结果、项目字体、编码器版本与代码；各语言不复用目标成片。有效检查点仅跳过重复编码，capture、quality、质量异议仍重查。系统安装字体变化不在项目字体哈希中，改变后须 `production RUN --force-render`。返工应修改实际方案，不能反复编码同一失败方案。

已有计划保留其明确路线（包括experiment）；inventory或资产改变导致计划失效时，先按原意重新执行plan，不由production偷偷换回默认算法。批次未完成前保留代表run及其评审，删除后放行证据缺失会阻断继续扩语。

## 预算与授权

`budget-status ID` 显示整次请求占位/计费、剩余额度和待对账数；`batch-status demo` 使用同一总账本并补充批次进度与耗时。视频submit、model-task、audio-analyze在外发前原子预留；KieClient写请求必须持有执行器预留许可，单份许可只能建一次模型任务。并发锁冲突时停止；中断在预留后未写job也继续占位，需要对账，不自动重发。确认终态计费后结算；收到费用但JSON解析失败也保存实扣。

总账本在state/budgets，批次进度在state/batches。请求上限固定60/40；修改run/batch预算或新建run不会增额。不要手动删除或调低账本。当前支持的全部付费KIE入口统一记账，其他供应商如后续接入也必须先走同一预留/结算合同。当前本地OCR/FFmpeg不产生供应商credits；Codex宿主套餐消耗没有KIE credits计价接口，不伪造换算。

执行器能阻止“已实扣或占位 + 下一笔估价”超过总额，但本地估价不能约束供应商最终计费；要保证远端账单绝不超额，需要供应商的确定价格/硬限额。实际费用超估算会阻止后续调用，未知计费继续占位。旧的单笔视频40上限已移除，Seedance禁用、每run笔数与返工次数保留。

权限边界：budget-open是宿主/主控登记真实用户事件的管理入口，不应暴露为子Agent可自行增额的业务工具。已授权自动KIE的正常翻译请求，无需为登记账本再问用户。当前本地文件系统无法防止拥有管理员权限的人改源码、伪造宿主事件或手动改账；迁移服务时由服务端保存可信用户事件、账本和KIE密钥，只给worker绑定预算后的执行接口。

`kie-authorization` 显示拥有者授权。已授权预算范围内由Agent判断是否必要并使用KIE，不再每对话重复询问；需要扩预算、其他供应商或范围外素材时仍需授权。宿主安全审批不能由配置绕过。

本机授权在config/kie-authorization.local.json，含原话及工作区绑定；不进Git或干净导出。新部署的操作者按自己的授权复制example为local并填实际路径。能力可迁移，付费同意不替其他用户作出。

2026-10-22：项目根 AGENTS.md 要求每次先读取 `kie-authorization`；已有有效授权范围内直接执行必要调用，无须逐视频重复询问。Codex 的命令/外发审批是独立宿主权限。用户对“本项目所有符合条件的命令和外发审批交给 Codex 自动审核，范围包含 KIE 之外的本项目操作”明确答复“允许本项目自动审核”，因此 `.codex/config.toml` 保存 `approvals_reviewer = "auto_review"`。该默认由自动审核处理符合条件的请求，沙箱、预算、模型限制和托管安全要求继续生效；高风险、超出授权或审核未通过的操作仍可能需要人工确认。

新会话需在受信任的项目目录加载该设置；会话显式权限、启动参数或托管要求可覆盖项目默认，当前有效模式以宿主为准。完整文件复制可带上 `.codex/config.toml`；现有 `workspace-export` 不复制该目录，也不导出本机 KIE 授权，使用干净导出包时需在目标宿主初始化一次相应设置及拥有者授权。

## 统计范围

`timing RUN` 和batch-status读取state/timing：自动记录解析、计划、渲染、抽证据、质检、上传/建任务/查询/下载及共用OCR/ASR/分离/混音/底片脚本。失败也计时；不存提示词、媒体、密钥或签名URL。

阶段数字包含子步骤，不能将外层render与内层ffmpeg相加。报告另给顶层工作秒数、合并重叠区间的观察墙钟、首末跨度和未观测间隔。Agent思考、人工评审、用户等待和旧临时脚本没有自动细分，间隔不能归因为OCR或模型慢。杀进程造成的未完成阶段没有完整时长，不伪造历史统计。provider_seconds继续以原始供应商回执为准。

## 文字识别与源解析复用

`codex-packet RUN --stage recognize` 提供实际图片和项目知识，由 Codex 看图完成实例识别，再用 `codex-result` 登记真实观察。`bin/ocr.py RUN` 是同一工作包的兼容入口。登记成功不代表实例覆盖、翻译或质量已通过，缺失观察继续 pending。

源解析库可复用已核验的源帧和历史 OCR 观察；复用仍需核对当前源哈希及覆盖范围。新识别不调用 RapidOCR 或 GLM，具体合同见 [文字识别](ocr.md) 和 [模型分工](../contracts/model-routing.md)。
