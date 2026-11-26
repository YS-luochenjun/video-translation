# 详细设计附录 D：模板

总入口见 [详细设计](详细设计.md)。

<a id="section-20"></a>

## 附录 D：现行模板字段字典

以下来自agent/templates公开示例，保留字段路径和示例类型；占位值不构成可提交参数。数组用[]表示元素，空数组的元素结构须查执行器。legacy目录中的旧本地TTS模板只作为历史兼容，不能用其发起新本地语音生成。

### D · `budget-request.json`

[agent/templates/budget-request.json](../../agent/templates/budget-request.json)

|字段路径|示例类型|示例值 / 填写提示|
|---|---|---|
|`authority`|string|user|
|`authorization_ref`|string|REPLACE_WITH_STABLE_ORIGINATING_HUMAN_MESSAGE_ID|
|`user_request`|string|REPLACE_WITH_ACTUAL_USER_VIDEO_TRANSLATION_REQUEST|
|`source`|string|C:/media/source.mp4|
|`mode`|string|first|

### D · `caption-alignment-example.json`

[agent/templates/caption-alignment-example.json](../../agent/templates/caption-alignment-example.json)

|字段路径|示例类型|示例值 / 填写提示|
|---|---|---|
|`schema_version`|number|1|
|`source_sha256`|string|COPY_VERIFIED_SOURCE_HASH|
|`target_language`|string|zh-CN|
|`audio`|object||
|`audio.path`|string|outputs/audio-mix/translated-mix.wav|
|`audio.sha256`|string|COPY_ACTUAL_FINAL_MIX_HASH|
|`timeline`|string|final_mix_seconds|
|`status`|string|pending|
|`reviewer`|string||
|`method`|string|manual_listening|
|`segments`|array||
|`segments[].speech_id`|string|a001|
|`segments[].units`|array||
|`segments[].units[].text`|string|现在|
|`segments[].units[].start`|number|0.2|
|`segments[].units[].end`|number|0.6|
|`note`|string|Illustrative times only. Replace with actual final-mix listening/alignment evidence before setting reviewed.|

### D · `codex-visual-report.json`

[agent/templates/codex-visual-report.json](../../agent/templates/codex-visual-report.json)

|字段路径|示例类型|示例值 / 填写提示|
|---|---|---|
|`actor`|string|Codex|
|`method`|string|填写实际看图或使用宿主图像编辑工具的过程|
|`knowledge_read`|array||
|`observations`|array||
|`observations[].image`|string|analysis/shot-001.jpg|
|`observations[].observation`|string|填写该图的实际观察及未解决问题|
|`outputs`|array||
|`limitations`|array||

### D · `codex-visual-task.json`

[agent/templates/codex-visual-task.json](../../agent/templates/codex-visual-task.json)

|字段路径|示例类型|示例值 / 填写提示|
|---|---|---|
|`images`|array||
|`instructions`|string|使用实际原图和项目知识完成指定图片编辑，保留产品与背景，输出新的版本化图片。按当前任务填写具体修改要求。|

### D · `finalization.json`

[agent/templates/finalization.json](../../agent/templates/finalization.json)

|字段路径|示例类型|示例值 / 填写提示|
|---|---|---|
|`source_sha256`|string|ACTUAL_SOURCE_SHA256|
|`inventory_sha256`|string|ACTUAL_INVENTORY_SHA256|
|`request_sha256`|string|ACTUAL_REQUEST_SHA256|
|`video`|object||
|`video.path`|string|outputs/translated-candidate.mp4|
|`video.sha256`|string|ACTUAL_VIDEO_SHA256|
|`reviewer`|string|Codex (same_agent)|
|`reason`|string|Describe the selected best complete result and why further retries have ended|
|`text_ids`|array||
|`speech_ids`|array||
|`speech_mode`|string|dubbed|
|`evidence`|array||
|`evidence[].path`|string|review/actual-result-observations.json|
|`evidence[].sha256`|string|ACTUAL_EVIDENCE_SHA256|
|`assets`|array||
|`limitations`|array||

### D · `inventory-example.json`

[agent/templates/inventory-example.json](../../agent/templates/inventory-example.json)

|字段路径|示例类型|示例值 / 填写提示|
|---|---|---|
|`schema_version`|number|1|
|`source_sha256`|string|COPY_FROM_RUN_RECORD|
|`content_features`|array||
|`coverage`|object||
|`coverage.visual`|object||
|`coverage.visual.status`|string|pending|
|`coverage.visual.method`|string||
|`coverage.visual.evidence`|array||
|`coverage.speech`|object||
|`coverage.speech.status`|string|pending|
|`coverage.speech.method`|string||
|`coverage.speech.evidence`|array||
|`coverage.timeline`|object||
|`coverage.timeline.status`|string|pending|
|`coverage.timeline.method`|string||
|`coverage.timeline.evidence`|array||
|`shots`|array||
|`shots[].id`|string|s001|
|`shots[].start`|number|0|
|`shots[].end`|number|8|
|`shots[].description`|string|Agent describes the actual shot|
|`shots[].keyframe`|string|analysis/shot-001.jpg|
|`text_instances`|array||
|`text_instances[].id`|string|t001|
|`text_instances[].source_text`|string|Try it today|
|`text_instances[].target_text`|string|现在就试试|
|`text_instances[].start`|number|1.2|
|`text_instances[].end`|number|4.6|
|`text_instances[].bbox`|array||
|`text_instances[].action`|string|model_edit|
|`text_instances[].text_role`|string|scene_text|
|`text_instances[].background_is_static`|boolean|True|
|`text_instances[].reason`|string|Replace with actual observations/evidence and method version: this static card supports a clean same-source donor plus transparent target text. Backup: host reconstruction if donor lighting/edges fail. Switch only on observed mismatch; stop when current-mode checks pass or bounded trials end. Record protected motion, actual check and unresolved scope.|
|`text_instances[].evidence`|array||
|`speech_segments`|array||
|`audio`|object||
|`audio.has_speech`|null|None|
|`audio.strategy`|string|unknown|
|`audio.reason`|string||
|`routing_assessment`|object||
|`routing_assessment.version`|number|1|
|`routing_assessment.primary_type`|null|None|
|`routing_assessment.reason`|string|Fill from actual information carriers, not word count|
|`routing_assessment.evidence`|array||
|`routing_assessment.method_choices`|array||
|`routing_assessment.method_choices[].domain`|string|visual|
|`routing_assessment.method_choices[].method_id`|string|route-selection-v3|
|`routing_assessment.method_choices[].reason`|string||
|`routing_assessment.method_choices[].alternative`|string||
|`routing_assessment.method_choices[].switch_when`|string||
|`routing_assessment.method_choices[].stop_when`|string||

### D · `knowledge-entry.json`

[agent/templates/knowledge-entry.json](../../agent/templates/knowledge-entry.json)

|字段路径|示例类型|示例值 / 填写提示|
|---|---|---|
|`id`|string|example-scoped-rule-v1|
|`path`|string|knowledge/local/verified/example.md|
|`status`|string|candidate|
|`scope`|object||
|`scope.workflow`|string|video-localization|
|`scope.target_language`|string|zh-CN|
|`scope.profile`|string|company-default|
|`tags`|array||
|`reviewed_by`|null|None|
|`reviewed_at`|null|None|
|`evidence_runs`|array||
|`valid_until`|null|None|
|`superseded_by`|null|None|
|`note`|string|Example only; copy into a private index after review, do not auto-promote|

### D · `knowledge-evidence.json`

[agent/templates/knowledge-evidence.json](../../agent/templates/knowledge-evidence.json)

|字段路径|示例类型|示例值 / 填写提示|
|---|---|---|
|`entry_id`|string|actual-existing-knowledge-id|
|`source_run`|string|actual-run-id|
|`video_sha256`|string|actual-result-sha256|
|`reviewed_by`|string|Actual evidence reviewer and limits|
|`evidence_review`|string|sanitized_project_evidence|
|`files`|object||
|`files.caption-sync.json`|string|review/actual-hash-prefix/caption-sync.json|
|`files.observed-audio`|string|review/actual-hash-prefix/audio.wav|
|`files.caption-boundary`|string|review/actual-hash-prefix/caption-observed-sheet-01.jpg|
|`required_evidence`|array||

### D · `knowledge-promotion.json`

[agent/templates/knowledge-promotion.json](../../agent/templates/knowledge-promotion.json)

|字段路径|示例类型|示例值 / 填写提示|
|---|---|---|
|`id`|string|reviewed-method-new-revision|
|`path`|string|knowledge/rules/reviewed-method-new-revision.md|
|`scope`|object||
|`scope.workflow`|string|video-localization|
|`tags`|array||
|`origin`|string|Describe the direct feedback or repeatable verification and its limits|
|`approval_type`|string|explicit_user_feedback|
|`evidence_review`|string|sanitized_project_evidence|
|`reviewed_by`|string|Actual reviewer and scope of review|
|`company_preference`|boolean|False|
|`source_run`|string|actual-run-id|
|`reference_video_sha256`|string|actual-video-sha256|
|`evidence_files`|array||
|`evidence_references`|object||
|`evidence_references.observation`|string|evidence/reviewed-project-evidence.json|
|`knowledge_type`|string|method|
|`validation_level`|string|developer_reviewed_guidance|
|`topic`|string|visual|
|`requires_features`|array||
|`candidate_sources`|array||
|`requires_any_features`|array||
|`delivery_modes`|array||
|`language_match`|string|exact|

### D · `knowledge-review.json`

[agent/templates/knowledge-review.json](../../agent/templates/knowledge-review.json)

|字段路径|示例类型|示例值 / 填写提示|
|---|---|---|
|`source`|object||
|`source.path`|string|knowledge/candidates/actual-candidate.json|
|`source.sha256`|string|actual-source-sha256|
|`previous_review`|null|None|
|`review_type`|string|developer_review|
|`reviewed_by`|string|Actual reviewer; distinguish same-agent review from independent review|
|`origin`|string|Actual request, feedback or evidence-backed development review|
|`resolution`|string|pending|
|`reason`|string|Which conclusions are justified, and what is still missing|
|`targets`|array||
|`adopted_parts`|array||
|`retained_parts`|array||
|`all_material_accounted`|boolean|False|
|`remaining_disposition`|string|needs_evidence|
|`next_action`|string|A concrete validation or publication step, not another identical summary|
|`retrieval_features`|array||

### D · `knowledge-use.json`

[agent/templates/knowledge-use.json](../../agent/templates/knowledge-use.json)

|字段路径|示例类型|示例值 / 填写提示|
|---|---|---|
|`plan_id`|string|actual-frozen-plan-id|
|`video_sha256`|string|actual-current-candidate-video-sha256|
|`reviewed_by`|string|Actual observer|
|`review_type`|string|same_agent|
|`uses`|array||
|`uses[].path`|string|knowledge/rules/actual-selected-method.md|
|`uses[].sha256`|string|actual-selected-revision-sha256|
|`uses[].outcome`|string|counterexample|
|`uses[].observation`|string|What was actually tried or not used, and the observed effect and limits|
|`evidence`|array||
|`evidence[].path`|string|review/actual-observation.json|
|`evidence[].sha256`|string|actual-evidence-sha256|

### D · `legacy/local-tts.json`

[agent/templates/legacy/local-tts.json](../../agent/templates/legacy/local-tts.json)

|字段路径|示例类型|示例值 / 填写提示|
|---|---|---|
|`voice`|string|piper-es-sharvard|
|`speed`|number|1.0|
|`speaker_id`|number|0|
|`speech_ids`|array||

### D · `local-repair-example.json`

[agent/templates/local-repair-example.json](../../agent/templates/local-repair-example.json)

|字段路径|示例类型|示例值 / 填写提示|
|---|---|---|
|`source_sha256`|string|REPLACE_WITH_ACTUAL_SOURCE_SHA256|
|`shots`|array||
|`shots[].id`|string|pose-one|
|`shots[].start`|number|0|
|`shots[].end`|number|1.2|
|`operations`|array||
|`operations[].shot`|string|pose-one|
|`operations[].start`|number|0.1|
|`operations[].end`|number|1.1|
|`operations[].method`|string|temporal_frame|
|`operations[].donor_time`|number|0|
|`operations[].bbox`|array||
|`operations[].trajectory`|array||
|`operations[].trajectory[].time`|number|0.1|
|`operations[].trajectory[].bbox`|array||
|`operations[].trajectory[].angle`|number|0|
|`operations[].protected_regions`|array||
|`operations[].reason`|string|Replace with observed same-pose donor, mask and protection rationale|

### D · `preproduction-failure.json`

[agent/templates/preproduction-failure.json](../../agent/templates/preproduction-failure.json)

|字段路径|示例类型|示例值 / 填写提示|
|---|---|---|
|`source_sha256`|string|REPLACE_WITH_ACTUAL_SOURCE_SHA256|
|`stage`|string|neutral|
|`reviewer`|string|REPLACE_WITH_ACTUAL_REVIEWER|
|`review_type`|string|same_agent|
|`reason`|string|Describe the actual blocker before a final candidate exists.|
|`hypothesis`|string|State a bounded lesson, not a general quality claim.|
|`observations`|array||
|`observations[].observation`|string|Describe the defect actually observed and its frame or audio interval.|
|`observations[].evidence`|array||
|`observations[].evidence[].path`|string|review/observed-defect.png|
|`observations[].evidence[].sha256`|string|REPLACE_WITH_ACTUAL_EVIDENCE_SHA256|
|`unreviewed_scope`|array||

### D · `prune-versions-example.json`

[agent/templates/prune-versions-example.json](../../agent/templates/prune-versions-example.json)

|字段路径|示例类型|示例值 / 填写提示|
|---|---|---|
|`versions`|array||
|`versions[].path`|string|outputs/old-repair/visual-master.mkv|
|`versions[].sha256`|string|REPLACE_WITH_ACTUAL_VIDEO_SHA256|
|`versions[].decision`|string|failed|
|`versions[].reason`|string|Describe the actually observed defect and the revised variable.|
|`versions[].evidence`|array||
|`versions[].records`|array||
|`versions[].evidence_scope`|string|State exactly which defect is preserved. Keep a continuous clip or original version when isolated images cannot explain motion/audio.|

### D · `quality-hold.json`

[agent/templates/quality-hold.json](../../agent/templates/quality-hold.json)

|字段路径|示例类型|示例值 / 填写提示|
|---|---|---|
|`id`|string|user-visual-correction-YYYYMMDD|
|`source`|object||
|`source.path`|string|runs/actual-run/inputs/source.mp4|
|`source.sha256`|string|REPLACE_WITH_ACTUAL_FULL_SOURCE_SHA256|
|`asset`|object||
|`asset.path`|string|outputs/source/locale/version/final.mp4|
|`asset.sha256`|string|REPLACE_WITH_ACTUAL_FULL_ASSET_SHA256|
|`asset_kind`|string|video|
|`reason`|string|Describe the observed defect, affected interval and uncertainty|
|`reported_by`|string|Attribute the user's correction and the actual reviewer|
|`origin`|object||
|`origin.thread_id`|string|actual-origin-thread|
|`origin.scope`|string|Exact identified version; do not automatically reject future repaired versions|
|`evidence`|array||
|`evidence[].path`|string|knowledge/local/feedback/actual-event/feedback.json|
|`evidence[].sha256`|string|REPLACE_WITH_ACTUAL_EVIDENCE_SHA256|

### D · `source-reference.json`

[agent/templates/source-reference.json](../../agent/templates/source-reference.json)

|字段路径|示例类型|示例值 / 填写提示|
|---|---|---|
|`id`|string|actual-source-reference-new-revision|
|`path`|string|knowledge/cases/actual-source-reference-new-revision.md|
|`scope`|object||
|`scope.workflow`|string|video-localization|
|`scope.source_sha256`|string|actual-source-sha256|
|`scope.target_language`|string|zh-CN|
|`tags`|array||
|`knowledge_type`|string|source_reference|
|`origin`|string|Exact-source observation or user approval, preserving its actual limits|
|`approval_type`|string|explicit_user_feedback|
|`evidence_review`|string|sanitized_project_evidence|
|`reviewed_by`|string|Actual reviewer and scope|
|`company_preference`|boolean|False|
|`source_run`|string|actual-run-id|
|`reference_video_sha256`|string|actual-video-sha256|
|`evidence_files`|array||
|`evidence_references`|object||
|`evidence_references.observation`|string|evidence/reviewed-project-evidence.json|

