"""Append-only, exact-asset quality objections independent of runs and deliveries."""
from __future__ import annotations

import re
from pathlib import Path

from . import bundles
from .common import ROOT, file_hash, inside, lock, object_hash, read_json, require, utc_now, write_json
from .evidence import EVIDENCE_SUFFIXES

DIRECTORY = "knowledge/local/quality-holds"


def _branch(root, source_sha256, asset_sha256):
    for digest in (source_sha256, asset_sha256):
        require(isinstance(digest, str) and re.fullmatch(r"[a-f0-9]{64}", digest),
                "Quality hold requires full source and asset SHA256")
    return inside(inside(root, DIRECTORY), source_sha256 + "/" + asset_sha256)


def active(source_sha256, asset_sha256, root=None):
    root = Path(root or ROOT).resolve()
    branch = _branch(root, source_sha256, asset_sha256)
    if not branch.exists():
        return []
    require((branch / "index.json").is_file(), "Incomplete quality hold; inspect before production")
    index = read_json(branch / "index.json")
    require(index.get("schema_version") == 1 and isinstance(index.get("entries"), list)
            and bool(index["entries"]), "Invalid quality hold index")
    result, seen = [], set()
    for entry in index["entries"]:
        identifier = entry.get("id")
        require(isinstance(identifier, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}", identifier)
                and identifier not in seen, "Invalid or duplicate quality hold id")
        seen.add(identifier)
        folder = inside(branch, identifier)
        require((folder / "manifest.json").is_file()
                and file_hash(folder / "manifest.json") == entry.get("manifest_sha256"),
                "Quality hold manifest missing or changed")
        manifest = bundles.verify(folder)
        meta = manifest["metadata"]
        require(manifest["kind"] == "quality-hold" and meta.get("id") == identifier
                and meta.get("source_sha256") == source_sha256
                and meta.get("asset_sha256") == asset_sha256, "Quality hold identity mismatch")
        require(meta.get("asset_kind") in {"video", "neutral_master"}
                and isinstance(meta.get("reason"), str) and bool(meta["reason"].strip())
                and bool(meta.get("reported_by")), "Quality hold attribution is incomplete")
        result.append({**meta, "case": folder.relative_to(root).as_posix(),
                       "manifest_sha256": entry["manifest_sha256"]})
    return result


def require_clear(source_sha256, asset_sha256, root=None):
    holds = active(source_sha256, asset_sha256, root)
    require(not holds, "Quality hold blocks production/delivery: " +
            "; ".join(hold["id"] + ": " + hold["reason"] for hold in holds))


def record(spec_path, root=None):
    """Capture attributed feedback and evidence; never alter a historical package."""
    root = Path(root or ROOT).resolve()
    spec = read_json(inside(root, spec_path))
    identifier = spec.get("id")
    require(isinstance(identifier, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}", identifier),
            "Invalid quality hold id")
    require(spec.get("asset_kind") in {"video", "neutral_master"}, "Invalid quality hold asset kind")
    for key in ("reason", "reported_by"):
        require(isinstance(spec.get(key), str) and bool(spec[key].strip()), f"Quality hold needs {key}")
    source, asset = spec["source"], spec["asset"]
    branch = _branch(root, source["sha256"], asset["sha256"])
    for binding in (source, asset):
        path = inside(root, binding["path"])
        require(path.is_file() and file_hash(path) == binding["sha256"], "Quality hold source/asset changed")
    require(isinstance(spec.get("evidence"), list) and bool(spec["evidence"]),
            "Quality hold requires evidence")
    files = {}
    for number, binding in enumerate(spec["evidence"]):
        path = inside(root, binding["path"])
        require(path.is_file() and path.suffix.lower() in EVIDENCE_SUFFIXES
                and file_hash(path) == binding["sha256"], "Quality hold evidence missing or changed")
        files[f"evidence/{number:02}-{path.name}"] = path
    metadata = {"id": identifier, "source_sha256": source["sha256"], "asset_sha256": asset["sha256"],
                "asset_kind": spec["asset_kind"], "reason": spec["reason"], "reported_by": spec["reported_by"],
                "origin": spec.get("origin", {}),
                "boundary": "Exact rejected asset only. Historical acceptance remains recorded; repaired bytes need fresh review."}
    identity = object_hash({"metadata": metadata, "files": {name: file_hash(path) for name, path in files.items()}})
    with lock(root / DIRECTORY / ".record.lock"):
        folder = branch / identifier
        if (folder / "manifest.json").exists():
            require(bundles.verify(folder)["identity"] == identity, "Quality hold changed; create a new event id")
        bundles.create(folder, "quality-hold", identity, files, {**metadata, "recorded_at": utc_now()})
        index_path = branch / "index.json"
        index = read_json(index_path) if index_path.exists() else {"schema_version": 1, "entries": []}
        previous = next((e for e in index["entries"] if e["id"] == identifier), None)
        digest = file_hash(folder / "manifest.json")
        if previous:
            require(previous["manifest_sha256"] == digest, "Quality hold manifest changed")
        else:
            index["entries"].append({"id": identifier, "manifest_sha256": digest})
            write_json(index_path, index)
        verified = active(source["sha256"], asset["sha256"], root)
    return {"decision": "hold", "asset_sha256": asset["sha256"], "notices": verified,
            "historical_files_modified": 0}
