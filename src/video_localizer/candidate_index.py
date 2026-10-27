"""Derived navigation, never activation or a rewrite of historical candidates."""
from collections import Counter, defaultdict
from pathlib import Path

from .common import file_hash, object_hash, read_json, require, write_json
from .knowledge_records import candidate_files


def build(root):
    root = Path(root).resolve()
    from .knowledge_review import decisions
    current_reviews = decisions(root)
    reviews = defaultdict(list)
    for path in sorted((root / "knowledge/curation").glob("candidate-adoption*.json")):
        review = read_json(path)
        records = review.get("records", [])
        if review.get("candidate"):
            records = [{"path": review["candidate"], "sha256": review["candidate_sha256"]}]
        for record in records:
            group = review.get("groups", {}).get(record.get("group"), review)
            reviews[record["path"]].append({
                "path": path.relative_to(root).as_posix(), "sha256": file_hash(path),
                "candidate_sha256": record["sha256"], "group": record.get("group"),
                "disposition": group.get("disposition", review.get("status")),
                "adopted_in_historical": group.get("adopted_in", []),
            })
    entries, hypotheses = [], defaultdict(list)
    for relative, path in candidate_files(root):
        digest = file_hash(path)
        value = read_json(path) if path.suffix == ".json" else {}
        evidence = reviews.get(relative, [])
        for review in evidence:
            require(review["candidate_sha256"] == digest, f"Adoption map candidate hash differs: {relative}")
        dispositions = {item["disposition"] for item in evidence}
        if any(item["adopted_in_historical"] for item in evidence):
            review_status = "partial_adoption_recorded"
        elif dispositions == {"synthetic_only"}:
            review_status = "synthetic_only"
        elif dispositions == {"archive_only"}:
            review_status = "historical_retained"
        else:
            review_status = "reviewed_without_adoption" if evidence else "no_adoption_record"
        entry = {"id": value.get("id", path.stem), "path": relative, "original_sha256": digest,
                 "status": value.get("status", "unstructured_candidate"),
                 "scope": value.get("scope", {}), "historical_outcome": value.get("outcome"),
                 "review_status": review_status,
                 "reviews": evidence}
        current = current_reviews.get((relative, digest))
        if current:
            entry['current_review'] = {key: current[key] for key in
                                      ('decision_path', 'decision_sha256', 'resolution', 'closed', 'next_action')}
            entry['current_targets'] = [target['id'] for target in current['targets']]
        if path.relative_to(root).as_posix() != relative:
            entry["storage_path"] = path.relative_to(root).as_posix()
            entry["queue_state"] = "archived"
        hypothesis = value.get("hypothesis")
        if isinstance(hypothesis, str) and hypothesis:
            key = object_hash(hypothesis)
            entry["hypothesis_sha256"] = key
            hypotheses[key].append(relative)
        entries.append(entry)
    indexed = {item["path"] for item in entries}
    require(set(reviews).issubset(indexed), "Adoption map refers to a missing candidate")
    groups = [{"hypothesis_sha256": key, "members": paths}
              for key, paths in sorted(hypotheses.items()) if len(paths) > 1]
    return {"schema_version": 2,
            "semantics": "Derived navigation only. Partial adoption is not whole-record promotion; no_adoption_record does not prove no review. Exact-text groups do not merge scope, sources, outcomes or quality holds. Read the hash-bound original and adoption map for retained failures and limitations.",
            "counts": dict(Counter(item["review_status"] for item in entries)),
            "entries": entries, "exact_hypothesis_groups": groups}


def refresh(root):
    record = build(root)
    write_json(Path(root) / "knowledge/candidates/index.json", record)
    return record


def verify(root):
    path = Path(root) / "knowledge/candidates/index.json"
    require(path.exists() and read_json(path) == build(root), "Candidate index is stale; run bin/knowledge_maintenance.py reindex")
