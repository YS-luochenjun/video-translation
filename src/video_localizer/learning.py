"""Permanent learning cases: methods and bounded evidence, never production assets."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from . import bundles
from .evidence import EVIDENCE_SUFFIXES, check_references, verify_supplements
from .common import ROOT, file_hash, inside, object_hash, read_json, require, utc_now, write_json


def capture_case(case_id, lesson, scope, root=None, run=None, video_sha256=None, records=(), status="candidate", visibility="private", references=None):
    root = Path(root or ROOT)
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}", case_id), "Invalid learning case id")
    require(visibility in {"project", "private"}, "Invalid knowledge visibility")
    require(visibility != "project" or run is None, "Project cases use reviewed sanitized evidence; raw run capture stays private")
    directory = inside(root / ("knowledge/examples" if visibility == "project" else "knowledge/local/examples"), case_id)
    if (directory / "manifest.json").exists():
        manifest = bundles.verify(directory)
        require(manifest["metadata"]["scope"] == scope, "Learning case scope changed")
        require(manifest["metadata"].get("video_sha256") == video_sha256, "Learning case video changed")
        require(manifest["metadata"]["lesson"] == lesson, "Learning case lesson changed; create a revision")
        return directory
    sources = {}
    for record in records:
        record = Path(record)
        require(record.resolve().is_relative_to(root.resolve()), "Learning evidence escapes workspace")
        require(record.is_file(), f"Learning evidence missing: {record.name}")
        require(record.suffix.lower() in EVIDENCE_SUFFIXES,
                "A knowledge case stores records, observed images and audio evidence, not whole production videos")
        relative = "evidence/" + (record.name if visibility == "project" else record.relative_to(root).as_posix().replace("runs/", "source-records/", 1))
        require(relative not in sources or sources[relative] == record, "Evidence filenames collide")
        sources[relative] = record
    source_sha = scope.get("source_sha256")
    if run is not None:
        run = Path(run)
        source_record = read_json(run / "run.json")
        source = inside(run, source_record["source"])
        require(file_hash(source) == source_record["source_sha256"], "Source changed before learning")
        require(not source_sha or source_sha == source_record["source_sha256"], "Learning scope belongs to another source")
        source_sha = source_record["source_sha256"]
        if video_sha256:
            videos = [p for p in (run / "outputs").glob("*.mp4") if file_hash(p) == video_sha256]
            require(videos, "Learning result does not bind an existing actual video")
        for relative in ("run.json", "inputs/request.json", "analysis/inventory.json", "analysis/media.json"):
            path = run / relative
            if path.exists():
                sources["evidence/context/" + relative] = path
        for path in [run / "outputs/quality.json", *sorted((run / "outputs/quality-history").glob("*.json")),
                     *sorted((run / "review").glob("*.json"))]:
            if path.is_file() and video_sha256 and read_json(path).get("video_sha256") == video_sha256:
                sources["evidence/result/" + path.relative_to(run).as_posix()] = path
        observations = run / "review" / video_sha256[:12] if video_sha256 else None
        if observations and observations.exists():
            from .learning_evidence import select
            for path in select(run, video_sha256):
                sources["evidence/observations/" + path.relative_to(run).as_posix()] = path
        for path in (run / "inputs/references").glob("*"):
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".webp"}:
                sources["evidence/user-reference/" + path.name] = path
    require(sources, "Learning needs evidence or a sourced developer instruction")
    bundles.create(directory, "knowledge-case", case_id, sources, {
        "scope": scope, "status": status, "lesson": lesson, "source_sha256": source_sha,
        "video_sha256": video_sha256, "origin_run_id": Path(run).name if run else None,
        "evidence_semantics": "Embedded historical records are immutable observations. Their old path strings are origin labels, not live dependencies. Use only this manifest's files.",
        "proof_boundary": "Preserved text, feedback and actual observed image/audio evidence. Does not preserve every full-video frame or make unobserved claims pass.",
        "observation_selection": "Native representative frames, explicit failures, declared review evidence and caption/audio boundaries; full production audits stay in delivery/recovery assets.",
        "required_external_files": [], "visibility": visibility, "company_preference": False,
        **({"references": references} if references is not None else {})
    })
    return directory


def verify_entry(entry, root=None):
    from .knowledge import validate_feature_requirements
    validate_feature_requirements(entry)
    root = Path(root or ROOT)
    if entry.get('selection_review'):
        review = entry['selection_review']
        review_path = inside(root, review['path'])
        require(review_path.is_relative_to(root / 'knowledge'), 'Selection review must be permanent knowledge')
        require(file_hash(review_path) == review['sha256'], 'Knowledge selection review changed')
    path = inside(root, entry["path"])
    require(path.is_relative_to(root / "knowledge"), "Knowledge method must live in knowledge")
    text = path.read_text(encoding="utf-8-sig")
    require(not re.search(r"(?:^|[\s`(])(?:runs|outputs|work)/", text), "Active method depends on a runtime/output path")
    if entry.get("method_sha256"):
        require(file_hash(path) == entry["method_sha256"], "Knowledge method changed without review")
    from .knowledge_records import resolve
    for source in entry.get("candidate_sources", []):
        require(path.is_relative_to(root / "knowledge/local") or "/local/" not in source["path"], "Public method cannot depend on private candidate sources")
        resolve(root, source["path"], source["sha256"])
    case_path = entry.get("case")
    if case_path:
        case_path = inside(root, case_path)
        require(case_path.is_relative_to(root / "knowledge"), "Knowledge evidence must live in knowledge")
        if entry.get("case_manifest_sha256"):
            require(file_hash(case_path / "manifest.json") == entry["case_manifest_sha256"], "Knowledge case manifest changed without review")
        if not path.is_relative_to(root / "knowledge/local"):
            require(case_path.is_relative_to(root / "knowledge/examples"), "Project knowledge must not require private cases")
        record = bundles.verify(case_path)
        require(record["kind"] == "knowledge-case", "Wrong knowledge evidence type")
        require(record["metadata"]["scope"] == entry.get("scope", {}), "Knowledge evidence scope differs")
        require(not record["metadata"].get("required_external_files"), "Knowledge requires external output artifacts")
        references = record["metadata"].get("references")
        if references is not None:
            check_references(text, references, {f["path"] for f in record["files"]})
    extra = verify_supplements(entry, root)
    source_ids = set()
    for evidence in entry.get("evidence_sources", []):
        folder = inside(root, evidence["path"])
        require(folder.is_relative_to(root / "knowledge/examples"), "Class methods need independent project evidence")
        require(file_hash(folder / "manifest.json") == evidence["manifest_sha256"], "Class method evidence changed")
        source_case = bundles.verify(folder)
        require(source_case["kind"] in {"knowledge-case", "knowledge-evidence"}, "Class evidence must be a knowledge case")
        source_sha = source_case["metadata"].get("source_sha256")
        require(source_sha and source_sha == evidence["source_sha256"], "Class method source evidence mismatch")
        source_ids.add(source_sha)
    if entry.get("validation_level") == "multi_source_observations":
        require(len(source_ids) >= 2, "Cross-source guidance requires at least two distinct source videos")
    return {"id": entry["id"], "decision": "pass", "files": (len(record["files"]) if case_path else 1) + extra}


def audit(root=None):
    root = Path(root or ROOT)
    from .knowledge_review import decisions
    reviews = decisions(root)
    storage = None
    if (root / "knowledge/examples/storage-index.json").exists():
        from .knowledge_maintenance import audit as audit_storage
        from .candidate_index import verify as verify_candidates
        storage = audit_storage(root)
        verify_candidates(root)
    records = []
    method_count, reference_count = 0, 0
    for index in (root / "knowledge/index.json", root / "knowledge/cases/index.json", root / "config/knowledge.local.json"):
        if not index.exists():
            continue
        for entry in read_json(index).get("entries", []):
            if entry.get("status") == "active" and not entry.get("superseded_by"):
                records.append(verify_entry(entry, root))
                if index == root / "knowledge/cases/index.json":
                    reference_count += 1
                else:
                    method_count += 1
    return {"decision": "pass", "active_entries": len(records), "entries": records,
            "reviewed_source_versions": len(reviews),
            "evidence_storage": storage,
            "active_methods_and_policies": method_count, "active_source_references": reference_count,
            "scope": "Knowledge method/evidence completeness and independence; no new video-quality assessment"}


def enqueue(candidate, root=None):
    """Durable, idempotent input to later distillation; never activates a rule."""
    root = Path(root or ROOT)
    key = object_hash({"lesson": candidate.get("hypothesis"), "scope": candidate.get("scope")})
    path = root / "knowledge/local/inbox" / f"{candidate['id']}.json"
    if not path.exists():
        write_json(path, {"id": candidate["id"], "concept_id": key, "status": "pending_distillation",
                          "case": candidate.get("case"), "created_at": utc_now(),
                          "activation": "Candidate only; merge evidence without broadening scope or changing preferences"})
    return str(path.relative_to(root).as_posix())


def record_project_candidate(candidate, root=None):
    """Route technical learning into the project; raw observations stay private."""
    root = Path(root or ROOT)
    def references(value):
        if isinstance(value, dict):
            return {key: references(child) for key, child in value.items() if key != "case"}
        if isinstance(value, list):
            return [references(child) for child in value]
        if isinstance(value, str):
            return re.sub(r"(?:runs|outputs|work|inputs|analysis|review)/[^\s`]+",
                          lambda m: "origin:" + Path(m.group(0)).name, value)
        return value
    record = references(candidate)
    record.update(status="candidate", knowledge_class="project_training_candidate",
                  evidence_boundary="Technical observation and hashes; raw private case is not needed to read this hypothesis. Activation requires independently packaged reviewed evidence.")
    path = root / "knowledge/candidates" / f"{candidate['id']}.json"
    from .knowledge_records import archives, resolve
    if path.relative_to(root).as_posix() in archives(root):
        resolve(root, path.relative_to(root).as_posix())
    elif not path.exists():
        write_json(path, record)
    from .candidate_index import refresh
    refresh(root)
    return str(path.relative_to(root).as_posix())


def promote(spec_path, root=None):
    """Publish an explicitly reviewed method and self-contained evidence case."""
    from .knowledge import validate_feature_requirements
    root = Path(root or ROOT)
    spec = read_json(inside(root, spec_path))
    # Ordinary revisions retain required retrieval unless the review explicitly changes it.
    if spec.get('supersedes'):
        for name in ('knowledge/index.json', 'knowledge/cases/index.json', 'config/knowledge.local.json'):
            index_path = root / name
            if not index_path.exists():
                continue
            previous = next((e for e in read_json(index_path).get('entries', []) if e['id'] == spec['supersedes']), None)
            if previous:
                for key in ('retrieval_role', 'selection_review'):
                    if key not in spec and key in previous:
                        spec[key] = previous[key]
    from .knowledge_records import resolve
    for source in spec.get("candidate_sources", []):
        require(source["path"].startswith(("knowledge/candidates/", "knowledge/distillations/", "knowledge/local/")), "Invalid promotion source")
        resolve(root, source["path"], source["sha256"])
    validate_feature_requirements(spec)
    require(spec.get("approval_type") in {"explicit_user_feedback", "developer_review"}, "Knowledge activation needs an attributed review")
    require(bool(spec.get("reviewed_by")) and bool(spec.get("origin")), "Knowledge activation needs reviewer and origin")
    require(spec.get("company_preference") is False, "Company preference changes need a separate authorized preference process")
    method = inside(root, spec["path"])
    require(method.is_relative_to(root / "knowledge"), "Store the method in knowledge before publishing")
    source_specific = bool(spec.get("scope", {}).get("source_sha256"))
    require(not (source_specific and spec.get("knowledge_type") == "class_method"), "Class methods use content conditions, not a source-video scope")
    records = [inside(root, p) for p in spec["evidence_files"]]
    require(records, "Activation evidence is missing")
    run = inside(root / "runs", spec["source_run"]) if spec.get("source_run") else None
    visibility = "private" if method.is_relative_to(root / "knowledge/local") else "project"
    require(visibility == "private" or all("/local/" not in s["path"] for s in spec.get("candidate_sources", [])), "Public method needs sanitized public candidate sources")
    if visibility == "project":
        require(spec.get("evidence_review") == "sanitized_project_evidence", "Review and sanitize project examples before activation")
        if run:
            source_record = read_json(run / "run.json")
            require(file_hash(inside(run, source_record["source"])) == source_record["source_sha256"], "Source changed")
            require(any(file_hash(p) == spec.get("reference_video_sha256") for p in (run / "outputs").glob("*.mp4")), "Project example video is unbound")
        run = None
        if source_specific:
            canonical = inside(root / "knowledge/cases", spec["id"] + ".md")
            if canonical.exists():
                require(file_hash(canonical) == file_hash(method), "Source reference body already exists with different content")
            else:
                canonical.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(method, canonical)
            method = canonical
    case = capture_case(spec["id"], method.read_text(encoding="utf-8-sig"), spec["scope"], root,
                        run, spec.get("reference_video_sha256"), records, "reviewed_reference", visibility,
                        spec.get("evidence_references", {}))
    entry = {key: spec[key] for key in ("id", "path", "scope", "tags", "origin", "reviewed_by", "company_preference")}
    entry["path"] = method.relative_to(root).as_posix()
    entry.update(status="active", reviewed_at=utc_now(), method_sha256=file_hash(method),
                 case=case.relative_to(root).as_posix(), case_manifest_sha256=file_hash(case / "manifest.json"))
    if spec.get("candidate_sources"):
        entry["candidate_sources"] = spec["candidate_sources"]
    for key in ("reference_video_sha256", "source_run", "supersedes", "requires_features", "requires_any_features", "knowledge_type", "validation_level", "topic", "evidence_sources", "evidence_caveat", "delivery_modes", "language_match", "retrieval_role", "selection_review"):
        if spec.get(key):
            entry[key] = spec[key]
    verify_entry(entry, root)
    if visibility == "private":
        relative_index = "config/knowledge.local.json"
    else:
        relative_index = "knowledge/cases/index.json" if source_specific else "knowledge/index.json"
    if source_specific:
        entry["knowledge_type"] = "source_reference"
    path = root / relative_index
    index = read_json(path) if path.exists() else {"schema_version": 1, "entries": []}
    require(not any(e["id"] == entry["id"] for e in index["entries"]), "Knowledge id already exists; publish a new revision")
    for old in index["entries"]:
        if old["id"] == entry.get("supersedes"):
            old.update(status="superseded", superseded_by=entry["id"])
    index["entries"].append(entry)
    write_json(path, index)
    return {"id": entry["id"], "case": entry["case"], "status": "active"}
