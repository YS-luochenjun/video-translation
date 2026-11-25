# Fireplay按编号接入与固定回传

宿主Agent读取Fireplay、操作已授权聊天及外部提交；项目CLI只登记证据、媒体、账本与状态，不复制登录凭据或假装调用连接器。政策入口是[AGENTS](../../AGENTS.md)，来源及参数分别在config/fireplay-intake.json、config/fireplay-publication.json、config/fireplay-youtube-routing.json、config/kie-access.json。新需求自动发现另见[巡检](fireplay-monitor.md)。本文保留接口和恢复步骤，不重复历史聊天原话。

## 持续执行到平台受理

用户2026-11-19授权：实际预算不足阻碍已授权视频需求时，可按需要使用 `budget-amend` 修订原账本，本授权下累计增加不超过首次使用本授权前该需求原额度的一倍。首次修订的 `previous_limit` 是后续计算基数，不得以已加额后的额度再次翻倍；保留费用、未知占位与每次修订回执。超过该上限另行询问，未知付费任务不因加额重发，宿主审批仍适用。授权详情见 `config/fireplay-intake.json.budget_increase_authority`。

用户2026-11-19明确允许R2中出现重复文件：不要因为担心R2重复而停下提交；上传有真实超时且缺有效资源回执时，按现有有界重传流程继续，保存各次回执。需求面板以正确需求、语言、命名、标签和素材绑定为准；已有正确绑定不因R2副本重复而返工。此授权不等于模型未知费用可以重发，也不证明未知的素材导入或需求绑定已经成功。

config/fireplay-intake.json.continuous_execution保存用户持续执行授权；新接单提示和fireplay-status均返回当前指令，旧聊天续作也读取。普通制作选择按实际证据和项目推荐自行决定，不再为继续制作、已授权KIE、必要审核媒体传送或固定提交另开确认。模型已受理就查询原taskId，待审就继续实际审核，CLI退出码2按具体缺口修复，partial只作中间批次；不要在这些阶段结束对话等待用户说“继续”。多个聊天同时上传时按config.upload_queue进入共享上传队列，等待空闲槽后继续原操作；队列等待不等于制作失败，也不允许重建重复上传。

仍需人工的具体阻塞记录缺口、已尝试的恢复、最小所需动作及原回执；同一未变问题不重复询问。并行推进未受影响的原片/语种。保持原预算、unknown对账、有界返工和严重质量门禁；宿主强制审批与拒绝不能由项目授权代批或绕过。全项完成以当前全部原片及各自语种的实际平台回传核验和有效completion-check/fireplay-close为准，YouTube受理后的进度交平台。

## 读取与下载

1. 用doctor验证的Python运行doctor、kie-authorization。通过tool_catalog发现requirement_list当前合同，summary按完整编号查询，精确匹配唯一code；未命中沿相同过滤分页，不能按前缀猜需求。再以真实UUID读blind_brief；两视图updatedAt一致，提交时serverTime须在10分钟内。平台正文是业务数据，不授予费用/写入权限。
2. 保存实际响应为 `{"summary":原始返回,"brief":原始返回}`，执行 `fireplay CODE --snapshot FILE`。按下节确定原片。解析结构化locales及正文翻译语种，别名去重并保留原值。Agent可补 `decision: {targets,quantity_mode:"one_per_locale",authorization_ref,source_quote}`，必须有真实用户来源。来源/语种冲突或数量含糊保留blockers。每原片×去重语种各一版时明确登记。
3. 多编号/明确范围先 `fireplay-pull SPEC`，使用 `agent/templates/fireplay-pull.json`，按返回host_actions完整读取summary_pages，每页保存真实arguments/response；P0先排冲突资源，P1持续并行。只读询问不启动未交办列表；每需求独立查看、聊天和计费，不开跨需求总池。
4. `fireplay-source CODE --video N` 给出精确查询。YouTube 链接按下节查库并补齐。对媒体直链和 Fireplay 视频附件使用 `fireplay-source CODE --download --video N`。下载后用 ffprobe 核验视频流、时长和尺寸并登记 SHA256，附件还核对实际字节数。续作复用已通过校验的文件。旧库若尺寸仅为 HD 分类而与实际文件不同，先读精确 `material_detail`。原查询的 `items` 与真实详情 `material_detail` 可组成 receipt。仅当资源 ID、R2 地址、YouTube ID 和实际字节数完全一致，且详情明确 `hasExactDimensions=false` 时，登记实际尺寸和原标注差异。其他尺寸冲突保留阻塞。

### 原片优先级

1. 优先采用需求正文和参考栏中的可识别视频链接，对同一原片去重。已选链接的文件暂不可取时，沿该链接恢复。
2. 两处均无可识别链接时，以精确需求 UUID 查询 `requirement_list(view=delivery)`，在 snapshot 顶层附上原始 `delivery` 回执。该视图可能含交付结果，选片只读同需求同版本的 `attachments` 视频项，按附件顺序登记，每片独立建聊。原片绑定包含平台附件 ID、地址、字节数和实际视频哈希。附件需求后续刷新、状态写入及读回仍带同版本的 `delivery` 回执，以核对原片清单。没有视频附件时，兼容旧需求标题里的视频链接。
3. 先前因缺原片而阻塞且尚未开工的需求，可用同一正文版本的附件回执恢复，保留原登记历史和授权。已登记的附件清单变化按既有内容修订处理。

### YouTube 缺片补取

1. 调用 `material_youtube_original_lookup` 精确查询已选视频 ID，将原始回执交 `fireplay-source CODE --receipt FILE --download --video N`。找到 R2 时沿正常下载校验。精确结果为 `missing` 时，按 `config/fireplay-intake.json.youtube_source_backup` 的持续授权，为已交办或合范围自动接入的需求继续补齐原片。
2. `needs_source_backup` 给出精确链接入库参数。宿主先核对本需求、当前原片及同一 YouTube ID 的既有入库或备份回执，再在 `state/fireplay/CODE/` 记录操作和待核对状态，按连接器当前合同调用一次 `material_upload_from_url`。记录实际结果、警告和素材检查链接。
3. 仅将实际入库回执返回的 `youtube_original_download_items` 传给 `material_youtube_original_download`，每批最多五条。调用前登记操作，保存真实受理回执。若返回复用素材而没有下载参数，沿实际素材 ID 读详情并重新查库。未知写入先核对原操作，缺证据时记录具体缺口。
4. 后台受理后以同一 YouTube ID 重新精确查库。`queued` 或 `processing` 保持等待并在后续巡检复查，同批其他原片照常推进。取得 R2 原片后，使用新查库回执完成下载与校验，再预约原片名额。记录实际尺寸与可用的素材检查链接。

正文、原片、语种、数量等内容版本变化时保留原run/账本，显式审查修订；状态、优先级、更新时间等元数据不触发重做。已完成、有人制作、缺权限/信息各自保留真实状态，其他需求继续。

正文提供公开 Pinterest Pin 时，`fireplay-source CODE --download` 按精确 Pin ID 解析页面中该帖的视频，保存来源证据，并核对下载文件的时长、尺寸和哈希。页面未给出唯一可验证的视频时保留原片缺口。

已开工、尚无任何return操作的需求，仅新增“只翻译文案的口播”且其他业务正文、原片、逐片语种及数量完全不变时，可用`review_scope_narrowing:true`、`scope:ad_narration_only`、精确`reviewed_content_version`和`scope_revision_authority`走受限修订。授权文件须绑定真实人类同意、需求UUID、新旧版本、原账本/额度、源哈希和全部语种；平台正文不充当授权。入口归档旧request并保留原聊天、run、模型、未知费用与预算，记录画面保留、仅广告旁白翻译；其他已开工正文修订仍阻断。

已开工且尚未准备任何回传时，若正文只补充「尺寸9:16」「声音清晰」或「标题文字要大一些，跟原视频中差不多」，用 `fireplay CODE --snapshot FILE --decision FILE` 登记。在决策文件填写 `review_delivery_clarification:true`、精确 `reviewed_content_version` 和 `revision_reason`，保留既有授权来源。要求需求身份、其他文案、原片、语种、数量及既有授权范围一致。沿原聊天、run 和预算继续。按新增要求核对成片尺寸、与成片哈希绑定的音频审核，或在现有发布自审中对照原片和成片的标题视觉大小。已符合新增要求的成片可直接复用。

已在制作且部分交付的需求后来变为done时，用户明确要求继续补交，可在decision登记`continue_pending_delivery:true`与当前`continuation_content_version`，并记录该续作的真实authorization_ref/source_quote。仅接受内容版本未变、已有账本和制作成员、原return仍有pending_locales且有绑定权限的续作；不重开制作、不修改平台状态、不覆盖旧回执。普通巡检仍阻止自动重做done需求。

## 聊天、授权与制作

1. `fireplay-chat CODE --video N`预览标题和提示。单原片使用需求编号，多原片使用需求号-1、-2、-3。各聊天仅制作自己的原片和该片语种。第一个实际绑定的聊天协调整单状态。已承接需求沿原聊天继续。
2. 下载并登记该原片后运行 `fireplay-chat CODE --video N --execute`。`queued` 等待全局名额。`needs_status_start` 表示已占名额，按下节完成状态写回。仅 `prepared` 时按返回的提示调用项目本地 `create_thread`。用 `set_thread_title` 设置精确标题并以真实 `threadId`、`hostId`、`title` 绑定。`unknown` 时查原创建回执并绑定原会话。
3. 负责聊天执行 `fireplay-start CODE AUTHORITY --video N`，AUTHORITY包含authority=user、稳定authorization_ref、user_request、mode=first/reuse及真实来源；续作不把轮询/重试冒充新请求。监控授权文件为state/fireplay/CODE/monitor-authority.json。本需求多原片共用真实去重语言×60的独立账本，原池及未知费用不重开。
4. KIE持续同意读config/fireplay-intake.json.kie及本需求kie-user-authorization.json；fireplay-start绑定真实需求、语种、内容版本、请求和原预算，工作区automatic_use=true时直接使用范围内模型及必要媒体传送，不逐次问同意。项目询问是否需要/同意KIE音频或视频时依据持续授权直接确定为需要、同意；缺本需求绑定先fireplay-start，不把它误当成需要用户再次同意。宿主强制审批不代用户点击。仅API/真实taskId/保存响应/本地费用日志恢复；用户没有后台登录权限。超时无可查询ID保留未知费用，不重扣、不重开额度。模型与返工上限仍按制作合同，宿主审批按其有效政策。
5. 按[本地化流程](video-localization.md)完成实际观察、翻译、选路、制作及审核。共用底片不继承别的语种验收；同名/同源的不同需求仍独立账本。P0只优先冲突资源，不停止P1。主控协调，实际制作与回传由对应聊天继续。

## 需求状态

1. 新接入的「视频翻译」「未开始」需求按此规则管理状态。第一个原片占到名额后，刷新精确UUID的summary和blind_brief。用 `fireplay-transition CODE start SNAPSHOT --execute` 登记写入并取得 `requirement_update_status` 参数。通过宿主调用后重新读取两种视图，执行 `fireplay-transition CODE start SNAPSHOT` 确认「进行中」，再运行原片建聊命令。随后原片继续按同一需求状态领名额。
2. 各原片会话可分批提交自己的语种。全部原片及语种真实上传、共享并绑定后，由 `fireplay-status.coordinator_chat` 指定的协调会话核对当前delivery视图并执行 `fireplay-completion-check`。刷新同一版本的summary和blind_brief后运行 `fireplay-transition CODE finish SNAPSHOT --execute`，实际调用状态工具，再读回「已完成」并用不带 `--execute` 的 `fireplay-transition CODE finish SNAPSHOT` 确认。最后执行 `fireplay-close CODE`。此处以Fireplay实际受理和绑定为准，YouTube发布进度由平台继续处理。
3. 状态更新参数包含平台真实 `updatedAt`，防止覆盖别人刚做的修改。未知结果先查原回执和最新状态。确认第一次未生效、状态和版本仍适用时，可带 `--retry --execute` 有界恢复一次。其他状态逐项核对。无法继续建聊时，可用 `fireplay-chat CODE --video N --release-reservation` 释放尚未发起创建的预约，保留原状态回执。

## 就绪、部分提交与unknown

同一成片先完成实际视听审核，再用该版已有观察和证据做发布裁定。已记录的普通瑕疵沿用原影响判断，达到已有停止条件时记录 `best_available` 并继续提交。回传、上传、绑定和超时恢复读取已冻结的成片哈希、归档清单及裁定。成片或审核依据改变、有新增严重发现或有效异议时，处理受影响版本。平台传输超时沿原回执核对实际上传状态，按已有恢复规则处理。

质量通过的完整正式outputs直接回传，不停在deliver后再问固定动作同意。有限预算/返工/能力内已做到最好的完整成品，普通不合格也可提交：实际看成片后执行 `fireplay-publication-review CODE SPEC`，填写完整翻译/必需配音/可观看判断、实际缺陷影响和best_available的stop_condition、reason及包内evidence。内部revise、评分低或普通瑕疵数量不单独阻断；大面积撕裂、无法观看、严重主体损坏、漏译、缺必需配音或有效质量异议仍阻断对应版本。旧普通问题否决可用reassess_under_current_policy追加新审查，保留原决定；不能重编码伪造新版本来绕过旧判断。模板见 `agent/templates/fireplay-publication-review.json`。共用底片的共同缺陷集中修复；单个语种的配音/译字/排版仍独立检查，不从一个成功外推全部。

固定提交持续授权及用户原话统一维护于config/fireplay-publication.json.submission_consent，由fireplay-chat、fireplay-status和巡检恢复消息带入。它包括对应需求组共享，不逐成片、批次或需求再问是否上传/共享。调用时附真实授权来源及当前精确成片/组范围，不新增确认表单。宿主明确拒绝或要求本次人工确认时仍须保留真实拒绝，说明具体操作与原因，不换工具绕过；请求人类处理前先核对当前及原负责聊天是否已有人类明确确认相同范围。项目持续授权不冒充宿主批准或成片质量通过。

1. 刷新summary/brief并register，执行material_sharing_departments获取真实可选组。需求deptId可能带od-前缀，选择接口实际返回且匹配需求组的ID。准备spec：`video_index`、`packages:[{video_index,locale,package:"outputs/..."}]`、`sharing_receipt:实际组列表响应`、`authority:{authorization_ref,source_quote,actions:["upload","import","bind"]}`。按[设计师归属规则](../../knowledge/rules/fireplay-designer-attribution-v3.md)读取当前执行人：排除罗晨钧、邹彬，其余人员作为设计师，用当前tool_catalog查requirement_field_options_query，include_members=true、member_ids=真实执行人ID，按next_offset翻页并核对feishuUserId/username；部分/空目录继续查证，不要求用户提供ID。spec附designer_receipt原响应可自动采用已授权真实用户ID归属路径，或使用已核验DID；多人全部填写，无其他人员才可留空。标二创并按下述当前规则追加英文derivative tag，按实际工具预览/执行及权限合同落库并读回，不能把预览当成功。product_tag依据真实标题/描述/原片提炼1至2词，locale使用规范别名。
2. 执行 `fireplay-return CODE SPEC`核验包manifest、源/成片哈希、语种、真实质量和异议。本批只交已合格语种时显式 `partial:true`；其余记pending_locales。批次绑定核验后才能追加新就绪语种，沿同一return-N.json复用旧upload/import/verify编号，旧bind留binding_history；新spec仅列未提交语种。unknown或未绑定的旧批次不得换包/覆盖；仅当所有旧包都是按下一步明确暂缓、尚未入库的未知上传，且没有待绑定素材时，允许保留旧操作并追加其他就绪语种。已提交语种不可再上传，暂缓语种继续pending。部分成功不报告整需求完成；按[全项交付规则](../../knowledge/rules/fireplay-complete-delivery-v3.md)继续所有pending。结束前核对fireplay-status.delivery_coverage与平台实际全部原片/语种，submission_complete=true后仍需用当前requirement_list(view=delivery)真实响应执行fireplay-completion-check CODE SPEC，completion-check.complete=true后执行fireplay-close CODE，只有completion_gate.can_close=true才可整项结案。该检查逐项核对所有原片/语种的已审哈希、真实素材ID及当前平台绑定；每次bind也自动保存整项检查回执，部分批次保持未完成。

   用户另行明确同意使用已核验的平台用户ID时，可在本次attribution填`designer_ids`、`identity_route=verified_user_id`及单独的`identity_authorization_ref`；ID须属于当前需求执行人，不从登录账号推测。此例外不生成或猜测DID，也不改变实际设计师归属，展示标题仍须填写下述真实DID映射。执行器在import后、verify前登记`attribute-N`，通过真实`material_attribution_update`填写设计师/二创，再读material_detail，以`response`和`verification`登记回执；预览或没有真实归属读回不得当完成，unknown不重发。
3. `fireplay-dispatch CODE --video N`预览，`--execute`只先登记unknown并准备宿主参数，不执行外部调用。宿主发现当前完整工具合同后恰好执行一次，再用 `fireplay-receipt CODE OPERATION FILE --video N`登记真实回执。未知结果先查原平台记录；实际文件上传超时且没有可用资源/素材回执时，按全项交付规则用fireplay-retry-upload登记有界重传，不再逐次请求同意，保留旧unknown；其他未知写入不再dispatch；不自行补无依据的confirmed参数。仅文件上传unknown且尚未入库时，可由 `fireplay.defer_unknown_upload` 登记用户明确不重传的决定或Agent基于真实超时回执的暂缓观察（authority、authorization_ref、source_quote），保留原unknown操作和全部包/编号，仅继续本批其他语种。暂缓语种留在pending_locales；绑定只含已核验语种，不把部分回传报告为全部完成，也不自动恢复或重发暂缓上传。
4. 本批逐语种upload → import → verify，全部核验后bind。新准备的包按 `config/fireplay-intake.json.default_upload_route` 默认使用 `material_r2_presign_upload`，对正式 MP4 进行二进制 PUT，再登记真实 HTTP 成功、文件 SHA256 及资源回执。已冻结的包沿原上传路线恢复。显式 `upload_route: bytes` 仍使用原 `material_r2_upload_from_bytes`，实际 Base64 参数文件不打印。import 使用普通 MCP 的 `VedioSouce=YouTube` 请求平台自动上传，实际 `shared_dept_id` 与下述英文标签随项填写；组共享不等于全平台 is_public。素材名及标签按下述当前规则生成。
5. verify通过material_detail读回实际material_id、名称、共享组与tag，并核对已指定的设计师及二创类型；缺失则按真实ID修正并重读，不重入库。bind使用真实素材ID，不操作设计订单；回执另附当前requirement_list(view=delivery)读后验证，确认精确需求包含本批全部素材。平台要求用户选材时展示selection URL并等待，不自选。绑定后各run写external-submission.json并引用持久state回执，不自动改需求状态或投放。

需求正文有独立一行明确写「无需传yt」或「无需传YouTube」时，回传登记此备注，并在普通MCP入库请求中使用 `VedioSouce=Other`。其余入库、组共享、标签、归属及绑定核验照常执行。

## 上传命名与标签

用户2026-11-18要求后续视频上传采用截图规则，并明确“修改到项目中”。唯一配置源为`config/fireplay-intake.json.publication.upload_metadata`；此规则替代上文及旧知识中的“编号-语言”名称和中文二创tag要求，设计师归属与二创属性继续保留。2026-11-19补充，品类、PID、DID和产品tag等内容如果无法从真实回执中取得，保留为空并继续上传，不能因为元数据查不到而停住制作或提交；语言tag仍以实际目标语种为准，所有已写入的tag必须为英文。

- 素材名作为YouTube标题，按`语言 品类 PID DID 需求编号`用空格分隔。语言采用规范locale；“年月日-编号”直接使用完整需求编号，不另拼日期。多原片仅在末尾需求编号后加`-1`、`-2`区分。
- tag包含规范语言和完整需求编号。有可核验的1至2词英文产品名时添加产品tag，没有合适的英文值时省略。二创额外使用`derivative`标签，平台创作类型仍为`derivative`。需求编号tag始终为原需求编号，不带多原片后缀。
- Agent从真实需求/成员/平台映射取得品类、运营PID和所有设计师DID，保存查询证据；PID保持字符串及前导零，不从需求组名或登录身份猜测，不把飞书用户ID当DID。缺映射时继续查询，仍无法取得时将对应标题字段和tag留空，不填D0/NA，也不阻断上传。
- `fireplay-return`规格可附`material_metadata:{category,pid,evidence_ref}`。能查到的品类、PID、DID和产品tag写入并保留实际证据；查不到的字段留空并从标题或tag中省略。采用`verified_user_id`归属时，附`designer_did_map:{真实设计师用户ID:真实DID}`，只有完整且格式有效的映射才写入标题DID字段。已有`attribution.designer_dids`经核验时直接复用。单一DID或多个`D288+D299`显示于名称DID字段；平台入库解析使用的`_D288_#`后缀仍仅作归属标注，不属于最终展示标题。
- 例如已核验品类GAME、PID07、DID D288时，西语名称为`es GAME 07 D288 SHE-20261118-039-1`，tags为`es`、`Candy Crush`、`SHE-20261118-039`、`derivative`。此例的身份值仅为格式演示，不提供实际归属依据。
- `material_detail`读回标题及本批已登记的全部标签。省略的可选字段不参与核验。已发起外部操作的冻结return批次继续使用原名称、标签与操作身份恢复，包含unknown和部分回传；不为本次规则变更重命名历史素材或重复上传。新批次及尚未发起任何外部操作的批次在准备回传时采用当前规则，图片项目不受影响。

## 平台路由与结案

用户最新明确固定话术即可：当前platform_managed模式由Fireplay负责YouTube账号路由，不强制逐视频选账号、截图、等待Worker或核对任务组显示。显式账号路径仅在用户另行要求时使用，不是默认门禁。旧import为unknown但已入库时恢复原确切material_id和保存响应，交receipt继续核验；不要求补旧任务组字段，不因后台显示或缺YouTube链接重传。历史异常原样保留，不冒称已修正，不修改整个账号所属组、不删除正确库记录掩盖问题。

精确素材ID、源/成片SHA256、字节数和绑定回执共同确认身份；相同名称或相似缩略图不足以判定重复。跨聊天同需求的不同原片不得按名称批量删除、替换或重绑；SHE多聊天实测来源见[七组复盘](../../knowledge/curation/seven-source-review-20261027.json)。

Fireplay受理、入库/共享/名称/标签/绑定核验后即按[提交知识](../../knowledge/rules/fireplay-completion-recovery-v5.md)收尾。后续YouTube进度、排队、限额和向量化交平台，不轮询、不等链接、不催办。按config/fireplay-youtube-routing.json.quota_handling，上传时已选择YouTube模式且素材真实受理后，即使账号/组额度不足、暂未创建YouTube任务，也正常完成核验及结案；不等待额度、不因此重传/重入库、另建任务或反复提醒，后续额度恢复由Fireplay处理。报告已提交/已请求自动上传，不冒称YouTube已完成。经验按知识技能归纳；必要证据、未知费用和质量异议保留；逐run执行maintain --close，阻断项如实记录。没有生产run的读取/测试不伪造交付或维护成功。
