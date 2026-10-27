"""Original candidate identities survive archival without rewriting their bytes."""
from pathlib import Path

from .common import file_hash, inside, read_json, require

ARCHIVE_INDEX = "knowledge/curation/candidate-archives.json"


def placeholder_lesson(value):
    """A missing reflection is bookkeeping, not a reusable observation."""
    return not isinstance(value, str) or value.strip().casefold() in {
        '', 'needs an evidence-backed lesson', '填写实际经验', '待填写经验',
        'preserved source observations, decisions and failure records await distillation.'
    }


def non_use_only(record):
    uses = record.get("uses", [])
    return bool(uses) and all(use.get("outcome") == "not_used" for use in uses)


def evidence_payload(path, base):
    """Case copies and raw ASR are evidence, not independent learning events."""
    path, base = Path(path), Path(base)
    if path.suffix != '.json':
        return False
    value = read_json(path)
    if value.get('kind') == 'knowledge-case':
        return True
    if all(key in value for key in ('segments', 'engine', 'audio_sha256')) and not any(
            key in value for key in ('hypothesis', 'lesson', 'quote', 'user_quote', 'source_quote')):
        return True
    for parent in path.parents:
        if parent == base or not parent.is_relative_to(base):
            break
        manifest = parent / 'manifest.json'
        if manifest.is_file() and read_json(manifest).get('kind') == 'knowledge-case':
            return True
    return False


def archives(root):
    path = Path(root) / ARCHIVE_INDEX
    return read_json(path)["entries"] if path.exists() else {}


def resolve(root, relative, digest=None):
    root = Path(root).resolve()
    path = inside(root, relative)
    if not path.is_file():
        entry = archives(root).get(relative)
        require(entry is not None, f"Knowledge source is missing: {relative}")
        path = inside(root / "knowledge/history/candidates", entry["archive_path"])
        require(file_hash(path) == entry["sha256"], "Archived candidate changed")
    require(digest is None or file_hash(path) == digest, f"Knowledge source revision changed: {relative}")
    return path


def candidate_files(root):
    root = Path(root).resolve()
    paths = {p.relative_to(root).as_posix() for p in (root / "knowledge/candidates").rglob("*")
             if p.is_file() and p.suffix in {".json", ".md"} and not p.name.startswith("index")
             and p.name != "README.md"}
    return [(name, resolve(root, name)) for name in sorted(paths | set(archives(root)))]
