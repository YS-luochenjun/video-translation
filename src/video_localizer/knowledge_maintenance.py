"""Exact-byte evidence compaction with an explicit, reproducible deletion plan."""
from collections import defaultdict
from pathlib import Path
import shutil

from . import bundles
from .common import file_hash, inside, object_hash, read_json, require, write_json
from .evidence_storage import catalog


def inventory(root):
    base = Path(root).resolve() / "knowledge/examples"
    assets, manifests = {}, {}
    for path in sorted(base.rglob("manifest.json")):
        record = bundles.verify(path.parent)
        require(record["kind"] in {"knowledge-case", "knowledge-evidence"}, "Unexpected public evidence bundle kind")
        manifests[path.relative_to(base).as_posix()] = file_hash(path)
        storage = catalog(path.parent)
        for asset in record["files"]:
            logical = inside(path.parent, asset["path"]).relative_to(base).as_posix()
            require(logical not in assets, f"Evidence path belongs to multiple bundles: {logical}")
            assets[logical] = {"sha256": asset["sha256"], "bytes": asset["bytes"],
                               "source": bundles.asset_path(path.parent, asset, storage)}
    return base, assets, manifests


def preview(root):
    base, assets, manifests = inventory(root)
    _, existing = catalog(base)
    require(set(existing).issubset(assets), "Storage alias has no original manifest")
    groups = defaultdict(list)
    for logical, asset in assets.items():
        groups[asset["sha256"]].append(logical)
    aliases = {}
    for digest, names in sorted(groups.items()):
        if len(names) < 2 and not any(name in existing for name in names):
            continue
        previous = {existing[name]["object"] for name in names if name in existing}
        require(len(previous) <= 1, "Same evidence hash maps to multiple objects")
        suffix = Path(names[0]).suffix.lower().lstrip(".") or "bin"
        target = next(iter(previous)) if previous else f"_objects/{digest}.{suffix}"
        for name in names:
            aliases[name] = {"object": target, "sha256": digest, "bytes": assets[name]["bytes"]}
    delete = []
    for name, alias in sorted(aliases.items()):
        path = inside(base, name)
        if path.exists():
            require(path == base / name and path.is_file(), "Compaction input is redirected")
            require(file_hash(path) == alias["sha256"], f"Original evidence changed: {name}")
            delete.append(name)
    objects = {alias["object"]: alias for alias in aliases.values()}
    added_bytes = 0
    for name, alias in objects.items():
        path = inside(base, name)
        require(path == base / name, "Object destination is redirected")
        if path.exists():
            require(file_hash(path) == alias["sha256"], "Existing evidence object changed")
        else:
            added_bytes += alias["bytes"]
    value = {"schema_version": 1, "manifests": manifests, "aliases": aliases, "delete": delete,
             "logical_bytes_removed": sum(aliases[name]["bytes"] for name in delete) - added_bytes,
             "objects": len(objects)}
    return {**value, "fingerprint": object_hash(value)}


def compact(root, expected):
    root = Path(root).resolve()
    plan = preview(root)
    require(plan["fingerprint"] == expected, "Evidence compaction preview changed; inspect a new preview")
    base, assets, _ = inventory(root)
    # Copy and verify every shared object before publishing aliases or deleting files.
    for name, alias in plan["aliases"].items():
        target = inside(base, alias["object"])
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + ".tmp")
            shutil.copyfile(assets[name]["source"], temporary)
            require(file_hash(temporary) == alias["sha256"], "Shared evidence copy changed")
            temporary.replace(target)
    # Recheck the original plan immediately before the completion marker.
    # New object files do not change manifests, aliases or candidate judgments.
    for name, digest in plan["manifests"].items():
        require(file_hash(inside(base, name)) == digest, "Manifest changed during compaction")
    write_json(base / "storage-index.json", {"schema_version": 1,
        "semantics": "Logical paths belong to unchanged bundle manifests. Shared bytes are scoped only by those manifests; sharing is not independent evidence or wider approval.",
        "aliases": plan["aliases"]})
    inventory(root)
    for name in plan["delete"]:
        original = inside(base, name)
        alias = plan["aliases"][name]
        require(original == base / name and not name.startswith("_objects/"), "Unsafe compaction deletion")
        require(file_hash(original) == alias["sha256"]
                and file_hash(inside(base, alias["object"])) == alias["sha256"],
                "Evidence changed before duplicate deletion")
        original.unlink()
    result = audit(root)
    return {**result, "removed_files": len(plan["delete"]),
            "logical_bytes_removed": plan["logical_bytes_removed"], "fingerprint": expected}


def audit(root):
    base, assets, manifests = inventory(root)
    _, aliases = catalog(base)
    require(set(aliases).issubset(assets), "Storage alias has no original manifest")
    objects = {value["object"] for value in aliases.values()}
    stored = {path.relative_to(base).as_posix() for path in (base / "_objects").rglob("*") if path.is_file()}
    require(objects == stored, "Unindexed or missing shared evidence objects")
    return {"decision": "pass", "bundles": len(manifests), "logical_assets": len(assets),
            "shared_aliases": len(aliases), "shared_objects": len(objects)}


def resolve_path(root, relative):
    root = Path(root).resolve()
    base, path = root / "knowledge/examples", inside(root, relative)
    require(path.is_relative_to(base), "Expected a knowledge/examples logical path")
    for folder in path.parents:
        if folder == base:
            break
        if (folder / "manifest.json").is_file():
            manifest = bundles.verify(folder)
            logical = path.relative_to(folder).as_posix()
            asset = next((item for item in manifest["files"] if item["path"] == logical), None)
            require(asset is not None, "Path is not bound by the evidence manifest")
            return {"logical_path": relative, "path": str(bundles.asset_path(folder, asset)),
                    "sha256": asset["sha256"], "bytes": asset["bytes"]}
    require(False, "Evidence manifest not found")
