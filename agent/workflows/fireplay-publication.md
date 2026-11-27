# Fireplay 上传、绑定及恢复

总入口见 [fireplay-intake](fireplay-intake.md)。

## 就绪、部分提交与unknown

同一成片先完成实际视听审核，再用该版已有观察和证据做发布裁定。已记录的普通瑕疵沿用原影响判断，达到已有停止条件时记录 `best_available` 并继续提交。回传、上传、绑定和超时恢复读取已冻结的成片哈希、归档清单及裁定。成片或审核依据改变、有新增严重发现或有效异议时，处理受影响版本。平台传输超时沿原回执核对实际上传状态，按已有恢复规则处理。

远程主备音频复核均因模型调用故障失败时，按[音频异常交付](../contracts/audio.md#独立配音与转写)使用已生成的完整 TTS 并正式归档、继续回传；不等待模型恢复或强制本地复核。

新需求及驳回返工（包括直接修复旧附件和自定义合成）在代表片扩语种前、实际成片发布审核时执行[新制作与返工的双域审核](../contracts/quality.md#新制作与返工的双域审核)及[标题与转场审核](../contracts/quality-visual.md#标题与转场审核)。驳回返工的声音和画面按[局部返工与素材复用](quality-feedback.md#局部返工与素材复用)处理。实际发现的缺陷按影响优先级、有界返工和既有发布政策处理。

质量通过的完整正式 outputs 直接回传。有限预算、返工次数或能力内已做到最好的完整成品，普通瑕疵也可提交。用同一成片已有的实际视听观察填写 `fireplay-publication-review CODE SPEC`，记录完整翻译、必需配音、可观看判断、缺陷影响和 `best_available` 的停止原因及包内证据。成片哈希和审核依据未变且无新增异议时，沿用该次观察。内部 revise、评分低或普通瑕疵数量不单独阻断。大面积撕裂、无法观看、严重主体损坏、漏译、缺必需配音或有效质量异议仍阻断对应版本。旧普通问题否决可用 `reassess_under_current_policy` 追加裁定并保留原决定。不能重编码伪造新版本来绕过旧判断。模板见 `agent/templates/fireplay-publication-review.json`。共用底片的共同缺陷集中修复，每个语种的配音、译字和排版都需检查。

次要界面切镜残影按[视觉标准](../contracts/quality-visual.md#默认实用视觉标准)审核。符合容差时在 `assessment.defects` 写 `kind:"secondary_ui_cut_residue"`、`severity:"minor"`、`instance_id`、秒数 `interval:[起点,终点]` 和实际观察 `description`。逐项确认 `nonessential_ui`、`momentary_at_cut`、`target_text_present_and_readable`、`no_legible_source_word`、`no_normal_playback_impact` 均为 `true`，在 `assessment.evidence` 引用包内 `final.mp4`。有对应去字观察时，仍按实际填写 `source_text_removed` 和 `visible_coverup`。无可见遮盖的该类残影可走普通瑕疵发布，并保留内部质量结论。

固定提交持续授权及用户原话统一维护于config/fireplay-publication.json.submission_consent，由fireplay-chat、fireplay-status和巡检恢复消息带入。它包括对应需求组共享，不逐成片、批次或需求再问是否上传/共享。调用时附真实授权来源及当前精确成片/组范围，不新增确认表单。宿主明确拒绝或要求本次人工确认时仍须保留真实拒绝，说明具体操作与原因，不换工具绕过；请求人类处理前先核对当前及原负责聊天是否已有人类明确确认相同范围。项目持续授权不冒充宿主批准或成片质量通过。

1. 刷新summary/brief并register，执行material_sharing_departments获取真实可选组。需求deptId可能带od-前缀，选择接口实际返回且匹配需求组的ID。准备spec：`video_index`、`packages:[{video_index,locale,package:"outputs/..."}]`、`sharing_receipt:实际组列表响应`、`authority:{authorization_ref,source_quote,actions:["upload","import","bind"]}`。按[设计师归属规则](../../knowledge/rules/fireplay-designer-attribution-v3.md)读取当前执行人：排除罗晨钧、邹彬，其余人员作为设计师，用当前tool_catalog查requirement_field_options_query，include_members=true、member_ids=真实执行人ID，按next_offset翻页并核对feishuUserId/username；部分/空目录继续查证，不要求用户提供ID。spec附designer_receipt原响应可自动采用已授权真实用户ID归属路径，或使用已核验DID；多人全部填写，无其他人员才可留空。标二创并按下述当前规则追加英文derivative tag，按实际工具预览/执行及权限合同落库并读回，不能把预览当成功。product_tag依据真实标题/描述/原片提炼1至2词，locale使用规范别名。
2. 执行 `fireplay-return CODE SPEC`核验包manifest、源/成片哈希、语种、真实质量和异议。本批只交已合格语种时显式 `partial:true`；其余记pending_locales。批次绑定核验后才能追加新就绪语种，沿同一return-N.json复用旧upload/import/verify编号，旧bind留binding_history；新spec仅列未提交语种。unknown或未绑定的旧批次不得换包/覆盖；仅当所有旧包都是按下一步明确暂缓、尚未入库的未知上传，且没有待绑定素材时，允许保留旧操作并追加其他就绪语种。已提交语种不可再上传，暂缓语种继续pending。按[全项交付规则](../../knowledge/rules/fireplay-complete-delivery-v3.md)继续所有pending。`fireplay-status` 显示实际原片及语种覆盖和整单校验门禁。`completion_gate.can_close=true` 时按需求状态流程结案。绑定读回已生成整单检查，涵盖全部原片、语种、成片哈希和素材ID。

   用户另行明确同意使用已核验的平台用户ID时，可在本次attribution填`designer_ids`、`identity_route=verified_user_id`及单独的`identity_authorization_ref`。ID须属于当前需求执行人，展示标题的DID仍按下述真实映射填写。批量入库回执核验后，用默认 `fireplay-dispatch CODE --video N --execute` 合并同一回传批次内已入库、尚未发起归属写入的素材，一次 `material_attribution_update` 写入相同的设计师名单和创作类型。只有一项就绪时继续单项写入。批量回执用 `fireplay-receipt CODE 批次ID FILE --video N` 登记，`response` 放原始写回结果，`verification` 放各素材的真实 `material_detail` 响应数组。身份、归属、名称、共享和标签齐全时复用同一次读回。遇部分成功或结果未知，按 `pending_material_ids` 查对应素材，后续可仅用 `verification` 补登记真实读回。已核验项沿用原回执，未核验项保留待处理状态，整批写入只发一次。

   用户明确授权替换一个已核验语种的绑定时，完整且已结算的原片回传可用单包 `partial:true` 和 `repair_revision:{authority:"user",authorization_ref,source_quote,reason,previous_outbox_sha256,replace_material_id}`。归档原回传，仅重开该语种；其他素材和已核验操作原样复用。绑定调用 `requirement_replace_materials` 前核对真实可见的原绑定；读回必须同时确认新版及其余语种仍在、旧版已解绑。保留旧素材库记录。
3. `fireplay-dispatch CODE --video N`预览，`--execute`只先登记unknown并准备宿主参数，不执行外部调用。多语种优先通过 `--package-index N` 准备各冻结包的文件上传（从1开始），两个及以上语种上传核验后，用 `--batch-import --execute` 登记一次普通平台入库调用；单项或指定账号路由走原入口。以批次 operation.id 用 `fireplay-receipt CODE OPERATION FILE --video N` 登记完整原始批次回执，执行器按照真实 `item_index` 分项核验，失败或缺失项保留unknown，已核验项继续归属及统一绑定。宿主发现当前完整工具合同后恰好执行一次。未知结果先查原平台记录；实际文件上传超时且没有可用资源/素材回执时，按全项交付规则用fireplay-retry-upload登记有界重传，不再逐次请求同意，保留旧unknown；其他未知写入不再dispatch；不自行补无依据的confirmed参数。仅文件上传unknown且尚未入库时，可由 `fireplay.defer_unknown_upload` 登记用户明确不重传的决定或Agent基于真实超时回执的暂缓观察（authority、authorization_ref、source_quote），保留原unknown操作和全部包/编号，仅继续本批其他语种。暂缓语种留在pending_locales；绑定只含已核验语种，不把部分回传报告为全部完成，也不自动恢复或重发暂缓上传。
4. 本批逐语种upload → import → verify，全部核验后bind。新准备的包按 `config/fireplay-intake.json.default_upload_route` 默认使用 `material_r2_presign_upload`，对正式 MP4 进行二进制 PUT，再登记真实 HTTP 成功、文件 SHA256 及资源回执。已冻结的包沿原上传路线恢复。显式 `upload_route: bytes` 仍使用原 `material_r2_upload_from_bytes`，实际 Base64 参数文件不打印。import 使用普通 MCP 的 `VedioSouce=YouTube` 请求平台自动上传，实际 `shared_dept_id` 与下述英文标签随项填写；组共享不等于全平台 is_public。素材名及标签按下述当前规则生成。
5. 普通 MCP 入库有明确逐项成功及真实素材 ID，并且请求已发送正确名称、共享和标签时，执行器复用入库回执。已有完整归属读回时也复用该回执。回执缺失、警告或字段冲突时通过 `material_detail` 补查对应素材，必要时按真实ID修正并重读。绑定使用真实素材ID；在同一需求读回本批素材时同时检查整单覆盖。平台要求选材时展示 selection URL 并等待。绑定后各run写 `external-submission.json` 并引用持久回执。

已取得预签名资源但未捕获 PUT 回执时，先查原资源。若完整 GET 为 HTTP 200，且实际读取字节数和 SHA256 匹配冻结成片，可用 `transfer:{completed:true,http_method:"GET",url,http_status,bytes,sha256}` 登记恢复证据，复用原资源，不重传。

正常回传以批次为单位复用已发现的 MCP 工具合同，不逐素材重新查工具定义、需求组或成员目录。需要刷新需求时先取真实 summary；若 UUID 和 updatedAt 均与登记一致，可直接以 `{"summary":实际新响应}` 执行 `fireplay CODE --snapshot FILE`，自动复用原 brief 和附件回执，不更改任何原始时间戳；版本变化才重新读取完整视图。`fireplay-status` 的 `return_context` 显示同需求、同内容、同组及同执行人的共享/成员回执是否可复用；可用时下一批 spec 省略对应 receipt，成员目录超过原有效期仍刷新。保留平台实际预览/确认要求和未知写入恢复，不因减少查询而绕过。平台受理后不等待或追踪 YouTube。

制作和回传可以重叠。需求组、执行人和可用命名字段在渲染或审核期间按现有回执准备。当前已通过发布裁定的语种立即组成可交批次，剩余语种继续审核或修复。普通预签名路线按包登记上传操作，按 MCP 实际支持的多项请求取得预签名结果，使用真实返回的地址并行 PUT，保存逐项二进制上传回执。对已确认上传的多个包批量入库，复用同批归属写回及核验结果，最后统一绑定。失败或未知项沿原操作核对，其他就绪项继续推进。同一批中，某项上传或入库结果未知时，默认派发仍可为已入库的多个素材合并写入归属。批量入库可能回显剥离归属后缀后的正式名称，按被冻结的展示名称核对，实际归属和共享仍按原规则验证。

需求正文有独立一行明确写「无需传yt」或「无需传YouTube」时，回传登记此备注，并在普通MCP入库请求中使用 `VedioSouce=Other`。其余入库、组共享、标签、归属及绑定核验照常执行。

