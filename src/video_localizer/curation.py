"""Project-owned daily knowledge loop: select, reason, validate, persist candidates."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import curation_engine, learning
from .common import ROOT, WorkflowError, file_hash, inside, lock, object_hash, read_json, require, utc_now, write_json

STATE = "knowledge/local/curation"
SOURCES = ("knowledge/candidates", "knowledge/local/candidates", "knowledge/local/inbox", "knowledge/local/feedback")
SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")


def settings(root):
    value = read_json(root / "config/hooks.json")["knowledge_daily"]
    require(value["timezone"] == "Asia/Shanghai", "This hook currently supports Asia/Shanghai")
    require(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value["time"]), "Invalid hook time")
    require(value["engine"] in {"codex_cli", "packet"}, "Unknown curation engine")
    require(1 <= value["max_records"] <= 100 and 1000 <= value["max_packet_bytes"] <= 1000000,
            "Invalid curation batch limits")
    require(10 <= value["timeout_seconds"] <= 600, "Invalid curation timeout")
    return value


def source_files(root):
    from .knowledge_review import closed_sources
    from .knowledge_records import non_use_only, evidence_payload
    closed = closed_sources(root)
    files = []
    for directory in SOURCES:
        base = inside(root, directory)
        if base.is_dir():
            files.extend(p for p in base.rglob("*") if p.is_file() and p.suffix in {".json", ".md"}
                         and not p.name.startswith("index") and p.resolve().is_relative_to(base.resolve()))
    return sorted(p for p in set(files) if (p.relative_to(root).as_posix(), file_hash(p)) not in closed
                  and not any(part in {"bundle", "evidence"} for part in p.relative_to(root).parts)
                  and not (p.is_relative_to(root / 'knowledge/local/feedback') and
                           evidence_payload(p, root / 'knowledge/local/feedback'))
                  and not (p.is_relative_to(root / "knowledge/local/feedback/knowledge-use") and non_use_only(read_json(p))))


def fingerprint(root, path):
    return {"path": path.relative_to(root).as_posix(), "sha256": file_hash(path)}


def baseline(root=None):
    root = Path(root or ROOT)
    path = root / STATE / "checkpoint.json"
    require(not path.exists(), "Baseline already exists; preserve previous incremental history")
    records = [dict(fingerprint(root, p), disposition="historical_baseline") for p in source_files(root)]
    write_json(path, {"schema_version": 1, "initialized_at": utc_now(), "seen_record_versions": records,
                     "pending": [], "artifacts": [], "last_successful_run_at": None})
    return {"state": "baseline_created", "records": len(records)}


def checkpoint(root):
    path = root / STATE / "checkpoint.json"
    require(path.is_file(), "Curation checkpoint missing: explicitly run hooks baseline for a new installation")
    state = read_json(path)
    require(state.get("schema_version") == 1 and isinstance(state.get("seen_record_versions"), list),
            "Invalid curation checkpoint; restore a verified previous version")
    for record in state["seen_record_versions"]:
        require(isinstance(record, dict) and isinstance(record.get("path"), str)
                and re.fullmatch(r"[0-9a-f]{64}", record.get("sha256", "")), "Invalid curation history")
    return state


def inventory(root, state):
    seen = {(p["path"], p["sha256"]) for p in state["seen_record_versions"]}
    return [record for p in source_files(root) if (record := fingerprint(root, p))
            and (record["path"], record["sha256"]) not in seen]


def protected(root):
    files = [root / "knowledge/index.json", root / "AGENTS.md", root / "knowledge/curation/candidate-archives.json"]
    for name in ("knowledge/rules", "knowledge/cases", "knowledge/examples", "knowledge/history",
                 "knowledge/curation/reviews", "knowledge/local/curation/reviews", "agent", "docs", "config", ".agents/skills"):
        directory = inside(root, name)
        if directory.is_dir():
            files.extend(p for p in directory.rglob("*") if p.is_file())
    return {p.relative_to(root).as_posix(): file_hash(p) for p in files if p.is_file()}


def catalogs(root, state=None):
    records = {}
    # One atomic checkpoint commits both source progress and current lesson heads.
    # Public indices are only a rebuildable view, never transaction authority.
    state = state if state is not None else checkpoint(root)
    for entry in state.get("lessons", []):
        require(entry["path"].startswith(("knowledge/distillations/", STATE + "/private-candidates/")), "Invalid lesson location")
        target = inside(root, entry["path"])
        require(file_hash(target) == entry["sha256"], "Distillation artifact changed")
        record = read_json(target)
        require(record["status"] == "candidate", "Curation catalog contains an activated rule")
        records[record["lesson_id"]] = record
    return records


def due(config, state, now):
    current = now.astimezone(SHANGHAI)
    hour, minute = map(int, config["time"].split(":"))
    deadline = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if current < deadline:
        deadline -= timedelta(days=1)
        # Before today's trigger, catch up the last missed window only when the
        # checkpoint existed then. A new workspace must not inherit old debt.
        if not state.get("last_successful_run_at"):
            initialized = state.get("initialized_at")
            return bool(initialized and datetime.fromisoformat(initialized).astimezone(SHANGHAI) <= deadline)
    last = state.get("last_successful_run_at")
    return not last or datetime.fromisoformat(last).astimezone(SHANGHAI) < deadline


def status(root=None, now=None):
    from .knowledge_review import queue
    root = Path(root or ROOT)
    config, state = settings(root), checkpoint(root)
    review_queue = queue(root)
    return {"owner": "project", "enabled": config["enabled"], "time": config["time"],
            "timezone": config["timezone"], "engine": config["engine"],
            "engine_available": bool(curation_engine.executable(root)) if config["engine"] == "codex_cli" else True,
            "new_records": len(inventory(root, state)), "pending": state.get("pending", []),
            "adoption_queue_open": len(review_queue),
            "review_required": bool(review_queue),
            "review_next_action": "knowledge-queue; review evidence and adopt or record a concrete gap" if review_queue else None,
            "due": due(config, state, now or datetime.now(timezone.utc)),
            "last_successful_run_at": state.get("last_successful_run_at"),
            "lock_present": (root / STATE / "lock.json").exists(), "paid_media_model_credits": 0}


def related_lessons(events, records):
    return [{key: record[key] for key in ("lesson_id", "scope", "visibility", "method", "conflict_with_rules")}
            | {"revision": object_hash(record)} for record in records.values()
            if any(record["scope"] == event["scope"] and record["visibility"] == event["visibility"] for event in events)]


def packet(root, state, config, *, oversized=None):
    events = []
    pending = {(e["path"], e["sha256"]) for e in state.get("pending", [])}
    fresh = [e for e in inventory(root, state) if (e["path"], e["sha256"]) not in pending]
    # Real repairs/counterexamples must not wait behind hundreds of generated
    # placeholder/inbox records. This changes scheduling, never scope or status.
    from .knowledge_records import placeholder_lesson
    def priority(record):
        path = inside(root, record['path'])
        data = read_json(path) if path.suffix == '.json' else {}
        if record['path'].startswith('knowledge/local/feedback/improvements/'):
            return (0, record['path'])
        if data.get('outcome') in ('counterexample', 'ineffective', 'regressed'):
            return (0, record['path'])
        if data.get('hypothesis') and not placeholder_lesson(data['hypothesis']):
            return (1, record['path'])
        return (2, record['path'])
    fresh.sort(key=priority)
    for record in fresh[:config["max_records"]]:
        path = inside(root, record["path"])
        data = read_json(path) if path.suffix == ".json" else {"observation": path.read_text(encoding="utf-8-sig")}
        require(isinstance(data, dict), "Curation event must be an object")
        # Inbox is a durable trigger; its corresponding candidate carries the observation.
        related = []
        if record["path"].startswith("knowledge/local/inbox/") and not data.get("scope"):
            candidate = root / "knowledge/local/candidates" / path.name
            if candidate.is_file():
                data = {**read_json(candidate), "inbox_event": data}
                related.append(fingerprint(root, candidate))
        events.append({**record, "event_id": object_hash(record), "scope": data.get("scope", {}),
                       "visibility": "private" if Path(record["path"]).as_posix().startswith("knowledge/local/") else "project", "record": data,
                       "related_records": related})
    existing = catalogs(root, state)
    rules = []
    for entry in read_json(root / "knowledge/index.json").get("entries", []):
        if entry.get("status") == "active" and not entry.get("superseded_by"):
            rules.append({"id": entry["id"], "scope": entry.get("scope", {}),
                          "method": inside(root / "knowledge", str(Path(entry["path"]).relative_to("knowledge"))).read_text(encoding="utf-8-sig")})
    result = {"schema_version": 1, "events": events, "existing": related_lessons(events, existing), "active_rules": rules,
              "analysis_contract": "Quote each source via record JSON pointer; separate unproven cause from action. "
              "Same-source repairs are one source. no_new_knowledge needs a source-specific reason; gaps stay pending."}
    def batch(items):
        return {**result, "events": items, "existing": related_lessons(items, existing)}

    def fits(items):
        return len(json.dumps(batch(items), ensure_ascii=False).encode()) <= config["max_packet_bytes"]

    require(fits([]), "Active curation rules alone exceed packet size limit")
    selected = []
    for event in events:
        if fits([*selected, event]):
            selected.append(event)
        elif oversized is not None and not fits([event]):
            identity = {key: val for key, val in event.items() if key != "record"}
            oversized.append({**identity, "reason": "Complete evidence plus context exceeds packet limit. "
                              "Review the original by path and hash or supply a smaller scoped observation."})
    result = batch(selected)
    return result


def source_identities(sources):
    identities = {e["scope"].get("source_sha256") if e["scope"].get("source_sha256") not in (None, "", "*")
                  else e["record"].get("source_sha256") for e in sources}
    return {x for x in identities if isinstance(x, str) and re.fullmatch(r"[0-9a-f]{64}", x)}


def validate_analysis(group, sources):
    """Verify provenance, not the truth or causality of the quoted business data."""
    if "analysis" not in group:
        return  # Cached legacy replies remain readable without reprocessing sources.
    analysis = group["analysis"]
    require(isinstance(analysis, dict) and set(analysis) == {
        "observations", "causal_hypothesis", "action_basis"}, "Invalid curation analysis")
    require(isinstance(analysis["causal_hypothesis"], str)
            and len(analysis["causal_hypothesis"]) <= 8000, "Invalid causal hypothesis")
    require(analysis["action_basis"] in {"proposed", "observed_comparison", "independent_sources"},
            "Invalid action basis")
    observations = analysis["observations"]
    require(isinstance(observations, list) and observations, "Observation evidence required")
    events = {e["event_id"]: e for e in sources}
    cited = set()
    for ref in observations:
        require(isinstance(ref, dict) and set(ref) == {"event_id", "pointer", "quote"}
                and isinstance(ref["event_id"], str) and ref["event_id"] in events,
                "Unknown observation source")
        require(isinstance(ref["pointer"], str) and ref["pointer"].startswith("/")
                and isinstance(ref["quote"], str) and ref["quote"].strip(), "Invalid observation reference")
        text = events[ref["event_id"]]["record"]
        try:
            for token in ref["pointer"][1:].split("/"):
                key = token.replace("~1", "/").replace("~0", "~")
                text = text[int(key)] if isinstance(text, list) else text[key]
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise WorkflowError("Observation pointer does not resolve") from exc
        require(isinstance(text, str) and ref["quote"] in text, "Observation quote differs from source")
        cited.add(ref["event_id"])
    require(cited == set(events), "Each grouped source needs observation evidence")
    require(analysis["action_basis"] != "independent_sources" or len(source_identities(sources)) >= 2,
            "Same-source repairs are not independent validation")


def validate(response, value):
    require(isinstance(response, dict) and {"groups", "pending"}.issubset(response)
            and set(response).issubset({"groups", "pending", "no_new_knowledge"}), "Invalid curation response")
    require(isinstance(response["groups"], list) and isinstance(response["pending"], list), "Invalid curation response lists")
    events = {e["event_id"]: e for e in value["events"]}
    existing = {e["lesson_id"]: e for e in value["existing"]}
    used, targets = [], set()
    for group in response["groups"]:
        require(isinstance(group, dict) and set(curation_engine.GROUP_FIELDS).issubset(group)
                and set(group).issubset(set(curation_engine.GROUP_FIELDS) | {"adoption", "analysis"}), "Invalid curation group fields")
        if "adoption" in group:
            proposal = group["adoption"]
            require(set(proposal) == {"action", "target_ids", "reason", "missing_evidence"}
                    and proposal["action"] in {"merge_existing", "new_method", "source_case", "pending"}
                    and isinstance(proposal["reason"], str) and proposal["reason"].strip()
                    and isinstance(proposal["missing_evidence"], list)
                    and all(isinstance(x, str) for x in proposal["missing_evidence"]), "Invalid adoption proposal")
            known = {r["id"] for r in value.get("active_rules", [])}
            require(isinstance(proposal["target_ids"], list) and all(x in known for x in proposal["target_ids"]), "Unknown adoption proposal target")
            require(proposal["action"] != "merge_existing" or proposal["target_ids"], "Merge proposal needs an active method")
        require(isinstance(group["event_ids"], list) and group["event_ids"], "Empty curation group")
        merging = len(group["event_ids"]) > 1 or bool(group["merge_into"])
        require(isinstance(group["same_meaning"], bool) and (not merging or group["same_meaning"])
                and isinstance(group["conflict_with_rules"], bool), "Merge judgment missing")
        require(all(isinstance(e, str) and e in events for e in group["event_ids"]), "Unknown curation source")
        sources = [events[e] for e in group["event_ids"]]
        require(sources[0]["scope"] and all(e["scope"] == sources[0]["scope"] and e["visibility"] == sources[0]["visibility"]
                for e in sources), "Cannot merge different or missing scopes/visibility")
        for field in ("title", "trigger", "action", "failure_signature", "next_counterexample_test", "merge_into"):
            require(isinstance(group[field], str) and len(group[field]) <= 8000, "Invalid curation text")
        require(bool(group["title"].strip()) and bool(group["action"].strip()), "Curation method missing")
        require(isinstance(group["limitations"], list) and all(isinstance(s, str) for s in group["limitations"]), "Invalid limitations")
        target = group["merge_into"]
        if target:
            require(target in existing and target not in targets, "Unknown or repeated merge target")
            require(existing[target]["scope"] == sources[0]["scope"]
                    and existing[target]["visibility"] == sources[0]["visibility"], "Merge target scope/visibility differs")
            targets.add(target)
        validate_analysis(group, sources)
        used.extend(group["event_ids"])
    require(isinstance(response.get("no_new_knowledge", []), list), "Invalid no-new-knowledge list")
    for item in response["pending"] + response.get("no_new_knowledge", []):
        require(isinstance(item, dict) and set(item) == {"event_id", "reason"}
                and item["event_id"] in events and isinstance(item["reason"], str) and item["reason"].strip(), "Invalid pending event")
        used.append(item["event_id"])
    require(len(used) == len(set(used)) and set(used) == set(events), "Each new event must be handled exactly once")


def persist(root, state, value, response, oversized=()):
    validate(response, value)
    for event in [*value["events"], *oversized]:
        require(file_hash(inside(root, event["path"])) == event["sha256"], "Source changed during curation; retry without advancing checkpoint")
        require(all(file_hash(inside(root, ref["path"])) == ref["sha256"] for ref in event.get("related_records", [])),
                "Related source changed during curation; prepare again")
    current_catalog = catalogs(root)
    require(value["existing"] == related_lessons(value["events"], current_catalog), "Curation catalog changed; prepare again")
    events = {e["event_id"]: e for e in value["events"]}
    existing = current_catalog
    artifacts, handled, writes = [], [], []
    heads = {e["lesson_id"]: e for e in state.get("lessons", [])}
    for group in response["groups"]:
        sources = [events[key] for key in group["event_ids"]]
        old = existing.get(group["merge_into"])
        lesson_id = old["lesson_id"] if old else "lesson-" + object_hash(sorted(group["event_ids"]))[:20]
        origins = {e["event_id"]: e for e in (old or {}).get("sources", [])}
        origins.update({e["event_id"]: e for e in sources})
        record = {"schema_version": 1, "lesson_id": lesson_id, "status": "candidate",
                  "scope": sources[0]["scope"], "visibility": sources[0]["visibility"],
                  "method": {key: copy.deepcopy(group[key]) for key in ("title", "trigger", "action", "failure_signature", "limitations", "next_counterexample_test")},
                  "sources": list(origins.values()), "conflict_with_rules": group["conflict_with_rules"] or bool((old or {}).get("conflict_with_rules")),
                  "company_preference": False, "activation": "Developer review required; no validated rules changed",
                  "evidence_boundary": "Embedded observations and source hashes only; no new video-quality acceptance or independent validation"}
        record["analysis"] = copy.deepcopy(group.get("analysis"))
        record["analysis_status"] = "source_linked" if group.get("analysis") else "legacy_unassessed"
        record["method"]["limitations"].append(
            "Quoted observations do not prove causality or validate the proposed action; controller review required."
            if group.get("analysis") else
            "Legacy response: observation, causal hypothesis and action evidence have not been separately assessed.")
        if group.get("adoption"):
            proposal = copy.deepcopy(group["adoption"])
            if (group.get("analysis") and sources[0]["scope"].get("source_sha256") in (None, "", "*")
                    and len(source_identities(sources)) == 1
                    and proposal["action"] in {"new_method", "merge_existing"}):
                gap = "Only one known video source; review source-limited evidence before any broader method adoption."
                proposal["reason"] = gap + " Original suggestion: " + proposal["action"] + ": " + proposal["reason"]
                proposal["action"] = "pending"
                proposal["missing_evidence"] = list(dict.fromkeys(proposal["missing_evidence"] + [gap]))
                record["method"]["limitations"].append(gap)
            record["adoption_proposal"] = proposal
            record["next_action"] = "knowledge-review: " + proposal["action"] + ": " + proposal["reason"]
        if old:
            record["previous_method"] = old["method"]
            record["previous_revision_sha256"] = object_hash(old)
        if old:
            record["method"]["limitations"] = list(dict.fromkeys(old["method"]["limitations"] + record["method"]["limitations"]))
        folder = "knowledge/distillations" if record["visibility"] == "project" else STATE + "/private-candidates"
        revision = object_hash(record)
        relative = f"{lesson_id}/{revision}.json"
        path = inside(inside(root, folder), relative)
        if path.exists():
            require(read_json(path) == record, "Distillation revision collision")
        writes.append((path, record))
        content = json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        artifact = {"path": path.relative_to(root).as_posix(), "sha256": digest}
        artifacts.append(artifact)
        heads[lesson_id] = {**artifact, "lesson_id": lesson_id, "visibility": record["visibility"]}
        handled.extend({"path": e["path"], "sha256": e["sha256"], "disposition": "candidate_curated"} for e in sources)
    handled.extend({"path": events[item["event_id"]]["path"],
                    "sha256": events[item["event_id"]]["sha256"],
                    "disposition": "no_new_knowledge", "reason": item["reason"]}
                   for item in response.get("no_new_knowledge", []))
    updated = copy.deepcopy(state)
    updated["seen_record_versions"].extend(handled)
    current_paths = {e["path"] for e in [*value["events"], *oversized]}
    from .knowledge_review import closed_sources
    closed = closed_sources(root)
    updated["pending"] = [e for e in state.get("pending", []) if e["path"] not in current_paths
                          and (e["path"], e["sha256"]) not in closed]
    updated["pending"].extend({**events[e["event_id"]], "reason": e["reason"]} for e in response["pending"])
    updated["pending"].extend(oversized)
    updated["lessons"] = list(heads.values())
    updated["artifacts"] = state.get("artifacts", []) + artifacts
    updated["last_successful_run_at"] = utc_now()
    return updated, artifacts, writes


def publish_catalogs(root, state):
    for folder in ("knowledge/distillations", STATE + "/private-candidates"):
        entries = [e for e in state.get("lessons", []) if e["path"].startswith(folder + "/")]
        if entries:
            write_json(root / folder / "index.json", {"schema_version": 1, "entries": entries,
                       "authority": "Derived candidate view; never the active knowledge index"})


def execute(root=None, due_only=False, prepare_only=False, response_file=None, engine=None, now=None):
    root = Path(root or ROOT)
    checkpoint_path = root / STATE / "checkpoint.json"
    previous = file_hash(checkpoint_path) if checkpoint_path.is_file() else None
    try:
        return _execute(root, due_only, prepare_only, response_file, engine, now)
    except (WorkflowError, ValueError, KeyError, TypeError, OSError) as exc:
        write_json(root / STATE / "reports" / ("failed-" + uuid.uuid4().hex + ".json"),
                   {"at": utc_now(), "state": "failed", "error_type": type(exc).__name__,
                    "error": str(exc), "checkpoint_advanced": (file_hash(checkpoint_path) if checkpoint_path.is_file() else None) != previous,
                    "paid_media_model_credits": 0})
        raise


def _execute(root, due_only, prepare_only, response_file, engine, now):
    root = Path(root or ROOT)
    config = settings(root)
    require(config["enabled"], "Project daily curation hook is disabled")
    with lock(root / STATE / "lock.json"):
        state = checkpoint(root)
        catalogs(root, state)
        publish_catalogs(root, state)
        if due_only and not due(config, state, now or datetime.now(timezone.utc)):
            return {"state": "not_due", "paid_media_model_credits": 0}
        frozen = protected(root)
        learning.audit(root)
        oversized = []
        value = packet(root, state, config, oversized=oversized)
        identifier = object_hash({"packet": value, "prompt_sha256": file_hash(inside(root, config["prompt"])), "engine": config["engine"]})
        if oversized:
            identifier = object_hash([identifier, oversized])
        job = root / STATE / "jobs" / identifier
        job.mkdir(parents=True, exist_ok=True)
        write_json(job / "packet.json", value)
        write_json(job / "schema.json", curation_engine.SCHEMA)
        response_path = job / "response.json"
        if not value["events"]:
            response = {"groups": [], "pending": []}
        elif response_file is not None:
            response = read_json(inside(root, response_file))
        elif response_path.exists():
            response = read_json(response_path)
        elif prepare_only or config["engine"] == "packet":
            return {"state": "awaiting_reasoning", "packet": str((job / "packet.json").relative_to(root)),
                    "schema": str((job / "schema.json").relative_to(root)), "paid_media_model_credits": 0}
        else:
            prompt = inside(root, config["prompt"]).read_text(encoding="utf-8-sig")
            response = (engine or curation_engine.codex_cli)(value, prompt, job, root, config["timeout_seconds"])
        validate(response, value)
        # Verify the reasoning step before allowing it to affect even candidate files.
        require(protected(root) == frozen, "Protected rules/config changed during curation; no checkpoint committed")
        write_json(response_path, response)
        updated, artifacts, writes = persist(root, state, value, response, oversized)
        for target, record in writes:
            if not target.exists():
                write_json(target, record)
        require(all(file_hash(inside(root, e["path"])) == e["sha256"] for e in artifacts), "Curation artifact integrity failure")
        audit = learning.audit(root)
        require(protected(root) == frozen, "Protected rules/config changed during curation; no checkpoint committed")
        path = root / STATE / "checkpoint.json"
        write_json(root / STATE / "checkpoint.previous.json", state)
        report = {"id": identifier, "at": utc_now(), "state": "pending" if updated["pending"] else "curated" if value["events"] else "idle",
                  "new_records": len(value["events"]), "oversized_deferred": len(oversized), "groups": len(response["groups"]),
                  "no_new_knowledge": len(response.get("no_new_knowledge", [])),
                  "merged": sum(bool(g["merge_into"]) or len(g["event_ids"]) > 1 for g in response["groups"]),
                  "pending": len(updated["pending"]), "conflicts": sum(g["conflict_with_rules"] for g in response["groups"]),
                  "artifacts": artifacts, "knowledge_audit": audit["decision"], "protected_files_unchanged": len(frozen),
                  "paid_media_model_calls": 0, "paid_media_model_credits": 0}
        report["remaining_new_records"] = len(inventory(root, updated)) - len(updated["pending"])
        write_json(path, updated)
        publish_catalogs(root, updated)
        from .knowledge_review import queue
        report["adoption_queue_open"] = len(queue(root))
        report["next_action"] = "knowledge-queue -> knowledge-review; publish reviewed revisions with knowledge-promote, then archive fully accounted originals"
        write_json(root / STATE / "reports" / (uuid.uuid4().hex + ".json"), report)
        return report
