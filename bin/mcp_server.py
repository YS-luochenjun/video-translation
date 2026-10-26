"""Minimal stdio MCP bridge. Newline-delimited JSON-RPC, no web server or credentials in config."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from video_localizer import workflow
from video_localizer.cli import capture, doctor
from video_localizer.common import ROOT, WorkflowError, get_run, inside, read_json
from video_localizer.knowledge import retrieve


def schema(properties=None, required=None):
    return {"type": "object", "properties": properties or {}, "required": required or [], "additionalProperties": False}


RUN = schema({"run": {"type": "string"}}, ["run"])
TOOLS = [
    {"name": "localizer_knowledge_queue", "description": "Read unresolved knowledge adoption and revision work with attribution", "inputSchema": schema(), "annotations": {"readOnlyHint": True}},
    {"name": "localizer_knowledge_advisories", "description": "Recall at most three scoped unverified observations; separate from active rules", "inputSchema": schema({"target_language": {"type": "string"}, "source_sha256": {"type": "string"}, "features": {"type": "string"}}, ["target_language"]), "annotations": {"readOnlyHint": True}},
    {"name": "localizer_knowledge_use", "description": "Record actual knowledge use or non-use against frozen plan, video and durable evidence; no rule activation", "inputSchema": schema({"run": {"type": "string"}, "spec": {"type": "string"}}, ["run", "spec"])},
    {"name": "localizer_codex_packet", "description": "Prepare real images and project knowledge for Codex text recognition/image editing; no automatic inference", "inputSchema": schema({"run": {"type": "string"}, "stage": {"type": "string", "enum": ["recognize", "image"]}, "spec": {"type": "string"}}, ["run"])},
    {"name": "localizer_codex_result", "description": "Bind actual Codex observations and edited images; existing visual quality gates still apply", "inputSchema": schema({"run": {"type": "string"}, "packet": {"type": "string"}, "report": {"type": "string"}}, ["run", "packet", "report"])},
    {"name": "localizer_model_routing", "description": "Read the current five specialist roles and Codex visual responsibilities", "inputSchema": schema(), "annotations": {"readOnlyHint": True}},
    {"name": "localizer_local_tts", "description": "Reuse existing hash-bound local narration; new speech uses Gemini TTS, no automatic approval", "inputSchema": schema({"run": {"type": "string"}, "spec": {"type": "string"}}, ["run", "spec"])},
    {"name": "localizer_close_failure", "description": "Preserve observed preproduction failure and independent evidence; no candidate or budget reset", "inputSchema": schema({"run": {"type": "string"}, "spec": {"type": "string"}}, ["run", "spec"])},
    {"name": "localizer_maintain", "description": "Task-scoped housekeeping; optional closure preserves evidence before retiring a settled delivered run", "inputSchema": schema({"run": {"type": "string"}, "close": {"type": "boolean"}}, ["run"])},
    {"name": "localizer_work_packet", "description": "Read current stage, blockers and bounded knowledge; no automatic approval", "inputSchema": schema({"run": {"type": "string"}, "stage": {"type": "string", "enum": ["source", "translation", "neutral", "render", "review", "delivery"]}}, ["run"]), "annotations": {"readOnlyHint": True}},
    {"name": "localizer_production", "description": "Resume existing local production; never submits paid jobs or invents reviews", "inputSchema": RUN},
    {"name": "localizer_compose_best", "description": "Compose existing translated layers and best available plates; no paid calls or quality approval", "inputSchema": RUN},
    {"name": "localizer_finalize", "description": "Output the complete translated result with disclosed defects; preserves failed quality records", "inputSchema": schema({"run": {"type": "string"}, "spec": {"type": "string"}}, ["run"])},
    {"name": "localizer_doctor", "description": "Check local runtime without a network call", "inputSchema": schema(), "annotations": {"readOnlyHint": True}},
    {"name": "localizer_analyze", "description": "Extract media assets and pending inventory for an existing run", "inputSchema": RUN},
    {"name": "localizer_plan", "description": "Validate agent inventory and build a scoped execution plan", "inputSchema": RUN},
    {"name": "localizer_render", "description": "Assemble reviewed local or completed model segments", "inputSchema": RUN},
    {"name": "localizer_capture", "description": "Capture current candidate evidence for review", "inputSchema": RUN},
    {"name": "localizer_quality", "description": "Check technical contract and attributed per-instance review", "inputSchema": RUN},
    {"name": "localizer_visual_evidence", "description": "Generate native comparisons and pending observations; no automatic pass", "inputSchema": schema({"run": {"type": "string"}, "stage": {"type": "string", "enum": ["neutral", "final"]}, "shot": {"type": "string"}}, ["run"])},
    {"name": "localizer_visual_review", "description": "Submit one actual attributed instance observation, never bulk pass", "inputSchema": schema({"run": {"type": "string"}, "manifest": {"type": "string"}, "observation": {"type": "string"}}, ["run", "manifest", "observation"])},
    {"name": "localizer_visual_notes", "description": "Expand concise individual notes, explicit frames and decisions required", "inputSchema": schema({"run": {"type": "string"}, "manifest": {"type": "string"}, "notes": {"type": "string"}}, ["run", "manifest", "notes"])},
    {"name": "localizer_visual_pages", "description": "Bounded native galleries with actual layer selection and next-frame cursor; never approval", "inputSchema": schema({"run": {"type": "string"}, "manifest": {"type": "string"}, "instance": {"type": "string"}, "layer": {"type": "string"}, "after_frame": {"type": "string"}, "limit": {"type": "string"}, "columns": {"type": "integer", "minimum": 1, "maximum": 4}}, ["run", "manifest", "instance"])},
    {"name": "localizer_repair_preflight", "description": "Candidate cuts and risk windows; no media submission or approval", "inputSchema": RUN},
    {"name": "localizer_repair_recipe", "description": "Execute bounded source-bound local repair; default probe, no paid calls, approval stays pending", "inputSchema": schema({"run": {"type": "string"}, "recipe": {"type": "string"}, "mode": {"type": "string", "enum": ["probe", "full"]}, "extension_reason": {"type": "string"}}, ["run", "recipe"])},
    {"name": "localizer_visual_release_neutral", "description": "Release neutral preparation only after per-instance review", "inputSchema": schema({"run": {"type": "string"}, "shot": {"type": "string"}}, ["run", "shot"])},
    {"name": "localizer_knowledge", "description": "Retrieve active scoped methods; pass source hash and comma-separated content features when known", "inputSchema": schema({"target_language": {"type": "string"}, "source_sha256": {"type": "string"}, "features": {"type": "string"}}, ["target_language"]), "annotations": {"readOnlyHint": True}}
]


def handle(message):
    if "id" not in message:
        return None
    response = {"jsonrpc": "2.0", "id": message["id"]}
    method, params = message.get("method"), message.get("params", {})
    try:
        if method == "initialize":
            response["result"] = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                                  "serverInfo": {"name": "ad-localizer", "version": "0.1.0"}}
        elif method == "ping":
            response["result"] = {}
        elif method == "tools/list":
            response["result"] = {"tools": TOOLS}
        elif method == "tools/call":
            name, arguments = params.get("name"), params.get("arguments", {})
            spec = next((item for item in TOOLS if item["name"] == name), None)
            if spec is None:
                raise WorkflowError("Unknown tool")
            contract = spec["inputSchema"]
            if set(arguments) - set(contract["properties"]) or not set(contract["required"]).issubset(arguments) or not all(isinstance(v, str) for v in arguments.values()):
                raise WorkflowError("Invalid tool arguments")
            if name == "localizer_doctor":
                value = doctor()
            elif name == 'localizer_model_routing':
                from video_localizer.model_routing import policy
                value = policy()
            elif name == 'localizer_codex_packet':
                from video_localizer.codex_visual import packet
                value = packet(get_run(arguments['run']), arguments.get('stage', 'recognize'), arguments.get('spec'))
            elif name == 'localizer_codex_result':
                from video_localizer.codex_visual import record
                value = record(get_run(arguments['run']), arguments['packet'], arguments['report'])
            elif name == 'localizer_local_tts':
                from video_localizer.local_tts import generate
                value = generate(get_run(arguments['run']), arguments['spec'])
            elif name == 'localizer_close_failure':
                from video_localizer.failure_closure import close
                value = close(get_run(arguments['run']), arguments['spec'])
            elif name == 'localizer_maintain':
                from video_localizer.maintenance import maintain
                value = maintain(get_run(arguments['run']), close=arguments.get('close', False))
            elif name == 'localizer_work_packet':
                from video_localizer.work_packet import build
                value = build(get_run(arguments['run']), arguments.get('stage'))
            elif name == 'localizer_production':
                from video_localizer.production import advance
                value = advance(get_run(arguments['run']))
            elif name == 'localizer_compose_best':
                from video_localizer.finalization import compose
                value = compose(get_run(arguments['run']))
            elif name == 'localizer_finalize':
                from video_localizer.finalization import finish
                value = finish(get_run(arguments['run']), arguments.get('spec', 'review/finalization.json'))
            elif name == 'localizer_repair_preflight':
                from video_localizer.repair import preflight
                value = preflight(get_run(arguments['run']), detect_cuts=True)
            elif name == 'localizer_repair_recipe':
                from video_localizer.repair import execute
                mode=arguments.get('mode','probe')
                if mode not in ('probe','full'): raise WorkflowError('Invalid repair mode')
                value=execute(get_run(arguments['run']),arguments['recipe'],mode=='probe',arguments.get('extension_reason'))
            elif name == "localizer_knowledge_queue":
                from video_localizer.knowledge_review import queue
                value = {"items": [{k: v for k, v in row.items() if k not in {"record", "decision"}} for row in queue(ROOT)]}
            elif name == "localizer_knowledge_use":
                from video_localizer.knowledge_usage import record
                run = get_run(arguments["run"])
                value = record(run, read_json(inside(run, arguments["spec"])), ROOT)
            elif name in {"localizer_knowledge", "localizer_knowledge_advisories"}:
                features = [v.strip() for v in arguments.get("features", "").split(",") if v.strip()]
                from video_localizer.knowledge_advisories import retrieve as retrieve_advisories
                reader = retrieve if name == "localizer_knowledge" else retrieve_advisories
                value = reader({"workflow": "video-localization", **arguments, "features": features,
                                  "tags": ["text", "timing", "ads", *features]})
            elif name.startswith('localizer_visual_'):
                from video_localizer import visual_audit
                run = get_run(arguments['run'])
                if name == 'localizer_visual_evidence':
                    value = visual_audit.generate(run, arguments.get('stage', 'final'), arguments.get('shot'))
                elif name == 'localizer_visual_review':
                    value = visual_audit.review(run, arguments['manifest'], arguments['observation'])
                elif name == 'localizer_visual_notes':
                    from video_localizer.visual_notes import submit
                    value = submit(run, arguments['manifest'], arguments['notes'])
                elif name == 'localizer_visual_pages':
                    from video_localizer.visual_notes import pages
                    value = pages(run, arguments['manifest'], arguments['instance'], layer=arguments.get('layer','all'),
                                  after_frame=int(arguments['after_frame']) if 'after_frame' in arguments else None,
                                  limit=int(arguments.get('limit','2')), columns=arguments.get('columns',1))
                else:
                    value = visual_audit.release_neutral(run, arguments['shot'])
            else:
                run = get_run(arguments["run"])
                functions = {"localizer_analyze": workflow.analyze, "localizer_plan": workflow.build_plan,
                             "localizer_render": workflow.render, "localizer_capture": capture, "localizer_quality": workflow.quality}
                value = functions[name](run)
            response["result"] = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}], "isError": False}
        else:
            response["error"] = {"code": -32601, "message": "Method not found"}
    except (WorkflowError, KeyError, ValueError, TypeError, OSError) as exc:
        response["result"] = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    return response


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        try:
            result = handle(json.loads(line))
        except ValueError:
            result = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        if result is not None:
            print(json.dumps(result, ensure_ascii=False), flush=True)

