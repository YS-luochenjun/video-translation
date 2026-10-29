# Fireplay需求界面自动本地化对接

第一阶段已实现按需求编号接入，操作规范见 [按编号承接](../agent/workflows/fireplay-intake.md)。队列入口为 `fireplay-pull SPEC`（真实用户指定编号或筛选范围，完整分页后P0排序），逐需求入口为 `fireplay`、`fireplay-source`、`fireplay-chat`、`fireplay-start`、`fireplay-return`、`fireplay-dispatch`、`fireplay-receipt`、`fireplay-status`；本地 MCP 桥提供 `localizer_fireplay`。用户给编号后，当前宿主 Agent 查询连接器、处理回执并继续制作，不要求用户手动下载上传或填写内部 JSON。脚本不自带平台登录，也不直接启动 Codex 推理。

初次接入实测曾对截图九条需求分别核验summary/brief、目标语言及原片查询，10条原片已真实下载、探测媒体并绑定哈希（051含2条）。每个需求已建立自己的聊天及账本，生产进度以该需求实际run和平台回执为准，不将接入验证称为制作或回传完成。详细回执保存在本地work/state。

按用户最新要求，每个需求使用独立用户聊天，标题为需求编号，管理该需求的全部原视频和全部语种；多个原片用编号-1、编号-2区分文件/run。P0优先只影响冲突资源分配，P1并行继续制作，不等待P0完成。聊天ID、语言run、共享请求预算、需求内容版本和回传outbox均持久登记。未知创建/写入结果不能自动重试。当前支持按实际发布审查可提交的完整译片上传、入库和绑定；不自动改需求状态，不回投放。平台AI独立素材通道、长期队列、原子认领和后台调度仍是后续能力。

用户2026-10-27最新纠正上传流程：使用config/fireplay-youtube-routing.json的platform_managed模式，按固定话术入库、共享需求组、请求YouTube自动上传、打语言/产品tag并绑定。不再以账号/任务组显示作为上传门禁，也不追踪YouTube后续进度。unknown恢复原素材回执，不重复入库；历史异常如实保留。

## 可复用能力

- 需求界面使用requirement_list读取范围、状态、版本、素材类型、语种、数量和执行权限，再按ID用blind_brief读取当前需求与来源描述。顺着返回游标翻页，不能把一次列表当完整队列。
- 本地视频≤50MB时，目录中的material_r2_upload_from_bytes支持字节上传，返回publicUrl/resourceId；再material_upload_from_url入库，取得material_id。普通视频与YouTube上传任务分别判断，不把R2成功冒充YouTube任务完成。大文件走平台支持的预签名/网页上传链路。
- 用requirement_bind_materials将真实material_id挂到对应需求；canBindMaterials与canUpdateStatus是不同权限。requirement_update_status使用已查询的合法状态和base_updated_at，防止覆盖别人的更新；完成状态可能触发通知，须在明确的自动回写授权内执行。
- “需求界面”和“设计订单”是不同对象。order_accept只接pending设计订单，不能套到需求记录上。需求认领/指派需先核对该记录的编辑能力、所属组和并发机制。

## 项目已保存的运行约定

1. 用户指定需求编号或组/日期/负责人等实际范围，宿主发现当前工具定义后拉取summary，逐页保存真实回执，排序并逐条读取blind_brief、下载所有原片。来源、语种缺失或冲突时仅该需求转待补信息，其他需求继续。
2. 身份沿用宿主Fireplay连接器，需求权限按实际读回。设计师按[执行人归属规则](../knowledge/rules/fireplay-designer-attribution-v2.md)查询：除罗晨钧、邹彬外的当前执行人均填写；自行核验真实成员及用户ID/DID并读回二创归属，无其他人员才可留空。不向用户索要内部ID，不扩大素材公开范围。
3. 当前用户已指定固定提交动作：审核后入库、共享到需求组、开启YouTube自动上传、语言及1至2词产品tag、编号加语言命名，最后绑定需求。配置原文在config/fireplay-intake.json，视频聊天prompt自动携带。素材详情读回验证共享/tag/名称，YouTube后续进度交平台，不额外轮询；入库成功不等于YouTube完成，整项交付须完成全部原片/语种的真实绑定读回。有瑕疵本地输出不等于质量通过；用户已允许有限条件下做到最好的完整正式成品带普通不合格回传，实际发布审查与内部质量分开；普通瑕疵数量不单独阻断，严重损坏或不完整仍阻断。
4. KIE同意与来源已持久保存到config/fireplay-intake.json.kie；对用户明确交办的需求，fireplay-start追加独立授权绑定，包含必要媒体传送。工作区automatic_use=true且在现有模型/预算内时直接执行，不逐聊天重复询问。各需求按自己的去重语种建立账本，不合并跨需求额度、不因续作重开，未交办列表项不启动付费制作。
5. 当前由宿主Agent按用户请求执行；每60分钟应用定时唤醒主控的监控流程已接入，见agent/workflows/fireplay-monitor.md。webhook及独立服务器常驻服务仍属后续能力。P0/P1并行推进受真实资源和服务并发限制，冲突时P0先用，不让P1等全部P0结束。

## 后续队列能力

接入层已绑定需求内容版本、源哈希、语种和run；下一阶段仍需平台可验证的原子认领/版本冲突检查，避免人机或多worker抢同一需求。内容修改保留旧稿件、账本和快照，阻止自动覆盖；优先级、负责人、状态及自身回写时间不单独触发重做。

上传/入库/绑定必须按阶段恢复，未知结果先查询，不重做模型或盲目重复上传；普通入库不能假设存在幂等键。外部回执与真实成片哈希存入run的external-submission记录，记录操作者、素材ID、需求ID及上传任务ID（如有），完成后maintain RUN --close。失败须留待恢复/待人工处理，不能因文件已上传就标完成。

字体环境已接入Mac真实家族及TTC字面，见[字体说明](fonts.md)：doctor可验证中日韩、泰语、印地语、阿拉伯语及拉丁/西里尔文字的常规/粗体样例。正式制作仍按实际稿件检查缺字和成片；明确指定但缺失的字体不自动替换。macOS系统Python 3.9不能加载已安装的3.12二进制依赖，宿主应选用doctor验证过的解释器。需要宿主Agent持续执行观察、翻译、图片与审核；工作包不等于推理完成，应用定时任务状态按state/fireplay/monitor中的真实回执核对，不宣称独立服务器已部署。真实回传仍须用正式审过的样片验证归属、上传传输、绑定读回及权限；不能用本地mock冒充线上闭环。

当前收尾约定：Fireplay入库、共享、标签、需求绑定及YouTube真实初始受理核验后即完成经验收尾，不再追踪后续上传进度；排队、限额和向量化交给Fireplay。尚无初始受理证据的历史素材沿原素材ID补建/恢复上传，已受理素材不为缺链接重复入库。机器政策为config/fireplay-publication.json.completion；[自动提交与经验收尾](../knowledge/rules/fireplay-completion-recovery-v4.md)与新增[初始受理规则](../knowledge/rules/fireplay-youtube-enqueue-verification-v1.md)结合使用。KIE核查仅用API和本地日志，访问限制读取config/kie-access.json。

## 已有制作的续作与结案

平台状态变为done不自动重做。对用户明确要求的未交付续作，按执行合同登记真实来源、当前内容版本和continuation决定；复用已有制作成员、账本、原outbox及待交语种，并重查绑定权限。只更正数量时，`fireplay_revision.quantity_correction`要求原稿、原片范围、语种与one_per_locale解释不变，当前数量等于已登记原片目标组合数，且显式审阅旧版本并保留快照；不借数量修正追加素材或额度。回归入口为`tests/test_fireplay_quantity_review.py`。

本地分批绑定齐全后，还须用真实当前delivery视图执行`fireplay-completion-check`，再`fireplay-close`保存本地结案回执；不修改平台需求状态。`fireplay_followup`维护已派发负责聊天的租约：unknown先核对原发送，sent到期须读取真实聊天状态再有界恢复，不能据消息已送达推断制作完成，也不能由此重发未知付费任务。完整参数和执行顺序仍以[接入](../agent/workflows/fireplay-intake.md)及[巡检](../agent/workflows/fireplay-monitor.md)为准。

## YouTube初始受理与历史补传（2026-10-29）

项目原固定话术已经要求开启自动上传，但此前执行器把R2直传入库成功直接记作requested_not_verified，没有检查任务是否真正建立。实际MCP请求虽含VedioSouce=YouTube，返回素材ID与R2地址仍不足以证明入队；本地缺少这一核验是本次已确认的实现问题。远端内部为何未建任务仍须平台证据，不能从本地参数推断。

新门禁将material_id、当前video_resource_id、真实task_id/受理状态或已有YouTube链接绑定原成片哈希。`fireplay-youtube-handoff`只登记实际平台证据，不调用或重发上传。缺少受理时保留原入库与绑定，巡检派发enable_youtube_upload；completion-check和close保持未完成。完成初始受理后不持续轮询后续进度。

本次只读素材审计：当前上传者罗晨钧共217条视频，154条有链接，63条无链接。原始分页、详情、任务查询和补传清单存本地state/fireplay/youtube-recovery-20261029；没有链接不等于全部已失败。仅通过支持的已有素材上传入口恢复，避免重复素材。现行要求见[YouTube受理规则](../knowledge/rules/fireplay-youtube-enqueue-verification-v1.md)。
