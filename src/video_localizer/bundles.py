"""Immutable bundles; public knowledge may share bytes within knowledge/examples."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from .common import file_hash, inside, operation_hash, read_json, require, utc_now, write_json
from .evidence_storage import catalog, resolve as asset_path


def create(directory, kind, identity, sources, metadata=None):
    """Copy bytes, never link to mutable runs. Manifest is the completion marker."""
    directory = Path(directory)
    manifest = directory / "manifest.json"
    if manifest.exists():
        result = verify(directory)
        require(result["kind"] == kind and result["identity"] == identity, "Bundle identity collision")
        return result
    directory.mkdir(parents=True, exist_ok=True)
    files, copied, hashes = [], {}, {}
    for relative, source in sorted(sources.items()):
        source = Path(source)
        require(source.is_file(), f"Bundle input missing: {relative}")
        require(source.name != ".env" and not source.name.startswith(".env."), "Credentials cannot enter bundles")
        target = inside(directory, relative)
        require(target != manifest, "Reserved bundle manifest path")
        digest = operation_hash(source, hashes)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            require(file_hash(target) == digest, f"Partial bundle changed: {relative}")
        elif digest in copied:
            try:
                os.link(copied[digest], target)
            except OSError:
                shutil.copyfile(source, target)
        else:
            shutil.copyfile(source, target)
        copied[digest] = target
        require(operation_hash(target, hashes) == digest, f"Bundle copy mismatch: {relative}")
        files.append({"path": relative, "sha256": digest, "bytes": target.stat().st_size})
    record = {"schema_version": 1, "kind": kind, "identity": identity, "created_at": utc_now(),
              "files": files, "metadata": metadata or {}}
    write_json(manifest, record)
    return verify(directory)


def verify(directory):
    directory = Path(directory)
    record = read_json(directory / "manifest.json")
    require(record.get("schema_version") == 1 and bool(record.get("files")), "Incomplete bundle manifest")
    seen, hashes = set(), {}
    storage = catalog(directory)
    for asset in record["files"]:
        require(asset["path"] not in seen, "Duplicate bundle path")
        seen.add(asset["path"])
        path = asset_path(directory, asset, storage)
        require(path.is_file() and path.stat().st_size == asset["bytes"]
                and operation_hash(path, hashes) == asset["sha256"], f"Bundle asset missing or changed: {asset['path']}")
    return record


def extract(directory, destination):
    """Materialize a verified delivery payload without consulting its original run."""
    directory, destination = Path(directory), Path(destination)
    record = verify(directory)
    require(record["kind"] == "delivery", "Only delivery bundles have a run payload")
    require(not destination.exists(), "Restore destination already exists")
    destination.mkdir(parents=True)
    for asset in record["files"]:
        if not asset["path"].startswith("payload/"):
            continue
        target = inside(destination, asset["path"][len("payload/"):])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(inside(directory, asset["path"]), target)
        require(file_hash(target) == asset["sha256"], "Restored asset differs")
    return {"directory": str(destination), "source_sha256": record["metadata"]["source_sha256"],
            "note": "Historical snapshot, not a new accepted run. New locale/copy requires new inventory, voice, typography, plan and review."}
