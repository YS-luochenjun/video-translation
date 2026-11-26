# 详细设计附录 B：MCP

总入口见 [详细设计](详细设计.md)。

<a id="section-18"></a>

## 附录 B：MCP 工具声明完整目录

来源：[bin/mcp_server.py](../../bin/mcp_server.py)。通用参数校验与boolean/integer声明差异已在正文说明；此处忠实保留工具声明，不对其可调用性作额外承诺。

### B · `localizer_knowledge_queue`

Read unresolved knowledge adoption and revision work with attribution

参数为空对象。

additionalProperties=false；readOnlyHint=True。提示不是执行权限或完整副作用证明。

### B · `localizer_knowledge_advisories`

Recall at most three scoped unverified observations; separate from active rules

|字段|类型|必需|约束|
|---|---|---|---|
|`target_language`|string|True|{}|
|`source_sha256`|string|False|{}|
|`features`|string|False|{}|

additionalProperties=false；readOnlyHint=True。提示不是执行权限或完整副作用证明。

### B · `localizer_knowledge_use`

Record actual knowledge use or non-use against frozen plan, video and durable evidence; no rule activation

|字段|类型|必需|约束|
|---|---|---|---|
|`run`|string|True|{}|
|`spec`|string|True|{}|

additionalProperties=false；readOnlyHint=未声明。提示不是执行权限或完整副作用证明。

### B · `localizer_codex_packet`

Prepare real images and project knowledge for Codex text recognition/image editing; no automatic inference

|字段|类型|必需|约束|
|---|---|---|---|
|`run`|string|True|{}|
|`stage`|string|False|{"enum": ["recognize", "image"]}|
|`spec`|string|False|{}|

additionalProperties=false；readOnlyHint=未声明。提示不是执行权限或完整副作用证明。

### B · `localizer_codex_result`

Bind actual Codex observations and edited images; existing visual quality gates still apply

|字段|类型|必需|约束|
|---|---|---|---|
|`run`|string|True|{}|
|`packet`|string|True|{}|
|`report`|string|True|{}|

additionalProperties=false；readOnlyHint=未声明。提示不是执行权限或完整副作用证明。

### B · `localizer_model_routing`

Read the current five specialist roles and Codex visual responsibilities

参数为空对象。

additionalProperties=false；readOnlyHint=True。提示不是执行权限或完整副作用证明。

### B · `localizer_local_tts`

Reuse existing hash-bound local narration; new speech uses Gemini TTS, no automatic approval

|字段|类型|必需|约束|
|---|---|---|---|
|`run`|string|True|{}|
|`spec`|string|True|{}|

additionalProperties=false；readOnlyHint=未声明。提示不是执行权限或完整副作用证明。

### B · `localizer_close_failure`

Preserve observed preproduction failure and independent evidence; no candidate or budget reset

|字段|类型|必需|约束|
|---|---|---|---|
|`run`|string|True|{}|
|`spec`|string|True|{}|

additionalProperties=false；readOnlyHint=未声明。提示不是执行权限或完整副作用证明。

### B · `localizer_maintain`

Task-scoped housekeeping; optional closure preserves evidence before retiring a settled delivered run

|字段|类型|必需|约束|
|---|---|---|---|
|`run`|string|True|{}|
|`close`|boolean|False|{}|

additionalProperties=false；readOnlyHint=未声明。提示不是执行权限或完整副作用证明。

### B · `localizer_work_packet`

Read current stage, blockers and bounded knowledge; no automatic approval

|字段|类型|必需|约束|
|---|---|---|---|
|`run`|string|True|{}|
|`stage`|string|False|{"enum": ["source", "translation", "neutral", "render", "review", "delivery"]}|

additionalProperties=false；readOnlyHint=True。提示不是执行权限或完整副作用证明。

### B · `localizer_production`

Resume existing local production; never submits paid jobs or invents reviews

|字段|类型|必需|约束|
|---|---|---|---|
|`run`|string|True|{}|

additionalProperties=false；readOnlyHint=未声明。提示不是执行权限或完整副作用证明。

### B · `localizer_compose_best`

Compose existing translated layers and best available plates; no paid calls or quality approval

|字段|类型|必需|约束|
|---|---|---|---|
|`run`|string|True|{}|

additionalProperties=false；readOnlyHint=未声明。提示不是执行权限或完整副作用证明。

### B · `localizer_finalize`

Output the complete translated result with disclosed defects; preserves failed quality records

|字段|类型|必需|约束|
|---|---|---|---|
|`run`|string|True|{}|
|`spec`|string|False|{}|

additionalProperties=false；readOnlyHint=未声明。提示不是执行权限或完整副作用证明。

### B · `localizer_doctor`

Check local runtime without a network call

参数为空对象。

additionalProperties=false；readOnlyHint=True。提示不是执行权限或完整副作用证明。

### B · `localizer_analyze`

Extract media assets and pending inventory for an existing run

|字段|类型|必需|约束|
|---|---|---|---|
|`run`|string|True|{}|

additionalProperties=false；readOnlyHint=未声明。提示不是执行权限或完整副作用证明。

### B · `localizer_plan`

Validate agent inventory and build a scoped execution plan

|字段|类型|必需|约束|
|---|---|---|---|
|`run`|string|True|{}|

additionalProperties=false；readOnlyHint=未声明。提示不是执行权限或完整副作用证明。

### B · `localizer_render`

Assemble reviewed local or completed model segments

|字段|类型|必需|约束|
|---|---|---|---|
|`run`|string|True|{}|

additionalProperties=false；readOnlyHint=未声明。提示不是执行权限或完整副作用证明。

### B · `localizer_capture`

Capture current candidate evidence for review

|字段|类型|必需|约束|
|---|---|---|---|
|`run`|string|True|{}|

additionalProperties=false；readOnlyHint=未声明。提示不是执行权限或完整副作用证明。

### B · `localizer_quality`

Check technical contract and attributed per-instance review

|字段|类型|必需|约束|
|---|---|---|---|
|`run`|string|True|{}|

additionalProperties=false；readOnlyHint=未声明。提示不是执行权限或完整副作用证明。

### B · `localizer_visual_evidence`

Generate native comparisons and pending observations; no automatic pass

|字段|类型|必需|约束|
|---|---|---|---|
|`run`|string|True|{}|
|`stage`|string|False|{"enum": ["neutral", "final"]}|
|`shot`|string|False|{}|

additionalProperties=false；readOnlyHint=未声明。提示不是执行权限或完整副作用证明。

### B · `localizer_visual_review`

Submit one actual attributed instance observation, never bulk pass

|字段|类型|必需|约束|
|---|---|---|---|
|`run`|string|True|{}|
|`manifest`|string|True|{}|
|`observation`|string|True|{}|

additionalProperties=false；readOnlyHint=未声明。提示不是执行权限或完整副作用证明。

### B · `localizer_visual_notes`

Expand concise individual notes, explicit frames and decisions required

|字段|类型|必需|约束|
|---|---|---|---|
|`run`|string|True|{}|
|`manifest`|string|True|{}|
|`notes`|string|True|{}|

additionalProperties=false；readOnlyHint=未声明。提示不是执行权限或完整副作用证明。

### B · `localizer_visual_pages`

Bounded native galleries with actual layer selection and next-frame cursor; never approval

|字段|类型|必需|约束|
|---|---|---|---|
|`run`|string|True|{}|
|`manifest`|string|True|{}|
|`instance`|string|True|{}|
|`layer`|string|False|{}|
|`after_frame`|string|False|{}|
|`limit`|string|False|{}|
|`columns`|integer|False|{"minimum": 1, "maximum": 4}|

additionalProperties=false；readOnlyHint=未声明。提示不是执行权限或完整副作用证明。

### B · `localizer_repair_preflight`

Candidate cuts and risk windows; no media submission or approval

|字段|类型|必需|约束|
|---|---|---|---|
|`run`|string|True|{}|

additionalProperties=false；readOnlyHint=未声明。提示不是执行权限或完整副作用证明。

### B · `localizer_repair_recipe`

Execute bounded source-bound local repair; default probe, no paid calls, approval stays pending

|字段|类型|必需|约束|
|---|---|---|---|
|`run`|string|True|{}|
|`recipe`|string|True|{}|
|`mode`|string|False|{"enum": ["probe", "full"]}|
|`extension_reason`|string|False|{}|

additionalProperties=false；readOnlyHint=未声明。提示不是执行权限或完整副作用证明。

### B · `localizer_visual_release_neutral`

Release neutral preparation only after per-instance review

|字段|类型|必需|约束|
|---|---|---|---|
|`run`|string|True|{}|
|`shot`|string|True|{}|

additionalProperties=false；readOnlyHint=未声明。提示不是执行权限或完整副作用证明。

### B · `localizer_knowledge`

Retrieve active scoped methods; pass source hash and comma-separated content features when known

|字段|类型|必需|约束|
|---|---|---|---|
|`target_language`|string|True|{}|
|`source_sha256`|string|False|{}|
|`features`|string|False|{}|

additionalProperties=false；readOnlyHint=True。提示不是执行权限或完整副作用证明。

