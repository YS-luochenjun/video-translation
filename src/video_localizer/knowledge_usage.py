"""Actual-use feedback binds the selected revision, plan, video and durable evidence."""
from pathlib import Path

from . import bundles
from .common import ROOT, file_hash, guarded, inside, object_hash, read_json, require, write_json
from .knowledge_records import non_use_only

AREA = "knowledge/local/feedback/knowledge-use"


@guarded
def record(run, spec, root=None):
    root, run = Path(root or ROOT).resolve(), Path(run).resolve()
    plan = read_json(run / "plan.json")
    require(spec["plan_id"] == plan["id"], "Knowledge-use plan is stale")
    frozen = run / "plans" / plan["id"] / "plan.json"
    require(frozen.is_file() and read_json(frozen) == plan, "Knowledge-use requires the unchanged frozen plan")
    candidate = read_json(run / "outputs/candidate.json")
    require(candidate.get("plan_id") == plan["id"] and candidate.get("inventory_sha256") == plan["inventory_sha256"], "Knowledge-use candidate belongs to another plan or inventory")
    require(candidate["sha256"] == spec["video_sha256"]
            and file_hash(inside(run, candidate["path"])) == candidate["sha256"], "Knowledge-use video is stale")
    for name, key in (("analysis/inventory.json", "inventory_sha256"), ("inputs/request.json", "request_sha256")):
        require(file_hash(run / name) == plan[key], "Knowledge-use inputs changed; rebuild the plan")
    source = read_json(run / "run.json")
    require(file_hash(inside(run, source["source"])) == plan["source_sha256"], "Knowledge-use source changed")
    require(spec.get("reviewed_by") and spec.get("review_type") in {"same_agent", "independent", "user_feedback"}, "Attribute the actual feedback review")
    selected = plan.get("knowledge", []) + plan.get("source_references", []) + plan.get("knowledge_advisories", [])
    require(isinstance(spec.get("uses"), list) and spec["uses"], "Describe which selected knowledge was used or not used")
    uses, seen = [], set()
    for use in spec["uses"]:
        key = (use["path"], use["sha256"])
        match = next((entry for entry in selected if (entry["path"], entry["sha256"]) == key), None)
        require(match is not None and key not in seen, "Feedback must bind a unique selected knowledge revision")
        seen.add(key)
        require(use["outcome"] in {"helpful", "ineffective", "counterexample", "not_used"}
                and use.get("observation"), "Feedback needs an observed outcome and explanation")
        uses.append({**use, "selected_snapshot": match})
    evidence = spec.get("evidence", [])
    require(evidence or all(u["outcome"] == "not_used" for u in uses), "Actual-use feedback needs evidence")
    files = {"plan.json": frozen}
    for item in evidence:
        path = inside(run, item["path"])
        require(file_hash(path) == item["sha256"] and path.suffix in {".json", ".md", ".png", ".jpg", ".wav", ".webp"}, "Feedback evidence changed or unsupported")
        files["evidence/" + item["path"]] = path
    identity = object_hash({"run": run.name, "spec": spec})
    folder = root / AREA / identity
    scope = {"workflow": "video-localization", "source_sha256": plan["source_sha256"],
             "target_language": read_json(run / "inputs/request.json")["target_language"]}
    bundles.create(folder / "bundle", "knowledge-case", identity, files,
                   {"scope": scope, "video_sha256": candidate["sha256"], "review_type": spec["review_type"]})
    negative = any(u["outcome"] in {"ineffective", "counterexample"} for u in uses)
    value = {"schema_version": 1, "id": identity, "status": "candidate", "scope": scope,
             "plan_id": plan["id"], "video_sha256": candidate["sha256"], "uses": uses,
             "outcome": "counterexample" if negative else "observation",
             "hypothesis": " | ".join(dict.fromkeys(u["observation"] for u in uses)),
             "reviewed_by": spec["reviewed_by"], "review_type": spec["review_type"],
             "case": (folder / "bundle").relative_to(root).as_posix(),
             "case_manifest_sha256": file_hash(folder / "bundle/manifest.json"),
             "limitations": ["Use report only; no automatic rule promotion, quality acceptance or cross-source proof."],
             "next_action": "Review counterexample and revise/supersede the affected method" if negative else "Review whether the method needs clarification or no change"}
    target = folder / "feedback.json"
    if target.exists():
        previous = read_json(target)
        # Old receipts repeat identical observations for every selected rule.
        # Preserve their exact text on retry; accept only the known old format.
        legacy = " | ".join(u["observation"] for u in uses)
        if previous.get('hypothesis') == legacy:
            value['hypothesis'] = legacy
        require(previous == value, "Immutable knowledge feedback changed")
    else:
        write_json(target, value)
    pointer = {"path": target.relative_to(root).as_posix(), "sha256": file_hash(target)}
    write_json(run / "review/knowledge-use" / (identity + ".json"), pointer)
    return {**pointer, "state": "recorded_non_use" if non_use_only(value) else "awaiting_knowledge_review", "automatic_promotion": False}


def followup(run, root=None):
    root = Path(root or ROOT).resolve()
    plan_path = Path(run) / "plan.json"
    if not plan_path.exists():
        return {"state": "no_plan", "remaining": []}
    plan = read_json(plan_path)
    selected = plan.get("knowledge", []) + plan.get("source_references", []) + plan.get("knowledge_advisories", [])
    candidate_path = Path(run) / "outputs/candidate.json"
    video = read_json(candidate_path).get("sha256") if candidate_path.exists() else None
    accounted = set()
    for pointer in (Path(run) / "review/knowledge-use").glob("*.json"):
        ref = read_json(pointer)
        path = inside(root, ref["path"])
        require(file_hash(path) == ref["sha256"], "Knowledge feedback changed")
        value = read_json(path)
        if value["plan_id"] == plan["id"] and value["video_sha256"] == video:
            accounted.update((u["path"], u["sha256"]) for u in value["uses"])
    remaining = [{"path": e["path"], "sha256": e["sha256"]} for e in selected
                 if (e["path"], e["sha256"]) not in accounted]
    return {"state": "needs_use_feedback" if remaining else "recorded", "remaining": remaining,
            "next_command": "knowledge-use RUN SPEC", "scope": "Selection is not use. Report not_used explicitly; feedback does not block or grant video acceptance."}


def alerts(context, root=None):
    from .knowledge_review import decisions
    root = Path(root or ROOT).resolve()
    heads, result = decisions(root), {}
    for path in (root / AREA).glob("*/feedback.json"):
        value = read_json(path)
        relative = path.relative_to(root).as_posix()
        decision = heads.get((relative, file_hash(path)))
        if decision and decision["closed"]:
            continue
        if any(v not in ("*", context.get(k)) for k, v in value["scope"].items()):
            continue
        bundle = root / value["case"]
        require(file_hash(bundle / "manifest.json") == value["case_manifest_sha256"], "Feedback evidence manifest changed")
        bundles.verify(bundle)
        for use in value["uses"]:
            if use["outcome"] in {"counterexample", "ineffective"}:
                result.setdefault((use["path"], use["sha256"]), []).append({"path": relative,
                    "sha256": file_hash(path), "observation": use["observation"], "authority": "unresolved_feedback_not_a_rule"})
    return result
