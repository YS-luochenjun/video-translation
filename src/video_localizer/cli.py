from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, audio as audio_tools, blind, bundles, captions, curation, evidence, learning, library, media, retention, source_state, workflow
from .common import CODE_ROOT, ROOT, WorkflowError, file_hash, get_run, guarded, inside, load_key, read_json, require, write_json
from .kie import KieClient, AUDIO_MODELS
from .knowledge import context_for, reflect, retrieve, source_references
from .model_routing import policy as routing_policy, selected


def doctor(online=False):
    from .runtime import report as runtime_report
    tools = media.tools_available()
    try:
        load_key()
        key = "configured_value_withheld"
    except WorkflowError:
        key = "missing"
    result = {"version": __version__, "python": sys.version.split()[0], "media_tools": tools,
              "workspace": str(ROOT), "code_root": str(CODE_ROOT),
              "kie_key": key, "scope": "Local readiness; no model generation proof"}
    result['runtime'] = runtime_report(CODE_ROOT)
    result['model_routing'] = routing_policy(ROOT)
    for relative in ("config/workspace.json", "config/quality.json", "knowledge/index.json", "config/mcp.json"):
        read_json(ROOT / relative)
    if online:
        result["kie_credits"] = KieClient().credits()
        result["scope"] = "Authenticated credit read; model generation still needs a real task"
    return result


@guarded
def capture(run):
    candidate = read_json(run / "outputs/candidate.json")
    source = inside(run, candidate["path"])
    require(file_hash(source) == candidate["sha256"], "Capture candidate video changed")
    directory = run / "review" / candidate["sha256"][:12]
    directory.mkdir(parents=True, exist_ok=True)
    # Other reviewers may create this directory first. Cache the actual outputs,
    # not the existence of their shared parent; an interrupted capture is resumable.
    pages_path = directory / "contact-pages.json"
    pages = read_json(pages_path) if pages_path.exists() else []
    frames_complete = bool(pages) and all((directory / f"frame-{n:05d}.jpg").is_file()
        for n in range(1, pages[-1]["last_frame"]+1))
    if not frames_complete:
        media.ffmpeg(["-i", source, "-vf", "fps=2,scale=480:-1", "-pix_fmt", "yuvj420p", "-q:v", "2", directory / "frame-%05d.jpg"])
    if not frames_complete or any(not (directory / p["file"]).is_file() for p in pages):
        media.contact_sheets(directory, directory)
    actual = media.probe(source)
    if actual["has_audio"] and not (directory / "audio.wav").is_file():
        media.ffmpeg(["-i", source, "-vn", "-ac", "1", "-ar", "16000", directory / "audio.wav"])
    duration = actual["duration"]
    video_stream = next(stream for stream in actual["raw"]["streams"] if stream["codec_type"] == "video")
    video_end = min(duration, float(video_stream.get("duration", duration)))
    for name, timestamp in (("boundary-start.jpg", 0), ("boundary-end.jpg", max(0, video_end-0.05))):
        if not (directory / name).exists():
            media.ffmpeg(["-ss", timestamp, "-i", source, "-frames:v", "1", "-pix_fmt", "yuvj420p", "-q:v", "2", directory / name])
        require((directory / name).is_file(), "Boundary frame was not decoded; inspect the actual video stream timeline")
    if (run / "plan.json").exists():
        plan = read_json(run / "plan.json")
        if plan["id"] == candidate["plan_id"]:
            for segment in plan["segments"][1:]:
                for label, offset in (("pre", -1/30), ("at", 0), ("post", 1/30)):
                    image = directory / f"seam-{segment['id']}-{label}.jpg"
                    if not image.exists():
                        media.ffmpeg(["-ss", max(0, min(duration-0.05, segment["start"]+offset)), "-i", source,
                                      "-frames:v", "1", "-pix_fmt", "yuvj420p", "-q:v", "2", image])
    policy = read_json(run / "analysis/inventory.json")["audio"]
    audio_check = audio_tools.evaluate(workflow.source_path(run), source, policy,
                                       read_json(run / "analysis/media.json")["duration"])
    write_json(directory / "audio-report.json", audio_check)
    inventory = read_json(run / "analysis/inventory.json")
    if inventory.get("audio", {}).get("has_speech") is True:
        # Decode around each planned word/phrase, including one-frame pre/post.
        for item in captions.track(inventory):
            for index, unit in enumerate(item["units"]):
                times = (unit["start"]-1/30, unit["start"], (unit["start"]+unit["end"])/2,
                         unit["end"]-1/30, unit["end"])
                for position, timestamp in enumerate(times):
                    frame = directory / f"caption-{item['id']}-{index:03d}-{position}.jpg"
                    if not frame.exists():
                        media.ffmpeg(["-ss", max(0, min(video_end-.05, timestamp)), "-i", source,
                                      "-frames:v", "1", "-pix_fmt", "yuvj420p", "-q:v", "2", frame])
        report = directory / "caption-sync.json"
        if not report.exists():
            wav = directory / "audio.wav"
            asset = {"path": wav.relative_to(run).as_posix(), "sha256": file_hash(wav)} if wav.is_file() else {}
            write_json(report, captions.review_template(run, candidate, inventory, asset))
    record = {"video_sha256": file_hash(source), "files": {path.relative_to(run).as_posix(): file_hash(path)
              for path in sorted(directory.rglob('*')) if path.is_file()},
              "sampling_fps": 2, "limitation": "Sampling can miss transient defects; inspect boundary frames/full playback as needed"}
    write_json(run / "review/capture.json", record)
    return {"capture": str(directory.relative_to(ROOT)), "files": len(record["files"])}


def status(run):
    record = read_json(run / "run.json")
    jobs = [read_json(path) for path in sorted((run / "jobs").glob("*.json"))]
    quality = read_json(run / "outputs/quality.json") if (run / "outputs/quality.json").exists() else None
    state = "created"
    preparation_blockers = []
    if (run / "analysis/inventory.json").exists():
        state = "awaiting_agent_inventory"
        inventory = read_json(run / 'analysis/inventory.json')
        if all(inventory.get('coverage', {}).get(key, {}).get('status') == 'reviewed'
               for key in ('visual', 'speech', 'timeline')):
            state = 'needs_planning'
            # Planning cannot consume an unreviewed master. Report the real
            # checkpoint, without changing any artifact or supplying a pass.
            if not (run / 'plan.json').exists():
                from .prepared import verify_for_production
                for shot in inventory.get('shots', []):
                    if shot.get('prepared_video'):
                        try:
                            verify_for_production(run, shot['prepared_video'], record['source_sha256'])
                        except (WorkflowError, OSError, KeyError, ValueError) as exc:
                            preparation_blockers.append({'shot': shot['id'], 'reason': str(exc)})
                if preparation_blockers:
                    state = 'needs_neutral_review'
    if (run / "plan.json").exists():
        try:
            workflow.current_plan(run)
            state = "planned"
        except WorkflowError:
            state = "needs_replanning"
    if state == "planned" and jobs:
        relevant = [job for job in jobs if job["plan_id"] == read_json(run / "plan.json")["id"]]
        state = "needs_reconciliation" if any(job["state"] in ("ambiguous", "submitting", "preparing") for job in relevant) else "awaiting_model" if any(job["state"] in ("submitted", "waiting", "queuing", "generating") for job in relevant) else state
    if (run / "outputs/candidate.json").exists() and state not in ("needs_replanning", "needs_reconciliation"):
        candidate = read_json(run / "outputs/candidate.json")
        if (run / "plan.json").exists() and candidate["plan_id"] == read_json(run / "plan.json")["id"]:
            state = "needs_review"
            review_path = run / "review/review.json"
            if quality and quality["video_sha256"] == candidate["sha256"] and quality["plan_id"] == candidate["plan_id"] and (
                    quality.get("review_sha256") is None or review_path.exists() and file_hash(review_path) == quality["review_sha256"]):
                state = "ready_to_deliver" if quality["decision"] == "pass" else "needs_revision"
            if (run / "outputs/delivery.json").exists() and state == "ready_to_deliver":
                delivery = read_json(run / "outputs/delivery.json")
                final = inside(run, delivery["video"])
                if delivery["sha256"] == candidate["sha256"] and final.exists() and file_hash(final) == delivery["sha256"]:
                    state = "delivered"
    completion = run / 'outputs/completion.json'
    if completion.is_file():
        completed = read_json(completion)
        final = run / 'outputs/final.mp4'
        if final.is_file() and file_hash(final) == completed.get('video_sha256'):
            state = 'delivered_with_issues'
    return {"state": state, "run": {key: value for key, value in record.items() if key != "state"},
            "jobs": jobs, "quality": quality, 'preparation_blockers': preparation_blockers}


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Agent-operated advertisement video localization")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("doctor", help="Local tools/config; --online checks KIE credits only")
    command.add_argument("--online", action="store_true")
    commands.add_parser("check", help="Run tests with this same working Python interpreter")
    commands.add_parser('kie-authorization', help='Show this workspace owner authorization, without credentials')
    commands.add_parser('resources', help='Show local compute owners and free disk space; never cleans or unlocks')
    commands.add_parser('model-routing', help='Show Codex responsibilities and the five specialist model roles')
    command = commands.add_parser('codex-packet', help='Bind actual images and project knowledge for Codex recognition or image editing')
    command.add_argument('run')
    command.add_argument('--stage', choices=['recognize', 'image'], default='recognize')
    command.add_argument('--spec', help='Run-relative JSON with optional images and instructions')
    command = commands.add_parser('codex-result', help='Register actual Codex observations/edited images; never auto-approve')
    command.add_argument('run')
    command.add_argument('packet')
    command.add_argument('report')
    command = commands.add_parser('asr', help='Whisper small transcription of actual audio; no acceptance claim')
    command.add_argument('run')
    command.add_argument('--audio')
    command.add_argument('--model', choices=[selected('asr')], default=selected('asr'))
    command.add_argument('--download', action='store_true')
    command.add_argument('--no-vad', action='store_true')
    command.add_argument('--language', help='Optional recognition hint, not independent language detection')
    command = commands.add_parser('audio-mix', help='Resume the existing narration-plan mixer without rewriting scripts')
    command.add_argument('run')
    command = commands.add_parser('maintain', help='Incremental housekeeping; --close preserves then retires a settled delivered run')
    command.add_argument('run')
    command.add_argument('--close', action='store_true')
    command = commands.add_parser('scratch-register', help='Register one rebuildable task-owned work/runs/RUN file')
    command.add_argument('run')
    command.add_argument('path')
    command.add_argument('--reason', required=True)
    command = commands.add_parser('work-packet', help='Read current blockers, exact job IDs and stage-specific AI work/knowledge')
    command.add_argument('run')
    command.add_argument('--stage', choices=['source', 'translation', 'neutral', 'render', 'review', 'delivery'])
    command = commands.add_parser('visual-evidence', help='Generate native-size comparison evidence and pending per-instance templates')
    command.add_argument('run')
    command.add_argument('--stage', choices=['neutral', 'final'], default='final')
    command.add_argument('--shot')
    command.add_argument('--no-decode-cache', action='store_true',
                         help='Decode new evidence from media; keep existing immutable bundles and review gates')
    command = commands.add_parser('visual-review', help='Record ONE attributed instance observation; never auto-fill pass')
    command.add_argument('run')
    command.add_argument('manifest')
    command.add_argument('observation')
    command = commands.add_parser('visual-notes', help='Expand concise individual notes; explicit coverage and decisions required')
    command.add_argument('run')
    command.add_argument('manifest')
    command.add_argument('notes')
    command = commands.add_parser('visual-pages', help='Build reusable native-pixel galleries without approving evidence')
    command.add_argument('run')
    command.add_argument('manifest')
    command.add_argument('--instance', required=True)
    command.add_argument('--max-height', type=int, default=1600)
    command.add_argument('--columns', type=int, default=1, help='Native-pixel gallery columns, 1..4; no frame sampling')
    command.add_argument('--layer', default='all', help='Actual strip layer label: all, source, neutral-0, final')
    command.add_argument('--after-frame', type=int)
    command.add_argument('--limit', type=int, default=2, help='At most four native gallery pages per response')
    command = commands.add_parser('repair-preflight', help='Risk windows for source cuts, blurred text and watermark edges; never approval')
    command.add_argument('run')
    command = commands.add_parser('repair-run', help='Execute a source-bound local repair recipe with durable trial budget')
    command.add_argument('run')
    command.add_argument('recipe')
    command.add_argument('--probe', action='store_true')
    command.add_argument('--extension-reason')
    command = commands.add_parser('repair-reconcile', help='Resolve a dead local repair process after checking operation locks')
    command.add_argument('run')
    command.add_argument('--reason', required=True)
    command = commands.add_parser('run-prune', help='Evict superseded generated comparison pictures after run-preserve')
    command.add_argument('run')
    command.add_argument('--execute', action='store_true')
    command.add_argument('--expect')
    command = commands.add_parser('run-prune-versions', help='Retire explicitly selected obsolete videos with independent failure evidence')
    command.add_argument('run')
    command.add_argument('spec')
    command.add_argument('--execute', action='store_true')
    command.add_argument('--expect')
    command = commands.add_parser('visual-release-neutral', help='Release a neutral shot only after all individual observations pass')
    command.add_argument('run')
    command.add_argument('--shot', required=True)
    command = commands.add_parser('budget-open', help='Host/operator: register one actual human request, never a worker run or retry')
    command.add_argument('spec')
    command = commands.add_parser('budget-bind', help='Bind an existing or derived run to the same request budget')
    command.add_argument('run')
    command.add_argument('--parent-run')
    command = commands.add_parser('budget-status', help='Read whole-request spending across all runs and batches')
    command.add_argument('id')
    command = commands.add_parser('fast-register', help='Bind a native-timing composition and open basic review; never auto-pass')
    command.add_argument('run')
    command.add_argument('recipe')
    command = commands.add_parser('finalize', help='Deliver the best complete translated video with disclosed issues, without quality approval')
    command.add_argument('run')
    command.add_argument('spec', nargs='?', default='review/finalization.json')
    command = commands.add_parser('compose-best', help='Compose existing translated shot layers and best plates without strict visual approval or model calls')
    command.add_argument('run')
    command = commands.add_parser('reuse-neutral', help='Bind a reviewed exact-source neutral master without locale decisions')
    command.add_argument('run')
    command.add_argument('--from-run', required=True)
    command.add_argument('--source-shot', required=True)
    command.add_argument('--target-shot', required=True)
    command = commands.add_parser('batch-create', help='Create locale runs sharing one source-duration request budget')
    command.add_argument('id')
    command.add_argument('video')
    command.add_argument('--targets', nargs='+', required=True)
    command.add_argument('--brief', default='完整本地化广告，保留品牌、音乐、音效和运动。')
    command.add_argument('--reused', action='store_true', help='Use the lower existing incremental-reuse budget')
    for name in ('batch-status', 'batch-approve', 'batch-run'):
        command = commands.add_parser(name)
        command.add_argument('id')
        if name == 'batch-run':
            command.add_argument('--deliver', action='store_true')
        if name == 'batch-approve':
            command.add_argument('--best-available', action='store_true',
                                 help='Expand from a finalized complete fast pilot while retaining its disclosed issues; no quality/master approval')
    command = commands.add_parser('production', help='Resume local plan/render/capture/quality steps; never invent reviews or submit paid tasks')
    command.add_argument('run')
    command.add_argument('--deliver', action='store_true')
    command.add_argument('--force-render', action='store_true')
    command = commands.add_parser('timing', help='Report measured stage durations and unobserved gaps')
    command.add_argument('run')
    command = commands.add_parser('tts-packet', help='Build a reusable exact-copy TTS packet without calling KIE')
    command.add_argument('run')
    command.add_argument('--voice', required=True)
    command.add_argument('--estimate', required=True, type=float)
    command.add_argument('--speech-ids', nargs='+')
    command = commands.add_parser('local-tts', help='Reuse existing hash-bound local narration takes; new speech uses tts-packet')
    command.add_argument('run')
    command.add_argument('spec')
    command = commands.add_parser('close-failure', help='Preserve attributed preproduction failures without inventing a final candidate')
    command.add_argument('run')
    command.add_argument('spec')
    command = commands.add_parser("workspace-init", help="Create an independent workspace with public knowledge and policy")
    command.add_argument("destination")
    command = commands.add_parser("workspace-export", help="Create a fresh runnable source copy without local data or credentials")
    command.add_argument("destination")
    command = commands.add_parser("workspace-verify", help="Verify an exported source/public knowledge baseline")
    command.add_argument("directory")
    command = commands.add_parser("storage-report", help="Read-only lifecycle and storage inventory")
    command.add_argument("--duplicates", action="store_true", help="Hash files to measure repeated logical bytes; never deletes")
    command = commands.add_parser("storage-policy", help="Show/set advisory storage limits; never deletes")
    command.add_argument("action", choices=["show", "set"], nargs="?", default="show")
    command.add_argument("--area", choices=["runs", "outputs", "media"])
    command.add_argument("--max-count", type=int)
    command.add_argument("--max-gib", type=float)
    command.add_argument("--minimum-free-gib", type=float)
    commands.add_parser("storage-plan", help="Read-only limit/closure report; no automatic eviction")
    commands.add_parser("delivery-index", help="Refresh a portable video browsing page without media copies")
    command = commands.add_parser("quality-hold", help="Record an evidence-bound quality objection without rewriting history")
    command.add_argument("spec")
    commands.add_parser("knowledge-audit", help="Verify permanent knowledge without depending on runs or outputs")
    command = commands.add_parser("knowledge-queue", help="Show unresolved adoption/revision work, not more automatic candidates")
    command.add_argument("--include-closed", action="store_true")
    command = commands.add_parser("knowledge-review", help="Record an attributed adoption, gap, or historical-only decision")
    command.add_argument("spec")
    command = commands.add_parser("candidate-archive", help="Preview or archive fully accounted candidate originals with provenance")
    command.add_argument("path")
    command.add_argument("--execute", action="store_true")
    command.add_argument("--expect")
    command = commands.add_parser("knowledge-use", help="Bind actual use/non-use feedback to plan, video and evidence")
    command.add_argument("run")
    command.add_argument("spec")
    command = commands.add_parser("language-resolve", help="Resolve the project's target-language aliases without a video")
    command.add_argument("language")
    command = commands.add_parser("knowledge-evidence", help="Append reviewed independent evidence without rewriting historical cases")
    command.add_argument("spec")
    command = commands.add_parser("source-find", help="Find verified exact-source extraction snapshots")
    command.add_argument("source_sha256")
    for name in ("source-save", "run-preserve", "run-delete"):
        command = commands.add_parser(name)
        command.add_argument("run")
        if name == "run-delete":
            command.add_argument("--execute", action="store_true", help="Delete only after preservation and all gates pass")
            command.add_argument("--expect", help="Exact fingerprint returned by the latest ready preview")
    command = commands.add_parser("hooks", help="Project-owned knowledge maintenance; no paid media models")
    command.add_argument("action", choices=["status", "baseline", "run", "prepare", "apply"])
    command.add_argument("--due", action="store_true", help="Only run after project daily time, once per successful sweep")
    command.add_argument("--response", help="Project-relative structured answer from any reasoning engine")
    command = commands.add_parser("knowledge-promote", help="Publish a reviewed method and independent evidence using a sourced spec")
    command.add_argument("spec")
    command = commands.add_parser("archive", help="Create a standalone local delivery/reuse package")
    command.add_argument("run")
    command = commands.add_parser("archive-verify", help="Check all bytes within a standalone package")
    command.add_argument("package")
    command = commands.add_parser("archive-restore", help="Restore a historical package into a new working run")
    command.add_argument("package")
    command.add_argument("--id", required=True)
    command = commands.add_parser("library-find", help="Find exact-source packages, reporting expired packages honestly")
    command.add_argument("source_sha256")
    command.add_argument("--target")
    command = commands.add_parser("model-task", aliases=["audio-task"], help="Inspect historical packets or submit current Gemini TTS/Wan tasks")
    command.add_argument("run")
    command.add_argument("packet")
    command.add_argument("--execute", action="store_true")
    command.add_argument("--retry-failed", action="store_true")
    command = commands.add_parser("captions", help="Compile reviewed final-mix alignment; --apply updates inventory, no paid call")
    command.add_argument("run")
    command.add_argument("--alignment", required=True, help="Run-relative reviewed alignment JSON")
    command.add_argument("--apply", action="store_true")
    command = commands.add_parser("caption-check", help="Read-only audiovisual caption gate; does not regenerate video")
    command.add_argument("run")
    for name, label in (("init", "video"), ("ingest", "url")):
        command = commands.add_parser(name)
        command.add_argument(label)
        command.add_argument("--target", default="zh-CN")
        command.add_argument("--brief", default="将视频完整本地化为指定目标语言的自然广告，保留品牌与产品。")
        command.add_argument("--id", required=True)
    for name in ("analyze", "audio-analyze", "plan", "packet", "submit", "poll", "render", "capture", "quality", "deliver", "reflect", "context", "status"):
        command = commands.add_parser(name)
        command.add_argument("run")
        if name in ("packet", "submit"):
            command.add_argument("segment")
        if name == "submit":
            command.add_argument("--execute", action="store_true", help="Actually upload and create a paid KIE job")
            command.add_argument("--retry-failed", action="store_true", help="One explicit retry of a terminal zero-cost provider failure")
        if name == "audio-analyze":
            command.add_argument('--model',choices=AUDIO_MODELS,default=selected('audio_analysis'))
            command.add_argument('--model-authorization',help='Run-relative source/request-bound human grant for an alternative analysis model')
            command.add_argument('--retry-upload',action='store_true',help='Retry a journaled transport failure before model submission; preserves prior attempt and budget')
            command.add_argument('--transcribe-only',action='store_true',help='Transcribe actual candidate audio alone; does not claim comparative music/FX review')
            command.add_argument('--voice-review',action='store_true',help='Compare actual character voice distinction and consistency; requires --candidate')
            command.add_argument("--execute", action="store_true", help="Upload audio and run one journaled KIE Gemini audio analysis")
            command.add_argument("--candidate", action="store_true", help="Compare source with captured candidate; transcribe actual output and review retained music/effects")
        if name == "plan":
            command.add_argument("--experiment", choices=["local_overlay", "model_edit"])
        if name == "poll":
            command.add_argument("job")
            command.add_argument("--wait", type=int, default=0, choices=range(46), metavar="0..45")
    command = commands.add_parser("knowledge")
    command.add_argument("--target", default="zh-CN")
    command = commands.add_parser("demo", help="Generate a known synthetic English advertisement fixture")
    command.add_argument("--id", default="demo-local")
    command.add_argument("--route", choices=["local_overlay", "model_edit"], default="local_overlay")
    command.add_argument("--seconds", type=float, default=8, help="Synthetic fixture length, 1-180 seconds")
    command = commands.add_parser("blind")
    command.add_argument("action", choices=["freeze", "verify", "reveal"])
    command.add_argument("run")
    command.add_argument("candidates", nargs="*")
    args = parser.parse_args(argv)
    try:
        name = args.command
        if name == "doctor":
            result = doctor(args.online)
        elif name == 'model-routing':
            result = routing_policy(ROOT)
        elif name == 'kie-authorization':
            from .batches import authorization
            result = authorization(ROOT)
        elif name == 'budget-open':
            from .budgets import open_request
            result = open_request(args.spec, ROOT)
        elif name == 'budget-status':
            from .budgets import status as budget_status
            result = budget_status(args.id, ROOT)
        elif name.startswith('batch-'):
            from . import batches, production
            if name == 'batch-create':
                result = batches.create(args.id, args.video, args.targets, args.brief, args.reused, ROOT)
            elif name == 'batch-approve':
                result = batches.approve(args.id, ROOT, best_available=args.best_available)
            elif name == 'batch-run':
                result = production.advance_batch(args.id, args.deliver, ROOT)
            else:
                result = batches.status(args.id, ROOT)
        elif name == "language-resolve":
            from .languages import resolve
            result = resolve(args.language)
        elif name == "workspace-init":
            from .workspace import initialize
            result = initialize(args.destination)
        elif name in ("workspace-export", "workspace-verify"):
            from .workspace import export, verify_export
            result = export(args.destination) if name == "workspace-export" else verify_export(args.directory)
        elif name == "storage-report":
            from .storage import report
            result = report(duplicates=args.duplicates)
        elif name == "storage-policy":
            from .storage_policy import configure, settings
            if args.action == "show":
                require(not any(value is not None for value in
                                (args.area, args.max_count, args.max_gib, args.minimum_free_gib)),
                        "Use storage-policy set to change limits")
                result = settings()
            else:
                result = configure(area=args.area, max_count=args.max_count, max_gib=args.max_gib,
                                   minimum_free_gib=args.minimum_free_gib)
        elif name == "storage-plan":
            from .storage_policy import plan as storage_plan
            result = storage_plan()
        elif name == "delivery-index":
            from .delivery_index import refresh
            result = refresh()
        elif name == "quality-hold":
            from .quality_holds import record
            result = record(args.spec)
        elif name == "hooks":
            if args.action == "status":
                result = curation.status(ROOT)
            elif args.action == "baseline":
                result = curation.baseline(ROOT)
            else:
                require(args.action != "apply" or args.response, "hooks apply requires --response")
                result = curation.execute(ROOT, due_only=args.due, prepare_only=args.action == "prepare",
                                          response_file=args.response if args.action == "apply" else None)
        elif name == "knowledge-audit":
            result = learning.audit(ROOT)
        elif name == "knowledge-queue":
            from .knowledge_review import queue
            result = {"items": [{k: v for k, v in row.items() if k not in {"record", "decision"}}
                                for row in queue(ROOT, args.include_closed)]}
        elif name == "knowledge-review":
            from .knowledge_review import review
            result = review(read_json(inside(ROOT, args.spec)), ROOT)
        elif name == "candidate-archive":
            from .knowledge_review import archive, archive_preview
            require(not args.execute or args.expect, "Archive requires --expect <preview fingerprint>")
            result = archive(args.path, args.expect, ROOT) if args.execute else archive_preview(args.path, ROOT)
        elif name == "knowledge-use":
            from .knowledge_usage import record
            run = get_run(args.run)
            result = record(run, read_json(inside(run, args.spec)), ROOT)
        elif name == "knowledge-evidence":
            result = evidence.supplement(args.spec, ROOT)
        elif name == "source-find":
            result = source_state.find(args.source_sha256, ROOT)
        elif name == "knowledge-promote":
            result = learning.promote(args.spec, ROOT)
        elif name == "archive-verify":
            package = inside(ROOT / "outputs", str(Path(args.package).relative_to("outputs")))
            verified = bundles.verify(package)
            result = {"decision": "pass", "files": len(verified["files"]), "metadata": verified["metadata"]}
        elif name == "archive-restore":
            import re
            require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", args.id), "Invalid restore run id")
            package = inside(ROOT / "outputs", str(Path(args.package).relative_to("outputs")))
            result = bundles.extract(package, inside(ROOT / "runs", args.id))
        elif name == "library-find":
            result = library.find(args.source_sha256, args.target, ROOT)
        elif name == 'resources':
            from .resources import status as resource_status
            result = resource_status(ROOT)
        elif name == "check":
            import subprocess
            return subprocess.run([sys.executable, str(CODE_ROOT / "bin/check.py")], cwd=CODE_ROOT).returncode
        elif name in ("init", "ingest"):
            result = workflow.create_run(args.video, args.target, args.brief, args.id) if name == "init" else workflow.ingest(args.url, args.target, args.brief, args.id)
        elif name == "knowledge":
            result = retrieve({"workflow": "video-localization", "target_language": args.target, "tags": ["text", "timing", "ads"]})
        elif name == "demo":
            from .demo import create_demo
            result = create_demo(args.id, args.route, args.seconds)
        else:
            run = get_run(args.run)
            if name == 'work-packet':
                from .work_packet import build
                result = build(run, args.stage)
            elif name == 'repair-preflight':
                from .repair import preflight
                result = preflight(run, detect_cuts=True)
            elif name == 'repair-run':
                from .repair import execute
                result = execute(run, args.recipe, args.probe, args.extension_reason)
            elif name == 'repair-reconcile':
                from .repair import reconcile
                result = reconcile(run, args.reason)
            elif name == 'run-prune':
                result = retention.prune(run, ROOT, args.execute, args.expect)
            elif name == 'run-prune-versions':
                result = retention.prune_versions(run, args.spec, ROOT, args.execute, args.expect)
            elif name == 'asr':
                from .asr import transcribe
                result = transcribe(run, args.audio, args.model, args.download, not args.no_vad, args.language)
            elif name == 'codex-packet':
                from .codex_visual import packet
                result = packet(run, args.stage, args.spec, root=ROOT)
            elif name == 'codex-result':
                from .codex_visual import record
                result = record(run, args.packet, args.report, root=ROOT)
            elif name == 'audio-mix':
                from .local_audio import mix
                result = mix(run)
            elif name == 'local-tts':
                from .local_tts import generate
                result = generate(run, args.spec)
            elif name == 'close-failure':
                from .failure_closure import close
                result = close(run, args.spec)
            elif name == 'visual-evidence':
                from .visual_audit import generate
                result = generate(run, args.stage, args.shot, reuse_decode=not args.no_decode_cache)
            elif name == 'visual-review':
                from .visual_audit import review as visual_review
                result = visual_review(run, args.manifest, args.observation)
            elif name == 'visual-notes':
                from .visual_notes import submit
                result = submit(run, args.manifest, args.notes)
            elif name == 'visual-pages':
                from .visual_notes import pages
                result = pages(run, args.manifest, args.instance, args.max_height,
                               args.layer, args.after_frame, args.limit, args.columns)
            elif name == 'visual-release-neutral':
                from .visual_audit import release_neutral
                result = release_neutral(run, args.shot)
            elif name == 'budget-bind':
                from .budgets import bind
                result = bind(run, get_run(args.parent_run) if args.parent_run else None)
            elif name == 'reuse-neutral':
                from .reuse import neutral
                result = neutral(run, get_run(args.from_run), args.source_shot, args.target_shot)
            elif name == 'production':
                from .production import advance
                result = advance(run, args.deliver, args.force_render)
            elif name == 'timing':
                from .timing import report
                result = report([run])
            elif name == 'tts-packet':
                from .production import tts_packet
                result = tts_packet(run, args.voice, args.estimate, args.speech_ids)
            elif name == 'fast-register':
                from .fast_delivery import register
                result = register(run, args.recipe)
            elif name == 'maintain':
                from .maintenance import maintain
                result = maintain(run, close=args.close)
            elif name == 'scratch-register':
                from .maintenance import register
                result = register(run, args.path, args.reason)
            elif name == 'finalize':
                from .finalization import finish
                result = finish(run, args.spec)
            elif name == 'compose-best':
                from .finalization import compose
                result = compose(run)
            elif name == "source-save":
                result = source_state.save(run, ROOT)
            elif name == "run-preserve":
                result = retention.preserve(run, ROOT)
            elif name == "run-delete":
                result = retention.delete(run, ROOT, args.execute, args.expect)
            elif name in ("audio-task", "model-task"):
                from . import model_tasks
                result = model_tasks.submit(run, args.packet, retry_failed=args.retry_failed) if args.execute else model_tasks.packet(run, args.packet)
            elif name == "archive":
                result = library.export(run, root=ROOT)
            elif name == "captions":
                result = captions.apply_alignment(run, args.alignment, args.apply)
            elif name == "caption-check":
                capture_path = run / "review/capture.json"
                candidate = read_json(run / "outputs/candidate.json")
                require(file_hash(inside(run, candidate["path"])) == candidate["sha256"], "Caption check candidate video changed")
                result = captions.evaluate(run, candidate,
                    read_json(run / "analysis/inventory.json"), read_json(capture_path) if capture_path.exists() else {},
                    read_json(ROOT / "config/quality.json")["caption_sync"], read_json(run / "plan.json"))
            elif name == "analyze":
                result = workflow.analyze(run)
            elif name == "audio-analyze":
                require(args.execute, "audio-analyze is a paid model request; pass --execute explicitly")
                result = workflow.analyze_audio(run, candidate=args.candidate, model=args.model,
                                                transcribe_only=args.transcribe_only,voice_review=args.voice_review,
                                                retry_upload=args.retry_upload,
                                                model_authorization=({'path': args.model_authorization,
                                                    'sha256': file_hash(inside(run, args.model_authorization))}
                                                    if args.model_authorization else None))
            elif name == "plan":
                result = workflow.build_plan(run, args.experiment)
            elif name in ("packet", "submit"):
                result = workflow.submit(run, args.segment, retry_failed=args.retry_failed) if name == "submit" and args.execute else workflow.prepare_packet(run, args.segment)
            elif name == "poll":
                result = workflow.poll(run, args.job, args.wait)
            elif name == "render":
                result = workflow.render(run)
            elif name == "capture":
                result = capture(run)
            elif name == "quality":
                result = workflow.quality(run)
            elif name == "deliver":
                result = workflow.deliver(run)
            elif name == "reflect":
                result = reflect(run)
            elif name == "context":
                from .batches import authorization, binding
                from .knowledge_advisories import retrieve as advisory_retrieve
                from .knowledge import related_source_references
                source_sha256 = file_hash(workflow.source_path(run))
                inventory_path = run / "analysis/inventory.json"
                inventory = read_json(inventory_path) if inventory_path.exists() else {"source_sha256": source_sha256}
                request = read_json(run / "inputs/request.json")
                ocr_path = run / 'analysis/ocr-summary.json'
                ocr_candidates = None
                if ocr_path.exists():
                    summary = read_json(ocr_path)
                    require(summary['source_sha256'] == source_sha256, 'OCR summary source mismatch')
                    ocr_candidates = {'path': 'analysis/ocr-summary.json', 'complete': summary.get('complete'),
                        'tracks': len(summary['candidate_tracks']), 'low_confidence_tracks': summary['low_confidence_tracks'],
                        'instructions': 'Historical evidence only. Codex must inspect actual images; candidate times do not establish exact boundaries.'}
                result = {"entry": "AGENTS.md", "request": read_json(run / "inputs/request.json"),
                          'historical_ocr_candidates': ocr_candidates,
                          'visual_executor': {'provider': 'codex', 'entry': 'codex-packet',
                                              'result_entry': 'codex-result', 'automatic_pass': False},
                          'model_routing': routing_policy(ROOT),
                          "kie_authorization": authorization(ROOT),
                          "batch_ledger": str(binding(run)) if binding(run) else None,
                          "inventory": "analysis/inventory.json", "model_policy": read_json(ROOT / 'config/model-policy.json') if (ROOT / 'config/model-policy.json').exists() else {},
                          "knowledge_context": context_for(request, inventory), "knowledge": retrieve(context_for(request, inventory)),
                          "source_references": source_references(context_for(request, inventory), root=ROOT),
                          "related_source_references": related_source_references(context_for(request, inventory), root=ROOT),
                          "knowledge_advisories": advisory_retrieve(context_for(request, inventory), ROOT),
                          "source_snapshots": source_state.find(source_sha256, ROOT),
                          "reusable_packages": library.find(source_sha256, root=ROOT),
                          "instructions": "Read matched knowledge files, inspect evidence, decide and record; credentials are loaded only by the executor"}
            elif name == "status":
                result = status(run)
            elif name == "blind":
                result = blind.freeze(run, args.candidates) if args.action == "freeze" else blind.verify(run) if args.action == "verify" else blind.reveal(run)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        if name in ('production', 'batch-run') and result.get('state') in ('needs_inventory', 'needs_review', 'needs_attention'):
            return 2
        return 2 if name in ("quality", "caption-check") and result["decision"] not in ("pass", "not_applicable") else 0
    except (WorkflowError, KeyError, TypeError, ValueError, OSError) as exc:
        # No raw requests, headers, credentials or signed result URLs in CLI errors.
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

