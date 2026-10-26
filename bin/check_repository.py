"""Check the portable source tree without modifying files or contacting services."""
import hashlib
import json
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from video_localizer.common import inside
from video_localizer.workspace import source_files
from video_localizer import candidate_index, knowledge_maintenance
from video_localizer.common import WorkflowError


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets = []

    def handle_starttag(self, tag, attrs):
        self.targets.extend(value for name, value in attrs
                            if name in {"href", "src"} and value)


def check(root=ROOT):
    root = Path(root).resolve()
    files = source_files(root)
    errors = []
    if (root / "knowledge/examples/storage-index.json").exists():
        try:
            knowledge_maintenance.audit(root)
            candidate_index.verify(root)
        except (WorkflowError, OSError, ValueError, KeyError) as exc:
            errors.append(f"Knowledge maintenance check failed: {exc}")
    entries = []
    for name in ("knowledge/index.json", "knowledge/cases/index.json"):
        path = root / name
        if path.exists():
            entries.extend(json.loads(path.read_text(encoding="utf-8"))["entries"])
    by_id = {entry["id"]: entry for entry in entries}
    if len(by_id) != len(entries):
        errors.append("Duplicate knowledge ID across method and source indexes")
    indexed = set()
    for entry in entries:
        relative = entry["path"]
        indexed.add(relative)
        path = inside(root, relative)
        if relative not in files:
            errors.append(f"Indexed knowledge is outside the source package: {relative}")
        if not path.is_file():
            errors.append(f"Missing knowledge body: {relative}")
            continue
        expected = entry.get("method_sha256")
        if expected and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            errors.append(f"Knowledge body hash differs: {relative}")
        seen, cursor = set(), entry
        while cursor.get("superseded_by"):
            if cursor["id"] in seen:
                errors.append(f"Cyclic knowledge replacement: {entry['id']}")
                break
            seen.add(cursor["id"])
            successor = cursor["superseded_by"]
            if successor not in by_id:
                errors.append(f"Missing knowledge successor: {successor}")
                break
            cursor = by_id[successor]
        if entry.get("status") == "superseded" and not entry.get("superseded_by"):
            errors.append(f"Superseded knowledge has no successor: {entry['id']}")
        if entry.get("status") == "active" and relative.startswith("knowledge/history/"):
            errors.append(f"Active knowledge stored as history: {relative}")
    bodies = {}
    for area in ("rules", "cases"):
        for path in (root / "knowledge" / area).glob("*.md"):
            if path.name == "README.md":
                continue
            relative = path.relative_to(root).as_posix()
            if relative not in indexed:
                errors.append(f"Unindexed current knowledge body: {relative}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest in bodies:
                errors.append(f"Duplicate current knowledge bodies: {bodies[digest]}, {relative}")
            bodies[digest] = relative

    checked_links = 0
    for relative, path in files.items():
        # Immutable evidence and historical prose retain their original source labels.
        if (path.suffix not in {".md", ".html"}
                or relative.startswith(("knowledge/examples/", "knowledge/history/",
                                        "knowledge/candidates/", "knowledge/distillations/",
                                        "docs/requirements/", "docs/research/"))):
            continue
        body = path.read_text(encoding="utf-8-sig")
        if path.suffix == ".html":
            parser = Links()
            parser.feed(body)
            targets = parser.targets
            if relative == "docs/project-flow.html":
                match = re.search(r'<script id="embedded-data" type="application/json">(.*?)</script>', body, re.S)
                if not match:
                    errors.append("Flowchart source data missing")
                else:
                    for source in json.loads(match[1])["sources"]:
                        name = source["path"]
                        if name not in files or hashlib.sha256(files[name].read_bytes()).hexdigest() != source["sha256"]:
                            errors.append(f"Flowchart source snapshot is stale: {name}; run bin/sync_flow_reference.py")
        else:
            prose = re.sub(r"```.*?```", "", body, flags=re.S)
            targets = re.findall(r"\[[^\]]*\]\(([^)]+)\)", prose)
            # Root-relative operating instructions often use code spans rather
            # than links. Verify these too after a directory migration.
            for name in re.findall(r"`((?:agent|docs|config|src|bin|\.agents/skills)/[^`\s<>*{}]+)`", prose):
                if Path(name).suffix in {".md", ".json", ".py", ".ps1"} and not name.endswith(".local.json"):
                    targets.append(os.path.relpath(root / name, path.parent).replace("\\", "/"))
        for target in targets:
            target = target.strip().strip("<>").split(' "', 1)[0]
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            resolved = (path.parent / unquote(parsed.path)).resolve()
            checked_links += 1
            if not resolved.is_relative_to(root):
                errors.append(f"Link leaves the source package: {relative} -> {target}")
                continue
            linked = resolved.relative_to(root).as_posix()
            included = linked in files or any(name.startswith(linked.rstrip("/") + "/") for name in files)
            if not included:
                errors.append(f"Link missing from source package: {relative} -> {target}")
        if relative.startswith(("agent/", "docs/")) and path.suffix == ".md":
            if "docs/verification/" in body:
                errors.append(f"Current documentation depends on local verification reports: {relative}")

    # Nested profile and hook references must also survive clean initialization.
    for path in (root / "config/profiles").glob("*/profile.json"):
        method = json.loads(path.read_text(encoding="utf-8"))["method"]
        if method not in files:
            errors.append(f"Profile method missing from source package: {method}")
    hooks = root / "config/hooks.json"
    if hooks.exists():
        prompt = json.loads(hooks.read_text(encoding="utf-8"))["knowledge_daily"]["prompt"]
        if prompt not in files:
            errors.append(f"Hook prompt missing from source package: {prompt}")

    return {"decision": "fail" if errors else "pass", "files": len(files),
            "knowledge_entries": len(entries), "checked_links": checked_links,
            "source_bytes": sum(path.stat().st_size for path in files.values()),
            "errors": errors,
            "scope": "Source inclusion, knowledge identity/history and current document links; not secret certification or video acceptance"}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    result = check()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["decision"] == "pass" else 1)
