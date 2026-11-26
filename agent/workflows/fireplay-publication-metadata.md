# Fireplay 命名、标签及平台结案

总入口见 [fireplay-intake](fireplay-intake.md)。

## 上传命名与标签

用户2026-11-18要求后续视频上传采用截图规则，并明确“修改到项目中”。唯一配置源为`config/fireplay-intake.json.publication.upload_metadata`；此规则替代上文及旧知识中的“编号-语言”名称和中文二创tag要求，设计师归属与二创属性继续保留。2026-11-19补充，品类、PID、DID和产品tag等内容如果无法从真实回执中取得，保留为空并继续上传，不能因为元数据查不到而停住制作或提交；语言tag仍以实际目标语种为准，所有已写入的tag必须为英文。

- 素材名作为YouTube标题，按`语言 品类 PID DID 需求编号`用空格分隔。语言采用规范locale；“年月日-编号”直接使用完整需求编号，不另拼日期。多原片仅在末尾需求编号后加`-1`、`-2`区分。
- tag包含规范语言和完整需求编号。有可核验的1至2词英文产品名时添加产品tag，没有合适的英文值时省略。二创额外使用`derivative`标签，平台创作类型仍为`derivative`。需求编号tag始终为原需求编号，不带多原片后缀。
- Agent从真实需求/成员/平台映射取得品类、运营PID和所有设计师DID，保存查询证据；PID保持字符串及前导零，不从需求组名或登录身份猜测，不把飞书用户ID当DID。缺映射时继续查询，仍无法取得时将对应标题字段和tag留空，不填D0/NA，也不阻断上传。
- `fireplay-return`规格可附`material_metadata:{category,pid,evidence_ref}`。能查到的品类、PID、DID和产品tag写入并保留实际证据；查不到的字段留空并从标题或tag中省略。采用`verified_user_id`归属时，附`designer_did_map:{真实设计师用户ID:真实DID}`，只有完整且格式有效的映射才写入标题DID字段。已有`attribution.designer_dids`经核验时直接复用。单一DID或多个`D288+D299`显示于名称DID字段；平台入库解析使用的`_D288_#`后缀仍仅作归属标注，不属于最终展示标题。
- 例如已核验品类GAME、PID07、DID D288时，西语名称为`es GAME 07 D288 SHE-20261118-039-1`，tags为`es`、`Candy Crush`、`SHE-20261118-039`、`derivative`。此例的身份值仅为格式演示，不提供实际归属依据。
- 标题及本批已登记的标签按上文使用现有官方回执核验，需要补证时读取 `material_detail`。省略的可选字段不参与核验。已发起外部操作的冻结 return 批次继续使用原名称、标签与操作身份恢复，包含 unknown 和部分回传。新批次及尚未发起任何外部操作的批次在准备回传时采用当前规则。

## 平台路由与结案

用户最新明确固定话术即可：当前platform_managed模式由Fireplay负责YouTube账号路由，不强制逐视频选账号、截图、等待Worker或核对任务组显示。显式账号路径仅在用户另行要求时使用，不是默认门禁。旧import为unknown但已入库时恢复原确切material_id和保存响应，交receipt继续核验；不要求补旧任务组字段，不因后台显示或缺YouTube链接重传。历史异常原样保留，不冒称已修正，不修改整个账号所属组、不删除正确库记录掩盖问题。

精确素材ID、源/成片SHA256、字节数和绑定回执共同确认身份；相同名称或相似缩略图不足以判定重复。跨聊天同需求的不同原片不得按名称批量删除、替换或重绑；SHE多聊天实测来源见[七组复盘](../../knowledge/curation/seven-source-review-20261027.json)。

Fireplay受理、入库/共享/名称/标签/绑定核验后即按[提交知识](../../knowledge/rules/fireplay-completion-recovery-v5.md)收尾。后续YouTube进度、排队、限额和向量化交平台，不轮询、不等链接、不催办。按config/fireplay-youtube-routing.json.quota_handling，上传时已选择YouTube模式且素材真实受理后，即使账号/组额度不足、暂未创建YouTube任务，也正常完成核验及结案；不等待额度、不因此重传/重入库、另建任务或反复提醒，后续额度恢复由Fireplay处理。报告已提交/已请求自动上传，不冒称YouTube已完成。经验按知识技能归纳；必要证据、未知费用和质量异议保留；逐run执行maintain --close，阻断项如实记录。没有生产run的读取/测试不伪造交付或维护成功。
