"""Maintain public knowledge storage and candidate navigation without promotion."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from video_localizer import candidate_index, knowledge_maintenance
from video_localizer.common import ROOT, require


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preview", "compact", "reindex", "check", "resolve"))
    parser.add_argument("path", nargs="?")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expect")
    args = parser.parse_args()
    if args.command == "preview":
        result = knowledge_maintenance.preview(args.root)
        result = {key: (len(value) if key in {"aliases", "manifests", "delete"} else value)
                  for key, value in result.items()}
    elif args.command == "compact":
        require(args.execute and args.expect, "Compaction requires --execute --expect <preview fingerprint>")
        result = knowledge_maintenance.compact(args.root, args.expect)
    elif args.command == "reindex":
        result = candidate_index.refresh(args.root)
        result = {"entries": len(result["entries"]), "counts": result["counts"],
                  "exact_hypothesis_groups": len(result["exact_hypothesis_groups"])}
    elif args.command == "resolve":
        require(args.path, "Provide the original project-relative evidence path")
        result = knowledge_maintenance.resolve_path(args.root, args.path)
    else:
        candidate_index.verify(args.root)
        result = knowledge_maintenance.audit(args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
