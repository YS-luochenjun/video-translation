# 核对设计师和二创归属

刷新当前需求执行人，排除罗晨钧、邹彬。其余执行人全部作为设计师，实际创作类型为二创。视频的新名称字段与英文 `derivative` 标签由[上传命名与标签](../../agent/workflows/fireplay-intake.md#上传命名与标签)指定。

使用当前 Fireplay 工具合同按真实成员 ID 查成员目录，展开成员和分页，与执行人列表逐项核对。保存来源，采用已核验的实际用户 ID 或 DID 映射。无可核验 DID 时按现行命名规则省略 DID 字段，归属仍按已核验身份提交。无其他执行人时可留空。回传规格绑定 `designer_receipt`。

入库后沿原 `material_id` 核验 `designerIds` 和 `creationType`。预览和权限状态真实记录，成功以平台写入及读回为准。已绑定或结果未知的素材沿原 ID 与操作恢复。选择和执行依据为 `config/fireplay-intake.json.designer_selection` 和当前上传规则。

修订依据为 evidence:previous、evidence:upload_policy。来源仅支持相应身份和操作规则。
