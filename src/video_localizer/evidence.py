"""Append-only evidence supplements and explicit, verifiable knowledge references."""
from __future__ import annotations

import re
from pathlib import Path

from . import bundles
from .common import ROOT, file_hash, inside, object_hash, read_json, require, utc_now, write_json

EVIDENCE_SUFFIXES = {".json", ".md", ".txt", ".png", ".jpg", ".jpeg", ".wav", ".webp", ".ass", ".csv", ".py"}


def check_references(text, references, available):
    for label in re.findall(r"evidence:([A-Za-z0-9_-]+)", text):
        require(label in references, f"Knowledge evidence reference is unresolved: {label}")
    for label, value in references.items():
        require(value in available, f"Knowledge evidence reference is not packaged: {label}")


def verify_supplements(entry, root):
    aliases = {}
    count = 0
    for supplement in entry.get("evidence_supplements", []):
        folder = inside(root, supplement["path"])
        require(folder.is_relative_to(Path(root) / "knowledge"), "Knowledge supplement must live in knowledge")
        if not str(entry["path"]).startswith("knowledge/local/"):
            require(folder.is_relative_to(Path(root) / "knowledge/examples"), "Project supplement requires project evidence")
        require(file_hash(folder / "manifest.json") == supplement["manifest_sha256"], "Knowledge supplement manifest changed")
        manifest = bundles.verify(folder)
        meta = manifest["metadata"]
        require(manifest["kind"] == "knowledge-evidence" and meta["entry_id"] == entry["id"], "Wrong knowledge supplement")
        require(meta["scope"] == entry.get("scope", {}), "Knowledge supplement scope differs")
        require(meta["case_manifest_sha256"] == entry["case_manifest_sha256"], "Supplement refers to another case revision")
        if entry.get("reference_video_sha256"):
            require(meta["video_sha256"] == entry["reference_video_sha256"], "Supplement belongs to another result")
        files = {f["path"] for f in manifest["files"]}
        for label, path in meta["references"].items():
            require(path in files, f"Required evidence missing from supplement: {label}")
            asset = next(item for item in manifest["files"] if item["path"] == path)
            aliases[label] = str(bundles.asset_path(folder, asset))
        count += len(files)
    for label in entry.get("required_evidence", []):
        require(label in aliases, f"Required knowledge evidence is unresolved: {label}")
    return count


def supplement(spec_path, root=None):
    root = Path(root or ROOT).resolve()
    spec = read_json(inside(root, spec_path))
    require(spec.get("evidence_review") == "sanitized_project_evidence" and bool(spec.get("reviewed_by")),
            "Evidence supplement needs attributed sanitization review")
    index_path, index, entry = None, None, None
    for path in (root / "knowledge/index.json", root / "knowledge/cases/index.json"):
        value = read_json(path) if path.exists() else {"entries": []}
        match = next((e for e in value["entries"] if e["id"] == spec["entry_id"]), None)
        if match:
            require(entry is None, "Knowledge id is duplicated across method and case catalogs")
            index_path, index, entry = path, value, match
    require(entry is not None, "Unknown knowledge entry")
    run = inside(root / "runs", spec["source_run"])
    source_record = read_json(run / "run.json")
    require(file_hash(inside(run, source_record["source"])) == source_record["source_sha256"], "Source changed")
    require(entry.get("scope", {}).get("source_sha256", source_record["source_sha256"]) == source_record["source_sha256"],
            "Supplement source differs from knowledge scope")
    video = spec["video_sha256"]
    require(not entry.get("reference_video_sha256") or entry["reference_video_sha256"] == video, "Supplement result differs")
    require(any(file_hash(p) == video for p in (run / "outputs").glob("*.mp4")), "Supplement video is unbound")
    sources, references = {}, {}
    for label, relative in spec["files"].items():
        path = inside(run, relative)
        require(path.is_file() and path.suffix.lower() in EVIDENCE_SUFFIXES, "Invalid knowledge evidence file")
        parts = Path(relative).parts
        if len(parts) > 2 and parts[0] == "review" and re.fullmatch(r"[a-f0-9]{12}", parts[1]):
            require(parts[1] == video[:12], "Evidence belongs to a different result video")
        require(not path.name.startswith(".env"), "Credentials cannot enter evidence")
        target = "evidence/" + Path(relative).as_posix()
        sources[target], references[label] = path, target
    require(sources, "Evidence supplement is empty")
    identity = object_hash({"entry": entry["id"], "files": {k: file_hash(p) for k, p in sources.items()}, "references": references})
    folder = inside(root / "knowledge/examples", "supplements/" + entry["id"] + "/" + identity)
    manifest = bundles.create(folder, "knowledge-evidence", identity, sources, {
        "entry_id": entry["id"], "scope": entry.get("scope", {}), "case_manifest_sha256": entry["case_manifest_sha256"],
        "source_sha256": source_record["source_sha256"], "video_sha256": video,
        "references": references, "reviewed_by": spec["reviewed_by"], "recorded_at": utc_now(),
        "proof_boundary": "Preserved historical evidence, not a new video review, independent acceptance or wider scope."})
    record = {"path": folder.relative_to(root).as_posix(), "manifest_sha256": file_hash(folder / "manifest.json")}
    entry["evidence_supplements"] = [s for s in entry.get("evidence_supplements", []) if s["path"] != record["path"]] + [record]
    entry["required_evidence"] = sorted(set(entry.get("required_evidence", [])) | set(spec.get("required_evidence", references)))
    verify_supplements(entry, root)
    write_json(index_path, index)
    return {"entry_id": entry["id"], "supplement": record, "files": len(manifest["files"]), "decision": "pass"}
