from __future__ import annotations

import random
from pathlib import Path

from .common import file_hash, guarded, inside, read_json, require, utc_now, write_json
from .media import ffmpeg, probe


@guarded
def freeze(run, candidates):
    require(2 <= len(candidates) <= 6, "Blind comparison needs 2-6 candidates")
    directory = run / "blind/package"
    require(not (run / "blind/freeze.json").exists(), "Comparison already frozen")
    require(not directory.exists(), "Unfinished package exists; inspect before retrying")
    directory.mkdir(parents=True)
    originals = [Path(path).resolve() for path in candidates]
    require(all(path.is_file() for path in originals), "Candidate missing")
    require(len({file_hash(path) for path in originals}) == len(originals), "Duplicate candidates")
    random.SystemRandom().shuffle(originals)
    mapping, manifest = {}, {}
    for i, source in enumerate(originals):
        label = chr(65+i)
        probe(source)
        target = directory / f"{label}.mp4"
        ffmpeg(["-i", source, "-map", "0:v:0", "-map", "0:a?", "-map_metadata", "-1", "-map_chapters", "-1",
                "-c", "copy", target])
        mapping[label] = {"source": str(source), "original_sha256": file_hash(source)}
        manifest[target.name] = file_hash(target)
    write_json(run / "reveal/mapping.json", mapping)
    write_json(run / "blind/freeze.json", {"created_at": utc_now(), "files": manifest,
               "mapping_sha256": file_hash(run / "reveal/mapping.json"),
               "warning": "Operational blinding only. A reviewer with workspace access can read reveal; use a separate review context."})
    write_json(run / "blind/review-template.json", {"reviewer": "", "winner": None,
               "candidates": {label: {"score": None, "reason": ""} for label in mapping}, "limitations": []})
    return {"package": str(directory), "count": len(manifest), "frozen": True}


def verify(run):
    freeze_record = read_json(run / "blind/freeze.json")
    directory = run / "blind/package"
    require({path.name for path in directory.iterdir()} == set(freeze_record["files"]), "Blind package file list changed")
    for name, digest in freeze_record["files"].items():
        require(file_hash(inside(directory, name)) == digest, "Blind candidate changed after freeze")
    require(freeze_record.get("mapping_sha256") and file_hash(run / "reveal/mapping.json") == freeze_record["mapping_sha256"],
            "Blind source mapping changed after freeze")
    return {"valid": True, "files": len(freeze_record["files"])}


@guarded
def reveal(run):
    verify(run)
    review = read_json(run / "blind/review.json")
    mapping = read_json(run / "reveal/mapping.json")
    require(review.get("reviewer") and review.get("winner") in (*mapping, "tie"), "Complete blind review before revealing")
    require(set(review.get("candidates", {})) == set(mapping), "Review all candidates")
    for item in review["candidates"].values():
        score = item.get("score")
        require(isinstance(score, (int, float)) and not isinstance(score, bool) and 0 <= score <= 100 and item.get("reason"),
                "Every blind candidate needs score and reason")
    write_json(run / "reveal/result.json", {"review_sha256": file_hash(run / "blind/review.json"),
               "revealed_at": utc_now(), "mapping": mapping, "winner": review["winner"],
               "preference_status": "comparison_evidence_only"})
    return {"mapping": mapping, "winner": review["winner"]}

