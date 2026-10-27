"""Initialize a portable workspace outside the executable checkout, without credentials."""
from pathlib import Path
import os
import shutil

from .common import CODE_ROOT, file_hash, inside, read_json, require, write_json


# A fresh copy is built from a positive list, never by copying the whole checkout.
# Keep source and evidence bytes unchanged: plans/knowledge bind their hashes.
PUBLIC_DIRECTORIES = (
    "agent", "docs", "config", ".agents/skills",
    "knowledge/rules", "knowledge/cases", "knowledge/examples",
    "knowledge/candidates", "knowledge/distillations", "knowledge/curation", "knowledge/history",
)
SOURCE_DIRECTORIES = ("bin", "src", "tests", "workbench")
RUNTIME_DIRECTORIES = {"node_modules", ".cache", "__pycache__", ".pytest_cache", ".venv", ".runtime"}


def _tree_files(folder):
    """Do not walk installed dependencies or build caches in public trees."""
    for directory, names, files in os.walk(folder, followlinks=False):
        names[:] = [name for name in names if name not in RUNTIME_DIRECTORIES]
        for name in names:
            require(not (Path(directory) / name).is_symlink(), "Workspace input is a link: " + name)
        yield from (Path(directory) / name for name in files)


def public_files(source):
    source = Path(source).resolve()
    paths = [source / name for name in ("AGENTS.md", ".env.example", "knowledge/index.json")]
    for name in ("README.md", "knowledge/README.md"):
        if (source / name).is_file():
            paths.append(source / name)
    for name in PUBLIC_DIRECTORIES:
        folder = source / name
        if folder.exists():
            paths.extend(_tree_files(folder))
    return _checked_files(source, paths)


def _checked_files(source, paths):
    result = {}
    for path in sorted(paths):
        relative = path.relative_to(source)
        if (RUNTIME_DIRECTORIES.intersection(relative.parts) or path.suffix in (".pyc", ".pyo")
                or relative.parts[:2] == ("docs", "verification")
                or path.name.endswith(".local.json") or path.name == ".env"
                or (path.name.startswith(".env.") and path.name != ".env.example")):
            continue
        require(path.is_file(), f"Workspace input missing: {relative.as_posix()}")
        # Reject links/junctions, including an ancestor redirected outside the checkout.
        require(path.resolve() == source / relative, f"Workspace input is a link: {relative.as_posix()}")
        result[relative.as_posix()] = path
    return result


def source_files(source):
    """The portable source boundary shared by export and repository checks."""
    source = Path(source).resolve()
    files = public_files(source)
    extras = [source / name for name in ("README.md", "pyproject.toml", ".gitignore", ".gitattributes")]
    for name in SOURCE_DIRECTORIES:
        extras.extend(_tree_files(source / name))
    files.update(_checked_files(source, extras))
    return files


def _copy(target, files):
    for relative, source in files.items():
        destination = inside(target, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        require(file_hash(destination) == file_hash(source), f"Workspace copy changed: {relative}")


def initialize(destination, source=None):
    source = Path(source or CODE_ROOT).resolve()
    target = Path(destination).expanduser().resolve()
    require(not target.exists(), "Workspace destination already exists")
    for name in (*PUBLIC_DIRECTORIES, *SOURCE_DIRECTORIES, "knowledge", "runs", "outputs", "media", "state"):
        require(not target.is_relative_to(source / name), "Workspace destination overlaps project data")
    files = public_files(source)
    target.mkdir(parents=True)
    _copy(target, files)
    return {"workspace": str(target), "environment_variable": "VIDEO_LOCALIZER_WORKSPACE",
            "scope": "Public knowledge and execution policy copied. Private knowledge, media, state, caches and credentials need separate managed migration."}


def export(destination, source=None):
    """Create a runnable source distribution for a fresh operator simulation."""
    from .learning import audit

    source = Path(source or CODE_ROOT).resolve()
    target = Path(destination).expanduser().resolve()
    require(not target.exists(), "Export destination already exists; choose a new empty destination")
    # A destination inside a copied tree could recursively become an input next time.
    copied_directories = (*PUBLIC_DIRECTORIES, *SOURCE_DIRECTORIES)
    for name in (*copied_directories, "runs", "outputs", "media", "state", "knowledge"):
        require(not target.is_relative_to(source / name), "Export destination overlaps project data")
    files = source_files(source)
    target.mkdir(parents=True)
    _copy(target, files)
    audit_result = audit(target)
    for name in ("runs", "outputs", "media", "state", "work", "knowledge/local", "assets/fonts"):
        (target / name).mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": 1, "kind": "fresh-workspace",
        "files": [{"path": relative, "sha256": file_hash(target / relative),
                   "bytes": (target / relative).stat().st_size} for relative in sorted(files)],
        "knowledge": {key: audit_result[key] for key in
                      ("decision", "active_entries", "active_methods_and_policies", "active_source_references")},
        "excluded": ["credentials", "private knowledge", "runs", "outputs", "media", "state",
                     "tool/model caches", "local fonts", "Git history", "cold archives"],
        "scope": "Runnable source and public knowledge; requires Python, media dependencies and an AI operator. No hosted application.",
    }
    write_json(target / "fresh-workspace.json", record)
    return {"workspace": str(target), **verify_export(target)}


def verify_export(directory):
    from .learning import audit

    directory = Path(directory).resolve()
    record = read_json(directory / "fresh-workspace.json")
    require(record.get("schema_version") == 1 and record.get("kind") == "fresh-workspace",
            "Not a fresh workspace manifest")
    require(bool(record.get("files")), "Empty fresh workspace manifest")
    seen = set()
    for item in record["files"]:
        require(item["path"] not in seen, "Duplicate fresh workspace path")
        seen.add(item["path"])
        path = inside(directory, item["path"])
        require(path.is_file() and file_hash(path) == item["sha256"],
                f"Fresh workspace file missing or changed: {item['path']}")
    result = audit(directory)
    return {"decision": "pass", "files": len(seen), "knowledge_entries": result["active_entries"],
            "scope": "Exported source/public evidence hashes only; newly generated runtime files are not part of the baseline"}
