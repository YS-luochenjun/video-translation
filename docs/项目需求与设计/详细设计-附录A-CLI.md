# 详细设计附录 A：CLI

总入口见 [详细设计](详细设计.md)。

<a id="section-17"></a>

## 附录 A：CLI 命令与参数完整目录

调用形式为 `python bin/va.py <命令>` 或项目配套 PowerShell 入口。以下包含 hooks 子命令；help为标准帮助参数不逐项重复。`required=False`仅说明parser层，业务校验可能进一步要求条件字段。

### A · `doctor`

Local tools/config; --online checks KIE credits only

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`--online`|False|`False`|nargs=0|

### A · `check`

Run tests with this same working Python interpreter

无额外业务参数。

### A · `kie-authorization`

Show this workspace owner authorization, without credentials

无额外业务参数。

### A · `resources`

Show local compute owners and free disk space; never cleans or unlocks

无额外业务参数。

### A · `model-routing`

Show Codex responsibilities and the five specialist model roles

无额外业务参数。

### A · `codex-packet`

Bind actual images and project knowledge for Codex recognition or image editing

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`--stage`|False|`recognize`|choices=['recognize', 'image']|
|`--spec`|False|`None`|Run-relative JSON with optional images and instructions|

### A · `codex-result`

Register actual Codex observations/edited images; never auto-approve

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`packet`|True|`None`||
|`report`|True|`None`||

### A · `asr`

Whisper small transcription of actual audio; no acceptance claim

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`--audio`|False|`None`||
|`--model`|False|`small`|choices=['small']|
|`--download`|False|`False`|nargs=0|
|`--no-vad`|False|`False`|nargs=0|
|`--language`|False|`None`|Optional recognition hint, not independent language detection|

### A · `audio-mix`

Resume the existing narration-plan mixer without rewriting scripts

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||

### A · `maintain`

Incremental housekeeping; --close preserves then retires a settled delivered run

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`--close`|False|`False`|nargs=0|

### A · `scratch-register`

Register one rebuildable task-owned work/runs/RUN file

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`path`|True|`None`||
|`--reason`|True|`None`||

### A · `work-packet`

Read current blockers, exact job IDs and stage-specific AI work/knowledge

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`--stage`|False|`None`|choices=['source', 'translation', 'neutral', 'render', 'review', 'delivery']|

### A · `visual-evidence`

Generate native-size comparison evidence and pending per-instance templates

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`--stage`|False|`final`|choices=['neutral', 'final']|
|`--shot`|False|`None`||
|`--no-decode-cache`|False|`False`|nargs=0；Decode new evidence from media; keep existing immutable bundles and review gates|

### A · `visual-review`

Record ONE attributed instance observation; never auto-fill pass

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`manifest`|True|`None`||
|`observation`|True|`None`||

### A · `visual-notes`

Expand concise individual notes; explicit coverage and decisions required

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`manifest`|True|`None`||
|`notes`|True|`None`||

### A · `visual-pages`

Build reusable native-pixel galleries without approving evidence

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`manifest`|True|`None`||
|`--instance`|True|`None`||
|`--max-height`|False|`1600`||
|`--columns`|False|`1`|Native-pixel gallery columns, 1..4; no frame sampling|
|`--layer`|False|`all`|Actual strip layer label: all, source, neutral-0, final|
|`--after-frame`|False|`None`||
|`--limit`|False|`2`|At most four native gallery pages per response|

### A · `repair-preflight`

Risk windows for source cuts, blurred text and watermark edges; never approval

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||

### A · `repair-run`

Execute a source-bound local repair recipe with durable trial budget

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`recipe`|True|`None`||
|`--probe`|False|`False`|nargs=0|
|`--extension-reason`|False|`None`||

### A · `repair-reconcile`

Resolve a dead local repair process after checking operation locks

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`--reason`|True|`None`||

### A · `run-prune`

Evict superseded generated comparison pictures after run-preserve

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`--execute`|False|`False`|nargs=0|
|`--expect`|False|`None`||

### A · `run-prune-versions`

Retire explicitly selected obsolete videos with independent failure evidence

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`spec`|True|`None`||
|`--execute`|False|`False`|nargs=0|
|`--expect`|False|`None`||

### A · `visual-release-neutral`

Release a neutral shot only after all individual observations pass

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`--shot`|True|`None`||

### A · `budget-open`

Host/operator: register one actual human request, never a worker run or retry

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`spec`|True|`None`||

### A · `budget-bind`

Bind an existing or derived run to the same request budget

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`--parent-run`|False|`None`||

### A · `budget-status`

Read whole-request spending across all runs and batches

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`id`|True|`None`||

### A · `fast-register`

Bind a native-timing composition and open basic review; never auto-pass

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`recipe`|True|`None`||

### A · `finalize`

Deliver the best complete translated video with disclosed issues, without quality approval

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`spec`|False|`review/finalization.json`|nargs=?|

### A · `compose-best`

Compose existing translated shot layers and best plates without strict visual approval or model calls

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||

### A · `reuse-neutral`

Bind a reviewed exact-source neutral master without locale decisions

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`--from-run`|True|`None`||
|`--source-shot`|True|`None`||
|`--target-shot`|True|`None`||

### A · `batch-create`

Create locale runs sharing one source-duration request budget

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`id`|True|`None`||
|`video`|True|`None`||
|`--targets`|True|`None`|nargs=+|
|`--brief`|False|`完整本地化广告，保留品牌、音乐、音效和运动。`||
|`--reused`|False|`False`|nargs=0；Use the lower existing incremental-reuse budget|

### A · `batch-status`



|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`id`|True|`None`||

### A · `batch-approve`



|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`id`|True|`None`||
|`--best-available`|False|`False`|nargs=0；Expand from a finalized complete fast pilot while retaining its disclosed issues; no quality/master approval|

### A · `batch-run`



|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`id`|True|`None`||
|`--deliver`|False|`False`|nargs=0|

### A · `production`

Resume local plan/render/capture/quality steps; never invent reviews or submit paid tasks

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`--deliver`|False|`False`|nargs=0|
|`--force-render`|False|`False`|nargs=0|

### A · `timing`

Report measured stage durations and unobserved gaps

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||

### A · `tts-packet`

Build a reusable exact-copy TTS packet without calling KIE

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`--voice`|True|`None`||
|`--estimate`|True|`None`||
|`--speech-ids`|False|`None`|nargs=+|

### A · `local-tts`

Reuse existing hash-bound local narration takes; new speech uses tts-packet

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`spec`|True|`None`||

### A · `close-failure`

Preserve attributed preproduction failures without inventing a final candidate

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`spec`|True|`None`||

### A · `workspace-init`

Create an independent workspace with public knowledge and policy

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`destination`|True|`None`||

### A · `workspace-export`

Create a fresh runnable source copy without local data or credentials

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`destination`|True|`None`||

### A · `workspace-verify`

Verify an exported source/public knowledge baseline

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`directory`|True|`None`||

### A · `storage-report`

Read-only lifecycle and storage inventory

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`--duplicates`|False|`False`|nargs=0；Hash files to measure repeated logical bytes; never deletes|

### A · `storage-policy`

Show/set advisory storage limits; never deletes

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`action`|False|`show`|choices=['show', 'set']；nargs=?|
|`--area`|False|`None`|choices=['runs', 'outputs', 'media']|
|`--max-count`|False|`None`||
|`--max-gib`|False|`None`||
|`--minimum-free-gib`|False|`None`||

### A · `storage-plan`

Read-only limit/closure report; no automatic eviction

无额外业务参数。

### A · `delivery-index`

Refresh a portable video browsing page without media copies

无额外业务参数。

### A · `quality-hold`

Record an evidence-bound quality objection without rewriting history

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`spec`|True|`None`||

### A · `knowledge-audit`

Verify permanent knowledge without depending on runs or outputs

无额外业务参数。

### A · `knowledge-queue`

Show unresolved adoption/revision work, not more automatic candidates

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`--include-closed`|False|`False`|nargs=0|

### A · `knowledge-review`

Record an attributed adoption, gap, or historical-only decision

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`spec`|True|`None`||

### A · `candidate-archive`

Preview or archive fully accounted candidate originals with provenance

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`path`|True|`None`||
|`--execute`|False|`False`|nargs=0|
|`--expect`|False|`None`||

### A · `knowledge-use`

Bind actual use/non-use feedback to plan, video and evidence

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`spec`|True|`None`||

### A · `language-resolve`

Resolve the project's target-language aliases without a video

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`language`|True|`None`||

### A · `knowledge-evidence`

Append reviewed independent evidence without rewriting historical cases

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`spec`|True|`None`||

### A · `source-find`

Find verified exact-source extraction snapshots

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`source_sha256`|True|`None`||

### A · `source-save`



|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||

### A · `run-preserve`



|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||

### A · `run-delete`



|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`--execute`|False|`False`|nargs=0；Delete only after preservation and all gates pass|
|`--expect`|False|`None`|Exact fingerprint returned by the latest ready preview|

### A · `hooks`

Project-owned knowledge maintenance; no paid media models

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`action`|True|`None`|choices=['status', 'baseline', 'run', 'prepare', 'apply']|
|`--due`|False|`False`|nargs=0；Only run after project daily time, once per successful sweep|
|`--response`|False|`None`|Project-relative structured answer from any reasoning engine|

### A · `knowledge-promote`

Publish a reviewed method and independent evidence using a sourced spec

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`spec`|True|`None`||

### A · `archive`

Create a standalone local delivery/reuse package

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||

### A · `archive-verify`

Check all bytes within a standalone package

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`package`|True|`None`||

### A · `archive-restore`

Restore a historical package into a new working run

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`package`|True|`None`||
|`--id`|True|`None`||

### A · `library-find`

Find exact-source packages, reporting expired packages honestly

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`source_sha256`|True|`None`||
|`--target`|False|`None`||

### A · `model-task`

Inspect historical packets or submit current Gemini TTS/Wan tasks

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`packet`|True|`None`||
|`--execute`|False|`False`|nargs=0|
|`--retry-failed`|False|`False`|nargs=0|

### A · `audio-task`



|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`packet`|True|`None`||
|`--execute`|False|`False`|nargs=0|
|`--retry-failed`|False|`False`|nargs=0|

### A · `captions`

Compile reviewed final-mix alignment; --apply updates inventory, no paid call

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`--alignment`|True|`None`|Run-relative reviewed alignment JSON|
|`--apply`|False|`False`|nargs=0|

### A · `caption-check`

Read-only audiovisual caption gate; does not regenerate video

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||

### A · `init`



|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`video`|True|`None`||
|`--target`|False|`zh-CN`||
|`--brief`|False|`将视频完整本地化为指定目标语言的自然广告，保留品牌与产品。`||
|`--id`|True|`None`||

### A · `ingest`



|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`url`|True|`None`||
|`--target`|False|`zh-CN`||
|`--brief`|False|`将视频完整本地化为指定目标语言的自然广告，保留品牌与产品。`||
|`--id`|True|`None`||

### A · `analyze`



|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||

### A · `audio-analyze`



|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`--model`|False|`gemini-3-8-flash-openai`|choices=['gemini-3-8-flash-openai', 'gemini-3.1-pro']|
|`--model-authorization`|False|`None`|Run-relative source/request-bound human grant for an alternative analysis model|
|`--retry-upload`|False|`False`|nargs=0；Retry a journaled transport failure before model submission; preserves prior attempt and budget|
|`--transcribe-only`|False|`False`|nargs=0；Transcribe actual candidate audio alone; does not claim comparative music/FX review|
|`--voice-review`|False|`False`|nargs=0；Compare actual character voice distinction and consistency; requires --candidate|
|`--execute`|False|`False`|nargs=0；Upload audio and run one journaled KIE Gemini audio analysis|
|`--candidate`|False|`False`|nargs=0；Compare source with captured candidate; transcribe actual output and review retained music/effects|

### A · `plan`



|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`--experiment`|False|`None`|choices=['local_overlay', 'model_edit']|

### A · `packet`



|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`segment`|True|`None`||

### A · `submit`



|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`segment`|True|`None`||
|`--execute`|False|`False`|nargs=0；Actually upload and create a paid KIE job|
|`--retry-failed`|False|`False`|nargs=0；One explicit retry of a terminal zero-cost provider failure|

### A · `poll`



|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||
|`job`|True|`None`||
|`--wait`|False|`0`|choices=range(0, 46)|

### A · `render`



|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||

### A · `capture`



|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||

### A · `quality`



|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||

### A · `deliver`



|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||

### A · `reflect`



|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||

### A · `context`



|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||

### A · `status`



|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`run`|True|`None`||

### A · `knowledge`



|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`--target`|False|`zh-CN`||

### A · `demo`

Generate a known synthetic English advertisement fixture

|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`--id`|False|`demo-local`||
|`--route`|False|`local_overlay`|choices=['local_overlay', 'model_edit']|
|`--seconds`|False|`8`|Synthetic fixture length, 1-180 seconds|

### A · `blind`



|参数|parser必需|默认值|可选值 / 数量 / 帮助|
|---|---|---|---|
|`action`|True|`None`|choices=['freeze', 'verify', 'reveal']|
|`run`|True|`None`||
|`candidates`|False|`None`|nargs=*|

