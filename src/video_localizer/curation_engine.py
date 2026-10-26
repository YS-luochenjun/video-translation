"""Replaceable reasoning interface; the engine returns data and never writes knowledge."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .common import WorkflowError, read_json, require, write_json


GROUP_FIELDS = {
    "event_ids": {"type": "array", "items": {"type": "string"}},
    "merge_into": {"type": "string"}, "same_meaning": {"type": "boolean"},
    "title": {"type": "string"}, "trigger": {"type": "string"},
    "action": {"type": "string"}, "failure_signature": {"type": "string"},
    "limitations": {"type": "array", "items": {"type": "string"}},
    "next_counterexample_test": {"type": "string"},
    "conflict_with_rules": {"type": "boolean"}
}
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["groups", "pending"],
          "properties": {
              "groups": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                         "required": list(GROUP_FIELDS), "properties": dict(GROUP_FIELDS)}},
              "pending": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                          "required": ["event_id", "reason"], "properties": {
                              "event_id": {"type": "string"}, "reason": {"type": "string"}}}}}}

# Optional on old stored replies; new reasoning must propose an adoption destination.
SCHEMA["properties"]["groups"]["items"]["properties"]["adoption"] = {
    "type": "object", "additionalProperties": False, "required": ["action", "target_ids", "reason", "missing_evidence"],
    "properties": {"action": {"type": "string", "enum": ["merge_existing", "new_method", "source_case", "pending"]},
                   "target_ids": {"type": "array", "items": {"type": "string"}}, "reason": {"type": "string"},
                   "missing_evidence": {"type": "array", "items": {"type": "string"}}}}


def executable(root):
    local = root / "config/hooks.local.json"
    configured = read_json(local).get("codex_executable") if local.exists() else None
    choices = [configured, shutil.which("codex")]
    # Desktop updates may rotate the bundled CLI path. This is executable discovery,
    # not a dependency on the desktop scheduler or a running app.
    folder = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI/Codex/bin"
    if folder.is_dir():
        choices.extend(str(p) for p in sorted(folder.glob("*/codex.exe"), key=lambda p: p.stat().st_mtime, reverse=True))
    return next((str(p) for p in choices if p and Path(p).is_file()), None)


def codex_cli(packet, prompt, job, root, timeout):
    """One text-only inference in an isolated directory, without project/media tools."""
    binary = executable(root)
    require(binary, "Curation engine unavailable: install a Codex CLI or use hooks prepare/apply")
    directory = job / "engine"
    directory.mkdir(exist_ok=True)
    write_json(directory / "schema.json", SCHEMA)
    output = directory / "response.json"
    output.unlink(missing_ok=True)
    argv = [binary, "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
            "--sandbox", "read-only", "--cd", str(directory), "--color", "never", "--json",
            "--output-schema", str(directory / "schema.json"), "--output-last-message", str(output)]
    # No global MCPs/plugins, apps, hooks, browser, media generation, shell, or other agents.
    for feature in ("apps", "hooks", "multi_agent", "multi_agent_v2", "memories", "shell_tool",
                    "browser_use", "computer_use", "image_generation", "code_mode"):
        argv.extend(["-c", f"features.{feature}=false"])
    argv.extend(["-c", 'web_search="disabled"', "-c", "mcp_servers={}", "-"])
    env = {key: value for key, value in os.environ.items()
           if not (key.startswith("KIE_") or key in {"OPENAI_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"})}
    try:
        completed = subprocess.run(argv, input=prompt + "\n\n<packet>\n" + json.dumps(packet, ensure_ascii=False) + "\n</packet>",
                                   cwd=directory, env=env, capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise WorkflowError("Curation text inference timed out; source checkpoint remains unchanged") from exc
    # Raw stderr can contain endpoint details. Persist only bounded structured accounting.
    usage = None
    for line in completed.stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        item = event.get("item", {})
        require(item.get("type") not in {"command_execution", "mcp_tool_call", "web_search", "file_change"},
                "Text-only curation engine attempted a tool call; response rejected")
        if event.get("type") == "turn.completed":
            usage = event.get("usage")
    write_json(job / "engine-receipt.json", {"engine": "codex_cli", "exit_code": completed.returncode,
               "usage": usage, "paid_media_model_calls": 0, "paid_media_model_credits": 0})
    require(completed.returncode == 0 and output.is_file(),
            "Curation text engine failed; check CLI login/connectivity. No knowledge or checkpoint was advanced")
    return read_json(output)
