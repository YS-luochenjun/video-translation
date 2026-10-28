"""Exact-source extraction cache. Reused observations never approve a new translation."""
from __future__ import annotations

import copy
import re
import shutil
from pathlib import Path

from . import bundles
from .common import ROOT, file_hash, guarded, inside, lock, object_hash, read_json, require, write_json

EXTRACTION_VERSION = 2  # Full soundtrack measurement; v1 may contain a 181-second report.
RAW_NAMES = {"media.json", "frame-index.json", "audio.wav", "audio-source.json", "contact-pages.json", "extraction-settings.json"}
SEMANTIC_NAMES = {"ocr-source.json", "ocr-summary.json", "ocr-supplement.json", "audio-transcript.json"}


def parameters(root):
    settings = read_json(Path(root) / "config/workspace.json")
    return {"version": EXTRACTION_VERSION, "sampling_seconds": settings["sampling_seconds"],
            "max_segment_seconds": settings["max_segment_seconds"]}


def observations(inventory):
    """Only source descriptions and geometry; translated timing/layout stay in their locale run."""
    shots = [{k: copy.deepcopy(s[k]) for k in ("id", "start", "end", "keyframe", "description") if k in s}
             for s in inventory.get("shots", [])]
    text = []
    for item in inventory.get("text_instances", []):
        record = {k: copy.deepcopy(item[k]) for k in ("id", "source_text", "bbox", "text_role", "trajectory",
                                                     "publisher_identity", "mark_form") if k in item}
        interval = item.get("source_interval", [item.get("start"), item.get("end")])
        record.update(start=interval[0], end=interval[1])
        text.append(record)
    return {"schema_version": 1, "source_sha256": inventory["source_sha256"], "shots": shots,
            "text_instances": text, "content_features": inventory.get("content_features", []),
            "has_source_speech": inventory.get("audio", {}).get("has_speech"),
            "speech_observations": [{k: s[k] for k in ("id", "start", "end", "source_text", "source_language", "character_id", "speech_role") if k in s}
                                    for s in inventory.get("speech_segments", [])],
            "origin_coverage": inventory.get("coverage", {}),
            "proof_boundary": "Historical source observations for inspection; no target copy, voice, layout or new-locale approval."}


@guarded
def save(run, root=None):
    root, run = Path(root or ROOT), Path(run)
    record = read_json(run / "run.json")
    source = inside(run, record["source"])
    require(file_hash(source) == record["source_sha256"], "Source changed before saving analysis")
    require((run / "analysis/media.json").is_file() and (run / "analysis/inventory.json").is_file(),
            "Run has no extracted source analysis")
    inventory = read_json(run / "analysis/inventory.json")
    require(inventory["source_sha256"] == record["source_sha256"], "Source analysis belongs to another video")
    neutral = observations(inventory)
    neutral_path = run / "analysis/source-observations.json"
    write_json(neutral_path, neutral)
    sources = {record["source"]: source, "analysis/source-observations.json": neutral_path}
    for path in (run / "analysis").rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(run).as_posix()
        raw = path.name in RAW_NAMES or path.name.startswith(("shot-", "contact-sheet")) or path.parent.name == "frames"
        if path.name in SEMANTIC_NAMES:
            data = read_json(path)
            require(data.get("source_sha256") == record["source_sha256"], "Source OCR/transcript belongs to another video")
            raw = True
        if raw:
            require(path.resolve().is_relative_to(run.resolve()), "Analysis asset escapes its run")
            sources[relative] = path
    extraction = run / "analysis/extraction-settings.json"
    settings = read_json(extraction) if extraction.exists() else parameters(root)
    identity = object_hash({"parameters": settings, "files": {k: file_hash(p) for k, p in sources.items()}})
    folder = inside(root / "media", f"{record['source_sha256']}/{identity}")
    manifest = bundles.create(folder, "source-analysis", identity,
        {"payload/" + k: v for k, v in sources.items()},
        {"source_sha256": record["source_sha256"], "parameters": settings,
         "source": record["source"], "origin_run_id": run.name, "target_language": None})
    entry = {"snapshot": folder.relative_to(root).as_posix(), "manifest_sha256": file_hash(folder / "manifest.json"),
             "parameters": settings, "observed_instances": len(neutral["text_instances"]), "id": identity}
    index_path = folder.parent / "index.json"
    with lock(folder.parent / ".catalog.lock"):
        index = read_json(index_path) if index_path.exists() else {"schema_version": 1, "entries": []}
        index["entries"] = [e for e in index["entries"] if e["id"] != identity] + [entry]
        write_json(index_path, index)
    return {**entry, "files": len(manifest["files"]), "source_sha256": record["source_sha256"]}


def verify(entry, root, source_sha256):
    folder = inside(Path(root) / "media", str(Path(entry["snapshot"]).relative_to("media")))
    require(file_hash(folder / "manifest.json") == entry["manifest_sha256"], "Source snapshot manifest changed")
    manifest = bundles.verify(folder)
    require(manifest["kind"] == "source-analysis" and manifest["metadata"]["source_sha256"] == source_sha256,
            "Source snapshot identity mismatch")
    require(manifest["metadata"]["parameters"] == entry["parameters"], "Source snapshot parameters changed")
    require(manifest["identity"] == entry["id"], "Source snapshot revision mismatch")
    original = inside(folder, "payload/" + manifest["metadata"]["source"])
    require(file_hash(original) == source_sha256, "Source snapshot contains a different original")
    return folder, manifest


def find(source_sha256, root=None):
    root = Path(root or ROOT)
    require(re.fullmatch(r"[a-f0-9]{64}", source_sha256 or ""), "Invalid source SHA256")
    path = root / "media" / source_sha256 / "index.json"
    if not path.exists():
        return []
    entries = read_json(path)["entries"]
    for entry in entries:
        verify(entry, root, source_sha256)
    return entries


@guarded
def restore(run, root=None):
    root, run = Path(root or ROOT), Path(run)
    require(not (run / "analysis/inventory.json").exists(), "Existing inventory must not be overwritten")
    record = read_json(run / "run.json")
    source = record["source_sha256"]
    require(file_hash(inside(run, record["source"])) == source, "Source changed before analysis reuse")
    matches = [e for e in find(source, root) if e["parameters"] == parameters(root)]
    if not matches:
        return None
    entry = max(enumerate(matches), key=lambda pair: (pair[1]["observed_instances"], pair[0]))[1]
    folder, manifest = verify(entry, root, source)
    for asset in manifest["files"]:
        relative = asset["path"].removeprefix("payload/")
        if not relative.startswith("analysis/"):
            continue
        target = inside(run, relative)
        if target.exists():
            require(file_hash(target) == asset["sha256"], "Existing analysis differs from cached source")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(inside(folder, asset["path"]), target)
    neutral = read_json(run / "analysis/source-observations.json")
    require(neutral["source_sha256"] == source, "Cached source observations belong to another source")
    shots = neutral["shots"]
    hints = [{**item, "target_text": "", "action": "pending", "reason": "Inspect reused source observation for the new locale",
              "evidence": ["analysis/source-observations.json"]} for item in neutral["text_instances"]]
    inventory = {"schema_version": 1, "source_sha256": source, "shots": shots, "text_instances": hints,
                 "speech_segments": [], "source_speech_observations": neutral.get("speech_observations", []),
                 "content_features": neutral.get("content_features", []),
                 "coverage": {k: {"status": "pending", "method": "", "evidence": []} for k in ("visual", "speech", "timeline")},
                 "audio": {"has_speech": neutral.get("has_source_speech"), "strategy": "unknown", "reason": ""},
                 "notes": ["Reused exact-source extraction. Review source hints; create and verify this locale's copy, voice, captions and plan."]}
    write_json(run / "analysis/inventory.json", inventory)
    write_json(run / "analysis/reuse.json", {**entry, "source_sha256": source, "new_locale_approved": False})
    return {"state": "awaiting_agent_inventory", "reused": True, "source_snapshot": entry["snapshot"],
            "shots": len(shots), "inventory": str((run / "analysis/inventory.json").relative_to(root))}
