"""Attributed review decisions and a finite queue; never activate rules implicitly."""
from pathlib import Path
import shutil
import hashlib
import re

from .common import ROOT, file_hash, inside, lock, object_hash, read_json, require, utc_now, write_json
from .knowledge_records import ARCHIVE_INDEX, archives, candidate_files, non_use_only, resolve, placeholder_lesson, evidence_payload

PUBLIC = "knowledge/curation/reviews"
PRIVATE = "knowledge/local/curation/reviews"
SOURCE_AREAS = ("knowledge/candidates/", "knowledge/distillations/", "knowledge/local/candidates/",
                "knowledge/local/feedback/", "knowledge/local/curation/private-candidates/")


def decisions(root):
    heads, records = {}, {}
    for area in (PUBLIC, PRIVATE):
        for path in sorted((Path(root) / area).glob("*.json")):
            record = read_json(path)
            require(path.stem == object_hash(record), "Knowledge review record changed")
            digest = file_hash(path)
            records[digest] = {**record, "decision_path": path.relative_to(root).as_posix(), "decision_sha256": digest}
    replaced = {r.get("previous_review") for r in records.values()} - {None}
    require(replaced.issubset(records), "Review predecessor missing")
    for digest, record in records.items():
        source = record["source"]
        resolve(root, source["path"], source["sha256"])
        previous = record.get("previous_review")
        if previous:
            require(records[previous]["source"] == source, "Review predecessor belongs to another source")
        seen, cursor = set(), digest
        while cursor:
            require(cursor not in seen, "Cyclic knowledge review history")
            seen.add(cursor)
            cursor = records[cursor].get("previous_review")
        for target in record["targets"]:
            require(hashlib.sha256(target["snapshot"].encode("utf-8")).hexdigest() == target["sha256"], "Reviewed target snapshot changed")
        if digest not in replaced:
            key = (source["path"], source["sha256"])
            require(key not in heads, "Competing knowledge reviews; resolve the branch explicitly")
            heads[key] = record
    for relative, entry in archives(root).items():
        decision = records.get(entry["decision_sha256"])
        require(decision and decision["closed"] and decision["source"] == {"path": relative, "sha256": entry["sha256"]}, "Archive lacks its closed review")
        path = inside(Path(root) / "knowledge/history/candidates", entry["archive_path"])
        require(file_hash(path) == entry["sha256"], "Archived original changed")
    return heads


def sources(root):
    root = Path(root).resolve()
    found = dict(candidate_files(root))
    # Only current distillation heads, never every historical revision.
    for area in ("knowledge/distillations", "knowledge/local/curation/private-candidates"):
        index = root / area / "index.json"
        if index.exists():
            for entry in read_json(index).get("entries", []):
                found[entry["path"]] = resolve(root, entry["path"], entry["sha256"])
    for area in ("knowledge/local/candidates", "knowledge/local/feedback"):
        for path in (root / area).rglob("*.json"):
            if path.name.startswith("index") or any(part in {"evidence", "bundle"} for part in path.relative_to(root / area).parts):
                continue
            if area == 'knowledge/local/feedback' and evidence_payload(path, root / area):
                continue
            if path.is_relative_to(root / "knowledge/local/feedback/knowledge-use") and non_use_only(read_json(path)):
                continue
            found[path.relative_to(root).as_posix()] = path
    return found


def closed_sources(root):
    """Include only inbox pointers whose exact linked candidate was reviewed closed."""
    root = Path(root)
    heads = decisions(root)
    closed = {key for key, record in heads.items() if record["closed"]}
    entries = []
    for name in ('knowledge/index.json', 'knowledge/cases/index.json', 'config/knowledge.local.json'):
        if (root / name).exists():
            entries.extend(read_json(root / name).get('entries', []))
    for path in (root / "knowledge/local/inbox").glob("*.json"):
        pointer = read_json(path)
        candidate = root / "knowledge/local/candidates" / path.name
        if candidate.exists() and (candidate.relative_to(root).as_posix(), file_hash(candidate)) in closed:
            original = read_json(candidate)
            if pointer.get("id") == original.get("id") and pointer.get("case") == original.get("case"):
                closed.add((path.relative_to(root).as_posix(), file_hash(path)))
                continue
        # Some inbox pointers reference public originals that have already been
        # archived. Resolve their exact hash and evidence/target, not just an ID.
        if not re.fullmatch(r'[A-Za-z0-9_-]+', pointer.get('id', '')):
            continue
        relative = pointer.get('candidate') or f'knowledge/candidates/{pointer["id"]}.json'
        matches = [(key, record) for key, record in heads.items()
                   if key[0] == relative and record['closed']]
        if len(matches) != 1:
            continue
        (relative, digest), review = matches[0]
        original = read_json(resolve(root, relative, digest))
        exact_pointer = pointer.get('candidate') == relative and pointer.get('candidate_sha256') == digest
        target_ids = {t['id'] for t in review.get('targets', [])}
        cases = {original.get('case')} | {e.get('case') for e in entries if e['id'] in target_ids}
        case_matches = bool(pointer.get('case') and pointer['case'] in cases)
        # Sanitized public originals can identify a private case by its manifest
        # hash instead of retaining the private path. Verify that exact evidence
        # and its semantic identity before closing the old inbox pointer.
        evidence = original.get('evidence', {})
        if not case_matches and pointer.get('case') and evidence.get('case_manifest_sha256'):
            from . import bundles
            folder = inside(root, pointer['case'])
            manifest = folder / 'manifest.json'
            if manifest.is_file() and file_hash(manifest) == evidence['case_manifest_sha256']:
                preserved = bundles.verify(folder)
                metadata = preserved.get('metadata', {})
                case_matches = (preserved.get('kind') == 'knowledge-case'
                                and metadata.get('scope') == original.get('scope')
                                and metadata.get('video_sha256') == evidence.get('video_sha256')
                                and metadata.get('lesson') == original.get('hypothesis'))
        if pointer.get('id') == original.get('id') and (exact_pointer or case_matches):
            closed.add((path.relative_to(root).as_posix(), file_hash(path)))
    return closed


def queue(root=None, include_closed=False):
    root = Path(root or ROOT).resolve()
    heads = decisions(root)
    candidate_index = root / "knowledge/candidates/index.json"
    prior_adoptions = {e["path"]: e.get("reviews", []) for e in read_json(candidate_index).get("entries", [])} if candidate_index.exists() else {}
    rows = []
    for relative, path in sorted(sources(root).items()):
        digest = file_hash(path)
        value = read_json(path) if path.suffix == ".json" else {"hypothesis": path.read_text(encoding="utf-8-sig")}
        decision = heads.get((relative, digest))
        if decision and decision["closed"] and not include_closed:
            continue
        rows.append({"path": relative, "storage_path": path.relative_to(root).as_posix(), "sha256": digest,
                     "scope": value.get("scope", {}), "status": "reviewed_closed" if decision and decision["closed"] else "needs_review",
                     "previous_review": decision["decision_sha256"] if decision else None,
                     "prior_adoptions": prior_adoptions.get(relative, []),
                     "adoption_proposal": value.get("adoption_proposal"),
                     "reflection_state": ('needs_lesson' if 'hypothesis' in value and placeholder_lesson(value['hypothesis'])
                                          else value.get('reflection_state', 'needs_review')),
                     "next_action": decision["next_action"] if decision else value.get("next_action", "Review the recorded adopted parts and remaining limitations; identify a target or concrete missing evidence instead of creating an identical candidate."),
                     "decision": decision, "record": value})
    return rows


def review(spec, root=None):
    from .learning import verify_entry
    root = Path(root or ROOT).resolve()
    source = spec["source"]
    require(isinstance(source, dict) and set(source) == {"path", "sha256"}, "Review source needs exactly path and sha256")
    require(source["path"].startswith(SOURCE_AREAS), "Review source must be a candidate, distillation or feedback")
    require(inside(root, source["path"]) == root / source["path"], "Review source must use its canonical path")
    original = resolve(root, source["path"], source["sha256"])
    require(spec.get("review_type") in {"developer_review", "explicit_user_feedback"}
            and spec.get("reviewed_by") and spec.get("origin"), "Review requires attribution and origin")
    resolution = spec["resolution"]
    require(resolution in {"adopted", "partial", "pending", "rejected", "synthetic_only", "duplicate"}, "Unknown review resolution")
    require(spec.get("reason") and isinstance(spec.get("adopted_parts"), list)
            and isinstance(spec.get("retained_parts"), list), "Account for adopted and retained contents")
    closed = resolution != "partial" and resolution != "pending" and spec.get("all_material_accounted") is True
    require(not closed or spec.get("remaining_disposition") == "historical_only", "Closed review must account for all remaining material")
    require(closed or bool(spec.get("next_action")), "Open review needs a concrete next action")
    private = "/local/" in source["path"]
    targets = []
    entries = []
    for name in ("knowledge/index.json", "knowledge/cases/index.json", "config/knowledge.local.json"):
        if (root / name).exists():
            entries.extend(read_json(root / name).get("entries", []))
    for target in spec.get("targets", []):
        entry = next((e for e in entries if e["id"] == target["id"]), None)
        require(entry and entry["status"] == "active" and not entry.get("superseded_by"), "Adoption target must be active; publish a reviewed revision first")
        require(private or not str(entry["path"]).startswith("knowledge/local/"), "Public review cannot disclose a private adoption target")
        verify_entry(entry, root)
        path = inside(root, entry["path"])
        require(file_hash(path) == target["sha256"], "Adoption target changed")
        targets.append({"id": entry["id"], "path": entry["path"], "sha256": file_hash(path),
                        "scope": entry.get("scope", {}), "snapshot": path.read_bytes().decode("utf-8")})
    require(resolution not in {"adopted", "partial", "duplicate"} or (targets and spec["adopted_parts"]), "Adoption needs verified targets and the specific adopted parts")
    features = spec.get("retrieval_features", [])
    from .knowledge import validate_feature_requirements
    validate_feature_requirements({"requires_features": features})
    if spec.get("advisory"):
        require(isinstance(spec["advisory"].get("summary"), str) and 0 < len(spec["advisory"]["summary"]) <= 1800
                and isinstance(spec["advisory"].get("limitations"), list)
                and all(isinstance(x, str) for x in spec["advisory"]["limitations"])
                and isinstance(spec["advisory"].get("next_check"), str), "Invalid reviewed advisory summary")
    with lock(root / "knowledge/local/curation/review.lock"):
        previous = decisions(root).get((source["path"], source["sha256"]))
        require(spec.get("previous_review") == (previous["decision_sha256"] if previous else None), "Review changed; refresh the queue")
        record = {**spec, "schema_version": 1, "closed": closed, "targets": targets,
                  "next_action": "historical_record_only" if closed else spec["next_action"],
                  "retrieval_features": features, "recorded_at": utc_now(),
                  "authority": "Review of specified contents only; no new video acceptance, automatic rule activation or broader source scope."}
        require(file_hash(original) == source["sha256"], "Source changed during review")
        area = PRIVATE if private else PUBLIC
        path = root / area / (object_hash(record) + ".json")
        write_json(path, record)
    return {"path": path.relative_to(root).as_posix(), "sha256": file_hash(path), "closed": closed}


def archive_preview(relative, root=None):
    root = Path(root or ROOT).resolve()
    require(relative.startswith("knowledge/candidates/"), "Only project candidate originals use this archive")
    original = resolve(root, relative)
    digest = file_hash(original)
    record = decisions(root).get((relative, digest))
    require(record and record["closed"], "Candidate still has unresolved contents; partial adoption cannot archive it")
    # Targets must still be the reviewed active revisions at the moment of removal.
    if record["targets"]:
        from .learning import verify_entry
        entries = [e for name in ("knowledge/index.json", "knowledge/cases/index.json") if (root / name).exists()
                   for e in read_json(root / name)["entries"]]
        for target in record["targets"]:
            entry = next((e for e in entries if e["id"] == target["id"]), None)
            require(entry and entry.get("status") == "active" and not entry.get("superseded_by"), "Adopted method changed; review before archive")
            verify_entry(entry, root)
            require(file_hash(root / entry["path"]) == target["sha256"], "Adopted method revision changed")
    value = {"source": relative, "sha256": digest, "decision_sha256": record["decision_sha256"],
             "archive_path": digest + "/" + Path(relative).name}
    return {**value, "fingerprint": object_hash(value)}


def archive(relative, expected, root=None):
    root = Path(root or ROOT).resolve()
    with lock(root / "knowledge/local/curation/review.lock"):
        preview = archive_preview(relative, root)
        require(expected == preview["fingerprint"], "Archive preview changed")
        original = resolve(root, relative, preview["sha256"])
        target = inside(root / "knowledge/history/candidates", preview["archive_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(original, target)
        require(file_hash(target) == preview["sha256"], "Archive copy differs")
        mapping = archives(root)
        mapping[relative] = {key: preview[key] for key in ("sha256", "archive_path", "decision_sha256")}
        write_json(root / ARCHIVE_INDEX, {"schema_version": 1, "entries": mapping})
        live = inside(root, relative)
        require(live == root / relative, "Refuse redirected candidate removal")
        if live.exists():
            require(file_hash(live) == preview["sha256"], "Candidate changed before removal")
            live.unlink()
    from .candidate_index import refresh
    refresh(root)
    return {"source": relative, "archived": target.relative_to(root).as_posix(), "sha256": preview["sha256"]}
