"""Refresh the offline flowchart's public source snapshots and CLI help."""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from video_localizer.workspace import source_files

PATTERN = re.compile(r'(<script id="embedded-data" type="application/json">)(.*?)(</script>)', re.S)


def synchronize(check_only=False):
    page = ROOT / "docs/project-flow.html"
    html = page.read_text(encoding="utf-8")
    match = PATTERN.search(html)
    if not match:
        raise ValueError("Flowchart data block missing")
    data = json.loads(match[2])
    public = source_files(ROOT)
    paths = dict.fromkeys(source["path"] for source in data["sources"])
    stale = []
    snapshots = []
    for name in paths:
        if name not in public or name == "docs/project-flow.html":
            raise ValueError("Flowchart source is not a public source file: " + name)
        path = public[name]
        text = path.read_text(encoding="utf-8-sig")
        item = {"path": name, "text": text, "lines": len(text.splitlines()),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        snapshots.append(item)
        if item != next(source for source in data["sources"] if source["path"] == name):
            stale.append(name)
    if check_only:
        return {"decision": "fail" if stale else "pass", "stale_sources": stale,
                "sources": len(snapshots), "scope": "Embedded source snapshots; authored explanations need review"}
    names = {item["name"] for item in data["commands"]}
    help_command = [sys.executable, "-X", "utf8", str(ROOT / "bin/va.py")]
    top = subprocess.run([*help_command, "--help"], check=True, capture_output=True,
                         text=True, encoding="utf-8", cwd=ROOT).stdout
    actual = set(re.search(r"\{([^}\n]+)\}", top)[1].split(","))
    if names != actual:
        raise ValueError(f"Update authored command descriptions first: missing={sorted(actual-names)}, removed={sorted(names-actual)}")
    for command in data["commands"]:
        result = subprocess.run([*help_command, command["name"], "--help"],
                                check=True, capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
        command["help"] = result.stdout
    data["sources"] = snapshots
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    updated = html[:match.start(2)] + payload + html[match.end(2):]
    page.write_text(updated, encoding="utf-8", newline="\n")
    return {"decision": "pass", "updated_sources": len(stale), "sources": len(snapshots),
            "commands": len(names), "scope": "Source snapshots and local CLI help only; no media/model calls"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Read-only snapshot check")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    result = synchronize(args.check)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(result["decision"] != "pass")
