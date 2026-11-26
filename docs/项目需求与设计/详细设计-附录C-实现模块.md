# 详细设计附录 C：实现模块

总入口见 [详细设计](详细设计.md)。

<a id="section-19"></a>

## 附录 C：实现模块与函数定位目录

按源码排序列出所有72个Python模块的顶层函数及类方法，包括内部函数。内部函数不构成稳定外部API。签名取自AST，行号取自基线源码；下列模块级说明保留原文，详细业务边界以正文和执行合同为准。

### C · `__init__.py`

来源：[src/video_localizer/__init__.py](../../src/video_localizer/__init__.py)；基线 3 行。

Local execution and evidence contracts for an agent-directed workflow.

本模块无顶层函数/类定义，主要承担包信息或常量。

### C · `asr.py`

来源：[src/video_localizer/asr.py](../../src/video_localizer/asr.py)；基线 66 行。

Reusable actual-audio transcription; cached evidence never asserts acceptance.

显式相对导入模块：`common`, `model_routing`, `timing`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`transcribe(run, audio_relative=None, size=None, download=False, vad=True, language=None)`|10||

### C · `audio.py`

来源：[src/video_localizer/audio.py](../../src/video_localizer/audio.py)；基线 175 行。

显式相对导入模块：`common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`decode(path)`|16|Decode the complete mono waveform for measurement, not speech recognition.|
|`level(value)`|30||
|`inspect(path)`|34||
|`waveform_match(source, result)`|61|Check retained audio after lossy muxing; report timing as well as correlation.|
|`evaluate(source_path, candidate_path, policy, duration)`|86||
|`prompt(policy, language, source_has_audio, speeches, start, end)`|123||
|`extract_track(source, output, start, duration)`|151||
|`concatenate(tracks, output)`|169||

### C · `batches.py`

来源：[src/video_localizer/batches.py](../../src/video_localizer/batches.py)；基线 221 行。

Locale batch orchestration and pilot gates; budgets belong to user requests.

显式相对导入模块：`budgets`, `common`, `languages`, `prepared`, `quality_holds`, `timing`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`_path(batch_id, root)`|9||
|`authorization(root=ROOT)`|15||
|`create(batch_id, video, targets, brief, reused=False, root=ROOT)`|25||
|`binding(run)`|65||
|`reserve(run, job_id, estimate)`|100||
|`sync(run)`|106||
|`masters(plan)`|111||
|`_pilot_snapshot(record, root)`|116||
|`_finalized_pilot_snapshot(record, root)`|145|Freeze a completed fast pilot without claiming quality or master approval.|
|`approve(batch_id, root=ROOT, best_available=False)`|176||
|`gate(run, plan=None)`|188||
|`status(batch_id, root=ROOT)`|207||

### C · `blind.py`

来源：[src/video_localizer/blind.py](../../src/video_localizer/blind.py)；基线 65 行。

显式相对导入模块：`common`, `media`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`freeze(run, candidates)`|11||
|`verify(run)`|39||
|`reveal(run)`|51||

### C · `budgets.py`

来源：[src/video_localizer/budgets.py](../../src/video_localizer/budgets.py)；基线 332 行。

Request-wide spending authority. Creating runs/batches never issues new credit.

显式相对导入模块：`common`, `workflow`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`duration_allowance(source, root=ROOT)`|17|Quote actual source duration; this never opens or replenishes a ledger.|
|`run_allowance(run)`|33|Use the bound original request, including for clips; otherwise quote only.|
|`job_allowance(run, allowance, segment_seconds)`|48|Finite planning guard; money and two repair rounds remain separate gates.|
|`operation()`|62||
|`_directory(root)`|70||
|`_index(root)`|74||
|`_record(root, scope)`|79||
|`open_request(spec, root=ROOT)`|84|Host/operator administrative action backed by a real, new user request.  authorization_ref is the stable human message/event ID, not a run/task ID. Production workers must never invent it to replenish an exhausted budget.|
|`amend_limit(scope, limit, authorization_ref, source_quote, root=ROOT)`|157|Host-only amendment from an actual user instruction; never resets spending.|
|`for_source(source_sha, root=ROOT)`|180||
|`_run_source(run)`|188||
|`bind(run, parent_run=None)`|194||
|`_refresh(record, root)`|230||
|`reserve(run, job_id, estimate)`|258||
|`resume_undispatched(run, job_id)`|278|Resume only a locally proven pre-dispatch failure, using the same reservation.|
|`authorize_request(url, body)`|293|Require a live reservation even for direct KieClient use; one paid POST only.|
|`sync(run)`|312||
|`status(scope, root=ROOT)`|323||

### C · `bundles.py`

来源：[src/video_localizer/bundles.py](../../src/video_localizer/bundles.py)；基线 78 行。

Immutable bundles; public knowledge may share bytes within knowledge/examples.

显式相对导入模块：`common`, `evidence_storage`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`create(directory, kind, identity, sources, metadata=None)`|12|Copy bytes, never link to mutable runs. Manifest is the completion marker.|
|`verify(directory)`|48||
|`extract(directory, destination)`|63|Materialize a verified delivery payload without consulting its original run.|

### C · `candidate_index.py`

来源：[src/video_localizer/candidate_index.py](../../src/video_localizer/candidate_index.py)；基线 73 行。

Derived navigation, never activation or a rewrite of historical candidates.

显式相对导入模块：`common`, `knowledge_records`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`build(root)`|9||
|`refresh(root)`|65||
|`verify(root)`|71||

### C · `captions.py`

来源：[src/video_localizer/captions.py](../../src/video_localizer/captions.py)；基线 296 行。

Shared spoken copy, audio-bound caption timing, and attributed AV review.

Alignment is imported from listening/forced alignment, never inferred by evenly
distributing characters. This module checks evidence bindings and consistency;
it does not itself hear speech or recognize lettering in video pixels.

显式相对导入模块：`common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`normalized(text)`|16|Ignore sentence punctuation/spacing, preserving numeric punctuation/units.|
|`contract(inventory, check_timing=True)`|27||
|`validate_spoken_copy(inventory, lines)`|71|Bind TTS/mixer inputs to the same final script used by captions.|
|`units(item)`|81||
|`track(inventory)`|88||
|`checked_units(values, duration)`|93||
|`compile_alignment(run, inventory, alignment, duration)`|105|Compile reviewed word/phrase boundaries on the final mixed-audio timeline.|
|`plan_assets(run, inventory, duration)`|146||
|`apply_alignment(run, relative, apply=False)`|163||
|`render_instances(instances)`|182|Expand speech fragments for compositors; ordinary titles retain source timing.|
|`shift_instances(instances, offset, duration)`|201|Move both caption and erase timelines into a segment without mutating inputs.|
|`review_template(run, candidate, inventory, audio_asset)`|214||
|`evaluate(run, candidate, inventory, captured, policy, plan=None)`|225|Hard gate: explicit classification, exact copy, measured AV timing, hashes.|

### C · `cli.py`

来源：[src/video_localizer/cli.py](../../src/video_localizer/cli.py)；基线 682 行。

显式相对导入模块：`asr`, `batches`, `budgets`, `codex_visual`, `common`, `delivery_index`, `demo`, `failure_closure`, `fast_delivery`, `finalization`, `kie`, `knowledge`, `knowledge_advisories`, `knowledge_review`, `knowledge_usage`, `languages`, `local_audio`, `local_tts`, `maintenance`, `model_routing`, `prepared`, `production`, `quality_holds`, `repair`, `resources`, `reuse`, `runtime`, `storage`, `storage_policy`, `timing`, `visual_audit`, `visual_notes`, `work_packet`, `workspace`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`doctor(online=False)`|15||
|`capture(run)`|37||
|`status(run)`|100||
|`main(argv=None)`|156||

### C · `codex_visual.py`

来源：[src/video_localizer/codex_visual.py](../../src/video_localizer/codex_visual.py)；基线 169 行。

Project-bound visual work for the host Codex: real inputs, knowledge and output receipts.

显式相对导入模块：`common`, `knowledge`, `knowledge_advisories`, `knowledge_records`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`_asset(run, relative)`|14||
|`_image(run, relative)`|20||
|`_source(run)`|30||
|`packet(run, stage='recognize', spec=None, root=None)`|38||
|`_verify_packet(run, relative, root, check_inventory=False)`|99||
|`record(run, packet_relative, report_relative, root=None)`|119||
|`verify(run, relative, sha256, root=None, stage=None)`|156||

### C · `common.py`

来源：[src/video_localizer/common.py](../../src/video_localizer/common.py)；基线 197 行。

显式相对导入模块：`batches`, `budgets`, `maintenance`, `resources`, `runtime`, `timing`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`class WorkflowError`|23||
|`operation_hash(path, cache)`|27|Read each hard-linked file once within ONE locked verification operation.  No persistent mtime-based trust: callers start with an empty cache each time.|
|`utc_now()`|39||
|`read_json(path)`|43||
|`write_json(path, value)`|56||
|`file_hash(path)`|81||
|`object_hash(value)`|89||
|`inside(root, relative)`|94||
|`get_run(name)`|102||
|`require_number(value, label, minimum=0, maximum=None)`|111||
|`require(condition, message)`|119||
|`lock(path)`|125|Cross-process exclusion. A crash intentionally leaves a visible recovery gate.|
|`run_operation(run)`|142|Serialize mutation/deletion across processes; nested calls in this thread share a lock.|
|`guarded(function)`|159||
|`load_key()`|189||

### C · `compositor.py`

来源：[src/video_localizer/compositor.py](../../src/video_localizer/compositor.py)；基线 109 行。

Preserve source pixels outside timed text mattes; typeset tracked native glyphs.

显式相对导入模块：`captions`, `common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`spans(item, segment)`|8||
|`header(meta)`|20||
|`event(start, end, text, layer=0)`|27||
|`regions(source, edited, segment, items, meta, directory)`|31||
|`color(value)`|65||
|`text(source, segment, items, meta, directory)`|71||

### C · `contracts.py`

来源：[src/video_localizer/contracts.py](../../src/video_localizer/contracts.py)；基线 152 行。

显式相对导入模块：`captions`, `common`, `layout`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`validate_inventory(inventory, run, meta)`|8||

### C · `cost.py`

来源：[src/video_localizer/cost.py](../../src/video_localizer/cost.py)；基线 20 行。

Submission-time cost guard, independent of an old plan's model choice.

显式相对导入模块：`common`, `model_routing`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`check_new_video_task(model, estimated_credits, root=None)`|6||

### C · `crop_stream.py`

来源：[src/video_localizer/crop_stream.py](../../src/video_localizer/crop_stream.py)；基线 49 行。

Bounded native RGBA crop decoding; no temporary per-frame image files.

显式相对导入模块：`common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`class CropStream`|7||
|`CropStream.__init__(self, path, numbers, region, selection)`|8||
|`CropStream.__enter__(self)`|19||
|`CropStream.__getitem__(self, number)`|22||
|`CropStream.__exit__(self, kind, value, traceback)`|38||

### C · `curation.py`

来源：[src/video_localizer/curation.py](../../src/video_localizer/curation.py)；基线 341 行。

Project-owned daily knowledge loop: select, reason, validate, persist candidates.

显式相对导入模块：`common`, `knowledge_records`, `knowledge_review`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`settings(root)`|20||
|`source_files(root)`|31||
|`fingerprint(root, path)`|46||
|`baseline(root=None)`|50||
|`checkpoint(root)`|60||
|`inventory(root, state)`|72||
|`protected(root)`|78||
|`catalogs(root, state=None)`|88||
|`due(config, state, now)`|103||
|`status(root=None, now=None)`|112||
|`related_lessons(events, records)`|124||
|`packet(root, state, config)`|130||
|`validate(response, value)`|160||
|`persist(root, state, value, response)`|203||
|`publish_catalogs(root, state)`|262||
|`execute(root=None, due_only=False, prepare_only=False, response_file=None, engine=None, now=None)`|270||
|`_execute(root, due_only, prepare_only, response_file, engine, now)`|284||

### C · `curation_engine.py`

来源：[src/video_localizer/curation_engine.py](../../src/video_localizer/curation_engine.py)；基线 91 行。

Replaceable reasoning interface; the engine returns data and never writes knowledge.

显式相对导入模块：`common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`executable(root)`|38||
|`codex_cli(packet, prompt, job, root, timeout)`|50|One text-only inference in an isolated directory, without project/media tools.|

### C · `delivery_index.py`

来源：[src/video_localizer/delivery_index.py](../../src/video_localizer/delivery_index.py)；基线 91 行。

A portable browsing page linking canonical videos without copying media.

显式相对导入模块：`common`, `quality_holds`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`_video(entry, root)`|13|Validate the displayed result, not every reusable asset in the package.|
|`refresh(root=None)`|38||

### C · `demo.py`

来源：[src/video_localizer/demo.py](../../src/video_localizer/demo.py)；基线 69 行。

显式相对导入模块：`common`, `knowledge`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`create_demo(name, route, seconds=8)`|7||

### C · `evidence.py`

来源：[src/video_localizer/evidence.py](../../src/video_localizer/evidence.py)；基线 91 行。

Append-only evidence supplements and explicit, verifiable knowledge references.

显式相对导入模块：`common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`check_references(text, references, available)`|13||
|`verify_supplements(entry, root)`|20||
|`supplement(spec_path, root=None)`|47||

### C · `evidence_storage.py`

来源：[src/video_localizer/evidence_storage.py](../../src/video_localizer/evidence_storage.py)；基线 37 行。

Resolve immutable manifest paths through the public evidence content store.

显式相对导入模块：`common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`catalog(directory)`|8||
|`resolve(directory, asset, storage=None)`|21|The original manifest remains authoritative for logical path, hash and size.|

### C · `failure_closure.py`

来源：[src/video_localizer/failure_closure.py](../../src/video_localizer/failure_closure.py)；基线 66 行。

Close a preproduction failure without inventing a candidate or a passing review.

显式相对导入模块：`common`, `evidence`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`close(run, relative)`|8||

### C · `fast_delivery.py`

来源：[src/video_localizer/fast_delivery.py](../../src/video_localizer/fast_delivery.py)；基线 251 行。

Explicit basic-quality delivery using hash-bound recipes and one compact review.

This route removes redundant paperwork, not actual audiovisual observations.
Existing strict candidates retain their original workflow and acceptance contract.

显式相对导入模块：`audio`, `captions`, `common`, `contracts`, `finalization`, `knowledge`, `knowledge_advisories`, `library`, `quality_holds`, `routing`, `workflow`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`_freeze_knowledge(run, plan)`|13||
|`policy(root=ROOT)`|37||
|`validate_plan(run, plan)`|41||
|`register(run, recipe_relative)`|68|Freeze a completed local composition. Registration never supplies a pass.|
|`review_failures(review, candidate, inventory, run, checks)`|122||
|`visual_finish_failures(review, run, acceptance)`|144|Permit documented minor cosmetic flaws without waiving content/motion checks.|
|`quality(run)`|171||
|`deliver(run)`|229||

### C · `finalization.py`

来源：[src/video_localizer/finalization.py](../../src/video_localizer/finalization.py)；基线 189 行。

Deliver a usable translated result without falsely approving its quality.

显式相对导入模块：`common`, `delivery_index`, `fast_delivery`, `knowledge`, `knowledge_advisories`, `library`, `routing`, `workflow`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`compose(run)`|10|Compose existing per-shot plates/layers even when cosmetic review failed.  Codex supplies translated layers. This function never invents translations, calls a model, or upgrades an unapproved plate to a reusable master.|
|`validate_completion(run, spec)`|82||
|`finish(run, relative='review/finalization.json')`|109|Explicit output completion; scores and quality holds remain historical facts.|

### C · `kie.py`

来源：[src/video_localizer/kie.py](../../src/video_localizer/kie.py)；基线 178 行。

显式相对导入模块：`budgets`, `common`, `model_routing`, `timing`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`class ApiError`|25||
|`ApiError.__init__(self, message, ambiguous=False, provider_response=None)`|26||
|`class NoRedirect`|32||
|`NoRedirect.redirect_request(self, req, fp, code, msg, headers, newurl)`|33||
|`class KieClient`|37||
|`KieClient.__init__(self, key=None, opener=None)`|38||
|`KieClient._request(self, url, body=None, content_type='application/json', envelope=True, timeout=60)`|42||
|`KieClient.analyze_audio(self, audio_url, prompt, model=None, *, run=None, model_authorization=None)`|69||
|`KieClient.credits(self)`|88||
|`KieClient.create(self, payload, *, run=None, model_authorization=None)`|92||
|`KieClient.status(self, task_id)`|100||
|`KieClient.upload(self, path)`|104||
|`public_url(url)`|120||
|`download(url, destination, max_bytes=500 * 1024 * 1024)`|135|Unauthenticated media fetch; validate each redirect and never forward the API key.|
|`result_urls(status)`|166||

### C · `knowledge.py`

来源：[src/video_localizer/knowledge.py](../../src/video_localizer/knowledge.py)；基线 213 行。

显式相对导入模块：`common`, `knowledge_usage`, `learning`, `workflow`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`context_for(request, inventory, root=None)`|10|Use agent-described features plus direct inventory facts for conditional methods.|
|`validate_feature_requirements(entry)`|52|Both feature clauses are optional; a nonempty any-clause needs one match.|
|`_scope_matches(entry, context)`|69||
|`retrieve(context, limit=6, today=None, *, indexes=None, root=None)`|85|Return eligible policies/required methods; limit bounds additional methods.|
|`source_references(context, limit=4, root=None)`|136||
|`related_source_references(context, root=None, limit=4)`|141|Discovery only: same source/base language, outside the approved locale scope.|
|`reflect(run, root=None)`|165||

### C · `knowledge_advisories.py`

来源：[src/video_localizer/knowledge_advisories.py](../../src/video_localizer/knowledge_advisories.py)；基线 58 行。

Bounded, scoped recall of observations, kept separate from authoritative methods.

显式相对导入模块：`common`, `knowledge_review`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`retrieve(context, root=None, limit=3)`|6||

### C · `knowledge_maintenance.py`

来源：[src/video_localizer/knowledge_maintenance.py](../../src/video_localizer/knowledge_maintenance.py)；基线 126 行。

Exact-byte evidence compaction with an explicit, reproducible deletion plan.

显式相对导入模块：`common`, `evidence_storage`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`inventory(root)`|11||
|`preview(root)`|27||
|`compact(root, expected)`|66||
|`audit(root)`|101||
|`resolve_path(root, relative)`|112||

### C · `knowledge_records.py`

来源：[src/video_localizer/knowledge_records.py](../../src/video_localizer/knowledge_records.py)；基线 36 行。

Original candidate identities survive archival without rewriting their bytes.

显式相对导入模块：`common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`non_use_only(record)`|9||
|`archives(root)`|14||
|`resolve(root, relative, digest=None)`|19||
|`candidate_files(root)`|31||

### C · `knowledge_review.py`

来源：[src/video_localizer/knowledge_review.py](../../src/video_localizer/knowledge_review.py)；基线 203 行。

Attributed review decisions and a finite queue; never activate rules implicitly.

显式相对导入模块：`candidate_index`, `common`, `knowledge`, `knowledge_records`, `learning`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`decisions(root)`|15||
|`sources(root)`|50||
|`closed_sources(root)`|69|Include only inbox pointers whose exact linked candidate was reviewed closed.|
|`queue(root=None, include_closed=False)`|83||
|`review(spec, root=None)`|105||
|`archive_preview(relative, root=None)`|160||
|`archive(relative, expected, root=None)`|182||

### C · `knowledge_usage.py`

来源：[src/video_localizer/knowledge_usage.py](../../src/video_localizer/knowledge_usage.py)；基线 113 行。

Actual-use feedback binds the selected revision, plan, video and durable evidence.

显式相对导入模块：`common`, `knowledge_records`, `knowledge_review`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`record(run, spec, root=None)`|12||
|`followup(run, root=None)`|71||
|`alerts(context, root=None)`|94||

### C · `languages.py`

来源：[src/video_localizer/languages.py](../../src/video_localizer/languages.py)；基线 39 行。

Resolve project-specific language shorthand before creating a task.

显式相对导入模块：`common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`resolve(value, root=None)`|8||

### C · `layout.py`

来源：[src/video_localizer/layout.py](../../src/video_localizer/layout.py)；基线 55 行。

Measured native type placement, bounded to the reviewed source text region.

显式相对导入模块：`common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`overlaps(a, b)`|9||
|`validate(item, meta)`|15||
|`font_size(item)`|26|Measure the actual font instead of letting a long translation cover its neighbors.|

### C · `learning.py`

来源：[src/video_localizer/learning.py](../../src/video_localizer/learning.py)；基线 267 行。

Permanent learning cases: methods and bounded evidence, never production assets.

显式相对导入模块：`candidate_index`, `common`, `evidence`, `knowledge`, `knowledge_maintenance`, `knowledge_records`, `knowledge_review`, `learning_evidence`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`capture_case(case_id, lesson, scope, root=None, run=None, video_sha256=None, records=(), status='candidate', visibility='private', references=None)`|13||
|`verify_entry(entry, root=None)`|75||
|`audit(root=None)`|125||
|`enqueue(candidate, root=None)`|154|Durable, idempotent input to later distillation; never activates a rule.|
|`record_project_candidate(candidate, root=None)`|166|Route technical learning into the project; raw observations stay private.|
|`promote(spec_path, root=None)`|192|Publish an explicitly reviewed method and self-contained evidence case.|

### C · `learning_evidence.py`

来源：[src/video_localizer/learning_evidence.py](../../src/video_localizer/learning_evidence.py)；基线 63 行。

Bounded examples are not a second copy of a complete production audit.

显式相对导入模块：`common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`select(run, video_sha256=None, history=False)`|7||

### C · `library.py`

来源：[src/video_localizer/library.py](../../src/video_localizer/library.py)；基线 242 行。

Local delivery catalog. Packages survive loss of runs; they are not knowledge.

显式相对导入模块：`common`, `fast_delivery`, `quality_holds`, `resources`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`source_folder(root, source_sha256)`|11|Use an explicitly registered demand name; hashes remain source identity.|
|`_bound_assets(value)`|24||
|`_asset_closure(run, roots)`|36|Follow preparation's bound inputs; preserve their exact run-relative paths.|
|`export(run, root=None, video_sha256=None, reuse_manifests=())`|58|Archive a delivered result or an explicitly selected historical reference.  A reference with a revise decision remains a reference, never a passed delivery.|
|`find(source_sha256, target_language=None, root=None)`|208||

### C · `local_audio.py`

来源：[src/video_localizer/local_audio.py](../../src/video_localizer/local_audio.py)；基线 110 行。

Existing narration mixer, promoted to a resumable project capability.

显式相对导入模块：`common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`source_track(run)`|8||
|`pcm(path)`|24||
|`save(path, values, rate)`|32||
|`mix(run)`|39||

### C · `local_tts.py`

来源：[src/video_localizer/local_tts.py](../../src/video_localizer/local_tts.py)；基线 95 行。

Read-only reuse of historical local narration takes; new speech uses Gemini TTS.

显式相对导入模块：`common`, `resources`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`_voice(code_root, identity, locale)`|10||
|`_engine_version(code_root)`|30||
|`_take(run, signature, voice)`|37||
|`generate(run, relative, code_root=CODE_ROOT)`|56||

### C · `maintenance.py`

来源：[src/video_localizer/maintenance.py](../../src/video_localizer/maintenance.py)；基线 189 行。

Incremental task-scoped housekeeping; durable packages are never cache targets.

显式相对导入模块：`common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`_context(run)`|9||
|`_plain(root, path)`|18||
|`register(run, relative, reason)`|28|Register one completed, rebuildable file, never a whole unbounded folder.|
|`status(run)`|43||
|`_empty(root, directory)`|52||
|`_references(root, candidates)`|70|Conservative references in records; failure to read prevents cache eviction.|
|`maintain(run, close=False, stage='manual')`|109||
|`after_stage(run, stage)`|173|Housekeeping may defer but can never turn a produced video into a failure.|

### C · `media.py`

来源：[src/video_localizer/media.py](../../src/video_localizer/media.py)；基线 338 行。

显式相对导入模块：`captions`, `common`, `timing`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`command(args, cwd=None, timeout=240)`|13||
|`probe(path)`|25||
|`ffmpeg(args, cwd=None)`|42||
|`ass_filter(filename)`|46||
|`cut(source, start, end, output)`|51||
|`scene_points(source, duration)`|57|Candidate visual cuts, never a reviewed text/pose timeline.|
|`extract(source, directory, interval=1.0, max_clip=8.0)`|69||
|`contact_sheets(frames, directory, columns=4, per_page=32, width=240)`|106||
|`tools_available()`|122||
|`ass_time(seconds)`|126||
|`ass_text(value)`|134||
|`render_local(source, segment, instances, meta, directory)`|138||
|`normalize(source, duration, meta, output)`|189||
|`restore_regions(source, edited, segment, regions, directory)`|201|Copy explicitly preserved source regions over a model edit before local typesetting.|
|`retime(source, duration, output, reason)`|220|Explicit experiment mapping; unplanned normalization still rejects duration changes.|
|`render_foreground(source, segment, instances, meta, directory)`|234|Typeset reviewed target copy on an already text-free video, without erasing pixels.|
|`render_reference(source, segment, instances, meta, directory, run)`|290|Approximate occluded animation with reviewed plates; retain source outside explicit mattes.|
|`assemble(visuals, audio_source, output, duration)`|325||

### C · `model_cache.py`

来源：[src/video_localizer/model_cache.py](../../src/video_localizer/model_cache.py)；基线 56 行。

Single-writer ASR model installation with complete-file receipts.

显式相对导入模块：`common`, `model_routing`, `resources`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`files(directory)`|11||
|`verify(directory)`|20||
|`ensure(size=None, download=False, root=CODE_ROOT, downloader=None)`|28||

### C · `model_routing.py`

来源：[src/video_localizer/model_routing.py](../../src/video_localizer/model_routing.py)；基线 70 行。

One current model per specialist capability; history is never resubmitted implicitly.

显式相对导入模块：`budgets`, `common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`policy(root=None)`|7||
|`selected(capability, root=None)`|16||
|`require_current(capability, model, root=None)`|22||
|`require_audio_analysis_model(model, run=None, authorization=None)`|28||
|`require_remote_task(model, root=None, run=None, authorization=None)`|49||

### C · `model_tasks.py`

来源：[src/video_localizer/model_tasks.py](../../src/video_localizer/model_tasks.py)；基线 292 行。

Journaled, source-bound KIE audio tasks and small diagnostic video probes.

显式相对导入模块：`batches`, `budgets`, `captions`, `common`, `cost`, `kie`, `model_routing`, `workflow`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`packet(run, relative)`|16||
|`_authorized_rate_limit_retry(run, job)`|144|An explicit 429 rejection has no accepted task; keep its old cost reservation.|
|`submit(run, relative, client=None, retry_failed=False)`|154||
|`_resume_undispatched(run, data, job, path, client)`|245||
|`collect(run, job, urls)`|269|Keep every returned stem, its original name, signal report and content hash.|

### C · `native_composition.py`

来源：[src/video_localizer/native_composition.py](../../src/video_localizer/native_composition.py)；基线 96 行。

Small reusable native-timeline composition primitives.

Do not stretch short model video to fill source time. Protected pixels come from
the corresponding source frame, never a frozen donor from another timestamp.

显式相对导入模块：`common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`preserve_regions(frame, source_frame, boxes)`|13||
|`require_native_timing(source_frames, output_frames, source_fps, output_fps)`|22||
|`audit_regions(source, output, regions)`|27|Compare sequential, same-index decoded regions; encoder loss is explicit.|
|`replace_speech_window(run, mixed_path, accompaniment, voice, start, end, offset, rate=44100)`|61||

### C · `ocr.py`

来源：[src/video_localizer/ocr.py](../../src/video_localizer/ocr.py)；基线 69 行。

Exact-input OCR caching and compact candidates, never a visual acceptance gate.

显式相对导入模块：`common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`signature(source, step, crop_top, model_files)`|8||
|`cached(path, expected)`|13||
|`store(path, data)`|24||
|`infer(image, engine, seen, crop_top)`|29|Reuse only byte-identical sampled pixels, not approximate frame similarity.|
|`summary(data)`|42||

### C · `ocr_supplement.py`

来源：[src/video_localizer/ocr_supplement.py](../../src/video_localizer/ocr_supplement.py)；基线 15 行。

Read-only historical GLM evidence. No network or inference path.

显式相对导入模块：`common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`context(run, source_sha256)`|4||
|`supplement(*args, **kwargs)`|14||

### C · `prepared.py`

来源：[src/video_localizer/prepared.py](../../src/video_localizer/prepared.py)；基线 93 行。

Bind a reusable visual repair master to its source and preparation evidence.

显式相对导入模块：`captions`, `common`, `quality_holds`, `visual_audit`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`verify(run, asset, source_sha256)`|6||
|`verify_for_production(run, asset, source_sha256, root=None)`|29|Require a reviewed neutral master before language rendering.  verify() remains an integrity check for restoring historical/failed packages. A valid archive is not approval to use its visual repair in another output.|
|`render(run, segment, items, meta, directory, source_sha256)`|75||

### C · `production.py`

来源：[src/video_localizer/production.py](../../src/video_localizer/production.py)；基线 154 行。

Reusable local production steps. AI decisions and observed reviews stay explicit.

显式相对导入模块：`cli`, `common`, `finalization`, `library`, `model_routing`, `prepared`, `quality_holds`, `render_cache`, `visual_audit`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`_fingerprint(run, plan)`|9||
|`advance(run, deliver=False, force_render=False)`|51||
|`advance_batch(batch_id, deliver=False, root=ROOT)`|108||
|`tts_packet(run, voice, estimate, speech_ids=None)`|132||

### C · `quality_holds.py`

来源：[src/video_localizer/quality_holds.py](../../src/video_localizer/quality_holds.py)；基线 103 行。

Append-only, exact-asset quality objections independent of runs and deliveries.

显式相对导入模块：`common`, `evidence`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`_branch(root, source_sha256, asset_sha256)`|14||
|`active(source_sha256, asset_sha256, root=None)`|21||
|`require_clear(source_sha256, asset_sha256, root=None)`|53||
|`record(spec_path, root=None)`|59|Capture attributed feedback and evidence; never alter a historical package.|

### C · `render_cache.py`

来源：[src/video_localizer/render_cache.py](../../src/video_localizer/render_cache.py)；基线 63 行。

Verified local segment reuse across plan revisions; model-result audio is excluded.

显式相对导入模块：`common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`implementation_signature()`|9||
|`signature(run, plan, segment, inventory, meta)`|22||
|`restore(run, key)`|47||
|`save(run, key, path)`|60||

### C · `repair.py`

来源：[src/video_localizer/repair.py](../../src/video_localizer/repair.py)；基线 432 行。

Source-bound local repair recipes, risk probes and a durable trial budget.

显式相对导入模块：`common`, `resources`, `runtime`, `timing`, `visual_audit`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`preflight(run, detect_cuts=False)`|14||
|`_load(run, relative)`|51||
|`_active(op, n, t)`|82||
|`_geometry(op, t)`|88||
|`_mask(frame, op, t, cv2, np)`|100||
|`_special(original, proposal, op, cv2, np)`|133|Parameterized legacy operations; intervals/coordinates belong in recipes.|
|`_engine()`|167||
|`execute(run, relative, probe=False, extension_reason=None)`|179||
|`_execute(run, recipe, source, relative, folder, probe, deadline=None)`|244||
|`_alive(pid)`|401||
|`reconcile(run, reason)`|416|Resolve a dead local process without clearing locks or retrying any model.|

### C · `repair_frames.py`

来源：[src/video_localizer/repair_frames.py](../../src/video_localizer/repair_frames.py)；基线 59 行。

Reuse exact decoded repair frames from completed lossless masters, not reviews.

显式相对导入模块：`common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`pixel_hash(frame)`|7||
|`class PreviousFrames`|11||
|`PreviousFrames.__init__(self, run, keys, cv2)`|12||
|`PreviousFrames.get(self, n)`|34||
|`PreviousFrames.close(self)`|53||

### C · `repair_masks.py`

来源：[src/video_localizer/repair_masks.py](../../src/video_localizer/repair_masks.py)；基线 41 行。

Explicit source-pixel selectors; thresholds belong to reviewed task recipes.

显式相对导入模块：`common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`select(frame, region, spec, cv2, np)`|5||

### C · `request_tts.py`

来源：[src/video_localizer/request_tts.py](../../src/video_localizer/request_tts.py)；基线 120 行。

Explicit human-authorized, request-bound Microsoft speech generation.

This optional adapter does not change the default provider or use KIE credentials.

显式相对导入模块：`batches`, `budgets`, `common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`validate(run, relative)`|17||
|`_generate(run, spec, job, job_path)`|56||
|`generate(run, relative)`|97||

### C · `resources.py`

来源：[src/video_localizer/resources.py](../../src/video_localizer/resources.py)；基线 91 行。

Bounded workspace compute and disk admission; never deletes data or steals locks.

显式相对导入模块：`common`, `timing`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`settings(root)`|14||
|`preflight(root, destination=None, required_bytes=0)`|27||
|`heavy(run, stage, required_bytes=0)`|42||
|`admission(run, stage)`|72||
|`status(root=ROOT)`|80||

### C · `retention.py`

来源：[src/video_localizer/retention.py](../../src/video_localizer/retention.py)；基线 345 行。

Preserve observations before an explicit, fail-closed run deletion.

显式相对导入模块：`common`, `evidence`, `learning_evidence`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`files(run)`|17||
|`blockers(run)`|28||
|`_run(root, run)`|62||
|`preserve(run, root=None)`|71||
|`inspect(run, root=None)`|129||
|`delete(run, root=None, execute=False, expected=None)`|164||
|`prune(run, root=None, execute=False, expected=None)`|186|Evict superseded generated pictures after the normal preservation gates.  Current source, candidate, released preparations, all JSON observations and recipes remain. A pruned old audit is explicitly incomplete, never approved.|
|`_live_references(root, exclude_run=None)`|237|Conservative closure of active manifests; historical versions are not roots.|
|`prune_versions(run, relative, root=None, execute=False, expected=None)`|281|Explicitly retire obsolete videos, retaining independent bounded error evidence.|

### C · `reuse.py`

来源：[src/video_localizer/reuse.py](../../src/video_localizer/reuse.py)；基线 72 行。

Copy a reviewed neutral master and its evidence without copying locale decisions.

显式相对导入模块：`common`, `prepared`, `timing`, `workflow`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`neutral(target, source, source_shot, target_shot)`|11||

### C · `routing.py`

来源：[src/video_localizer/routing.py](../../src/video_localizer/routing.py)；基线 64 行。

Validate the Agent's content judgment and reasons without choosing its method.

显式相对导入模块：`common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`translation_domains(inventory)`|8||
|`validate(inventory, request, run, entries=None, duration=None)`|15|Versioned intake gate; historical requests gain no fabricated assessment.|

### C · `runtime.py`

来源：[src/video_localizer/runtime.py](../../src/video_localizer/runtime.py)；基线 55 行。

Project-owned tools and caches; no host-specific Codex paths.

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`vision_path(root)`|12|Image-processing dependencies have one current installation location.|
|`configure(root)`|17||
|`report(root)`|39||

### C · `source_state.py`

来源：[src/video_localizer/source_state.py](../../src/video_localizer/source_state.py)；基线 147 行。

Exact-source extraction cache. Reused observations never approve a new translation.

显式相对导入模块：`common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`parameters(root)`|17||
|`observations(inventory)`|23|Only source descriptions and geometry; translated timing/layout stay in their locale run.|
|`save(run, root=None)`|43||
|`verify(entry, root, source_sha256)`|86||
|`find(source_sha256, root=None)`|99||
|`restore(run, root=None)`|112||

### C · `storage.py`

来源：[src/video_localizer/storage.py](../../src/video_localizer/storage.py)；基线 102 行。

Read-only inventory: logical copies are not equivalent to reclaimable disk space.

显式相对导入模块：`common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`report(root=None, duplicates=False)`|22||

### C · `storage_policy.py`

来源：[src/video_localizer/storage_policy.py](../../src/video_localizer/storage_policy.py)；基线 145 行。

User-adjustable storage budgets and read-only planning, never a deletion API.

显式相对导入模块：`common`, `retention`, `storage`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`_validate(policy)`|17||
|`settings(root=None)`|37||
|`configure(root=None, *, area=None, max_count=None, max_gib=None, minimum_free_gib=None)`|56||
|`_run_summary(run, root, policy)`|82|A completed result is not proof that deletion/financial closure is safe.|
|`plan(root=None)`|105||

### C · `surface.py`

来源：[src/video_localizer/surface.py](../../src/video_localizer/surface.py)；基线 60 行。

Verify and composite a source-bound transparent typography video layer.

显式相对导入模块：`common`, `layout`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`instance_bindings(items)`|6||
|`verify(run, asset, source_sha256, target_language, items)`|12||
|`composite(source, layer, duration, directory)`|45||

### C · `timing.py`

来源：[src/video_localizer/timing.py](../../src/video_localizer/timing.py)；基线 85 行。

Local stage measurements; elapsed work is not provider compute or human review time.

显式相对导入模块：`common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`timed(stage)`|17||
|`directory(run)`|30||
|`measure(run, stage)`|36||
|`report(runs)`|61||

### C · `visual_audit.py`

来源：[src/video_localizer/visual_audit.py](../../src/video_localizer/visual_audit.py)；基线 491 行。

Native-size comparison evidence and explicit per-instance review contracts.

No detector or evidence generator may assign pass. Local owners can edit code/files;
this validates attributable observations, not whether a person actually saw pixels.

显式相对导入模块：`common`, `crop_stream`, `prepared`, `quality_holds`, `visual_reuse`, `visual_storage`, `workflow`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`_asset(run, value)`|28||
|`_shot_items(inventory, shot=None)`|34||
|`context(run, stage, shot_id=None, asset=None, clocks=None)`|43||
|`directory(run, binding)`|106||
|`_timestamps(path)`|112||
|`_clock(path, cache)`|121||
|`required_frames(item, times, offset, features)`|129||
|`_region(item, width, height)`|143||
|`_selection(numbers)`|155||
|`_extract(path, numbers, region, destination)`|165||
|`_template(binding, row)`|175||
|`generate(run, stage='final', shot_id=None, reuse_decode=True)`|185||
|`_verify_files(folder, manifest)`|336||
|`_meaningful(text)`|344||
|`_review_valid(record, row, binding)`|349||
|`review(run, manifest_relative, observation_relative)`|378||
|`verify_bundle(folder, binding, review_index=None)`|403||
|`verify_final(run)`|435||
|`verify_neutral(run, asset)`|442||
|`release_neutral(run, shot_id)`|458||

### C · `visual_notes.py`

来源：[src/video_localizer/visual_notes.py](../../src/video_localizer/visual_notes.py)；基线 178 行。

Concise human/agent input; expand identifiers, never invent observations or passes.

显式相对导入模块：`common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`_frames(values, row)`|7||
|`_expand(packet, note, row, binding)`|25||
|`submit(run, manifest_relative, notes_relative)`|57||
|`pages(run, manifest_relative, instance_id, max_height=1600, layer='all', after_frame=None, limit=None, columns=1)`|98|Lossless native-pixel gallery; disposable views are outside the evidence manifest.|

### C · `visual_reuse.py`

来源：[src/video_localizer/visual_reuse.py](../../src/video_localizer/visual_reuse.py)；基线 189 行。

Reuse verified comparison tiles before decoding, never review decisions.

Indexes reference existing lossless evidence pages; they do not duplicate media.
Missing pages are cache misses. Changed pages fail closed and remain inspectable.

显式相对导入模块：`common`, `crop_stream`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`tile(image, label)`|15||
|`class EvidenceCache`|23||
|`EvidenceCache.__init__(self, root)`|24||
|`EvidenceCache.identity(self, path, **parameters)`|42||
|`EvidenceCache.verify_inputs(self)`|49||
|`EvidenceCache._path(self, relative)`|53||
|`EvidenceCache._read(self, path, identity)`|58||
|`EvidenceCache._write(self, path, identity, value)`|65||
|`EvidenceCache.clock(self, path, loader)`|68||
|`EvidenceCache.tiles(self, path, numbers, region, label, selection)`|82||
|`EvidenceCache.restore_page(self, references, destination, store)`|93||
|`EvidenceCache.load(self, entry, size)`|115||
|`EvidenceCache.commit(self)`|141||
|`class TileStream`|149||
|`TileStream.__init__(self, cache, key, path, numbers, region, label, selection, available)`|150||
|`TileStream.__enter__(self)`|161||
|`TileStream.__getitem__(self, number)`|164||
|`TileStream.fingerprint(self, number)`|172||
|`TileStream.remember(self, number, page, box, pixels_sha256, page_size, tile_hashes)`|180||
|`TileStream.__exit__(self, kind, value, traceback)`|187||

### C · `visual_storage.py`

来源：[src/video_localizer/visual_storage.py](../../src/video_localizer/visual_storage.py)；基线 68 行。

Reuse identical lossless comparison pixels, never review decisions.

显式相对导入模块：`common`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`class PageStore`|9||
|`PageStore.__init__(self, root)`|10||
|`PageStore._copy(self, source, destination)`|20||
|`PageStore.reuse(self, source, destination, key, digest)`|31||
|`PageStore.save(self, image, destination)`|40||
|`PageStore.commit(self)`|65||

### C · `work_packet.py`

来源：[src/video_localizer/work_packet.py](../../src/video_localizer/work_packet.py)；基线 189 行。

Compact stage guidance from existing state and knowledge; no invented reviews.

显式相对导入模块：`batches`, `cli`, `common`, `knowledge`, `knowledge_advisories`, `knowledge_usage`, `library`, `maintenance`, `model_routing`, `quality_holds`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`_next_action(run, state, jobs)`|30||
|`build(run, stage=None)`|55||

### C · `workflow.py`

来源：[src/video_localizer/workflow.py](../../src/video_localizer/workflow.py)；基线 1145 行。

显式相对导入模块：`batches`, `budgets`, `codex_visual`, `common`, `contracts`, `cost`, `fast_delivery`, `finalization`, `kie`, `knowledge`, `knowledge_advisories`, `languages`, `model_routing`, `model_tasks`, `prepared`, `quality_holds`, `routing`, `visual_audit`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`source_path(run)`|18||
|`profile_path(run)`|25||
|`create_run(video, target, brief, name, source_url=None)`|32||
|`ingest(url, target, brief, name)`|64||
|`analyze(run)`|76||
|`execution_limits(run)`|102||
|`analyze_audio(run, client=None, candidate=False, model=None, transcribe_only=False, voice_review=False, retry_upload=False, model_authorization=None)`|131|One journaled multimodal audio analysis; never infer speech from the video captions.|
|`current_plan(run)`|319||
|`_revision_signature(plan, inventory)`|369|Count a changed recipe once when only provenance locations were rebound.|
|`_check_revision_budget(run, plan, inventory, maximum_rounds)`|382||
|`build_plan(run, experiment=None)`|398||
|`prepare_packet(run, segment_id)`|598||
|`reserved_credits(job, fallback)`|707|Terminal provider billing replaces a reservation; unknown outcomes keep it reserved.|
|`reused_model_result(run, segment, packet)`|715|Reuse an existing paid result only for an identical provider request/assets.|
|`submit(run, segment_id, client=None, retry_failed=False)`|735||
|`poll(run, job_id, wait_seconds=0, client=None)`|808||
|`render(run, force_segments=False)`|849||
|`quality(run)`|956||
|`valid_evidence(run, paths)`|1106||
|`deliver(run)`|1111||

### C · `workspace.py`

来源：[src/video_localizer/workspace.py](../../src/video_localizer/workspace.py)；基线 127 行。

Initialize a portable workspace outside the executable checkout, without credentials.

显式相对导入模块：`common`, `learning`。这里只列AST可直接识别的模块名，不是运行时依赖闭包。

|函数 / 类方法及签名|基线行|实现自述（如有）|
|---|---|---|
|`public_files(source)`|18||
|`_checked_files(source, paths)`|31||
|`source_files(source)`|47|The portable source boundary shared by export and repository checks.|
|`_copy(target, files)`|58||
|`initialize(destination, source=None)`|66||
|`export(destination, source=None)`|79|Create a runnable source distribution for a fresh operator simulation.|
|`verify_export(directory)`|110||

