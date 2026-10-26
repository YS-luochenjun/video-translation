"""Resolve immutable manifest paths through the public evidence content store."""
from pathlib import Path
import re

from .common import inside, read_json, require


def catalog(directory):
    directory = Path(directory).resolve()
    for parent in (directory, *directory.parents):
        if parent.name == "examples" and parent.parent.name == "knowledge":
            index = parent / "storage-index.json"
            if index.is_file():
                record = read_json(index)
                require(record.get("schema_version") == 1, "Unknown evidence storage schema")
                return parent, record["aliases"]
            break
    return None, {}


def resolve(directory, asset, storage=None):
    """The original manifest remains authoritative for logical path, hash and size."""
    directory = Path(directory).resolve()
    original = inside(directory, asset["path"])
    base, aliases = storage if storage is not None else catalog(directory)
    alias = aliases.get(original.relative_to(base).as_posix()) if base else None
    if alias is None:
        return original
    require(alias["sha256"] == asset["sha256"] and alias["bytes"] == asset["bytes"],
            "Evidence storage alias differs from original manifest")
    name = alias["object"]
    require(re.fullmatch(r"_objects/[a-f0-9]{64}\.[a-z0-9]+", name) is not None,
            "Invalid evidence object path")
    require(Path(name).stem == asset["sha256"], "Evidence object name differs from hash")
    path = inside(base, name)
    require(path == base / name, "Evidence object cannot be a redirected path")
    return path
