"""Bounded, scoped recall of observations, kept separate from authoritative methods."""
from .common import ROOT, object_hash, require
from .knowledge_review import queue


def retrieve(context, root=None, limit=3):
    require(type(limit) is int and 0 <= limit <= 5, "Advisory limit must be between zero and five")
    ranked = []
    for row in queue(root or ROOT):
        record, decision, scope = row["record"], row["decision"] or {}, row["scope"]
        if not isinstance(scope, dict) or not scope or scope.get("workflow", "video-localization") != context.get("workflow"):
            continue
        # Identity/profile/locale restrictions are never relaxed for recall.
        if any(value not in ("*", context.get(key)) for key, value in scope.items()
               if key not in {"stage", "workflow"}):
            continue
        features = set(decision.get("retrieval_features", record.get("requires_features", [])))
        if not features.issubset(set(context.get("features", []))):
            continue
        exact_source = scope.get("source_sha256") == context.get("source_sha256") and bool(scope.get("source_sha256"))
        if not exact_source and not features:
            continue
        # Synthetic and non-advertisement records need explicit review; no name-based promotion.
        method = record.get("method", {})
        reviewed = decision.get("advisory", {})
        summary = reviewed.get("summary") or method.get("action") or record.get("hypothesis") or record.get("action")
        if not isinstance(summary, str) or not summary.strip() or '\ufffd' in summary:
            continue
        limits = reviewed.get("limitations", method.get("limitations", record.get("limitations", record.get("limits", []))))
        item = {"path": row["path"], "storage_path": row["storage_path"], "sha256": row["sha256"],
                "scope": scope, "validation_status": "unverified_observation", "authority": "advisory_only",
                "historical_outcome": record.get("outcome"), "summary": summary[:900],
                "limitations": [str(value)[:240] for value in limits[:3]],
                "next_check": str(reviewed.get("next_check") or method.get("next_counterexample_test") or row["next_action"])[:400],
                "review_sha256": row["previous_review"],
                "instructions": "Read the hash-bound original before trying it. Historical stage/scope still apply. May suggest risks or tests; cannot override active rules, approve quality, or authorize models/spend."}
        priority = (4 if exact_source else 0) + (3 if "/distillations/" in row["path"] else 0)
        if record.get("outcome") in {"counterexample", "ineffective", "fail", "revise"}:
            priority += 2
        sources = record.get("sources") or [{"path": row["path"], "sha256": row["sha256"], "record": record}]
        origins = []
        for source in sources:
            aliases = {(source["path"], source["sha256"])}
            original = source.get("record", {})
            if original.get("hypothesis"):
                aliases.add(("observation", object_hash({"scope": original.get("scope"), "hypothesis": original["hypothesis"]})))
            origins.append(aliases)
        ranked.append((priority, item, origins))
    selected, seen, covered = [], set(), set()
    for _, item, origins in sorted(ranked, key=lambda value: (-value[0], value[1]["path"])):
        key = object_hash({"scope": item["scope"], "summary": item["summary"]})
        if key not in seen and not all(aliases & covered for aliases in origins) and len(selected) < limit:
            selected.append(item)
            seen.add(key)
            covered.add((item["path"], item["sha256"]))
            for aliases in origins:
                covered.update(aliases)
    return selected
