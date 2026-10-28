"""Shared spoken copy, audio-bound caption timing, and attributed AV review.

Alignment is imported from listening/forced alignment, never inferred by evenly
distributing characters. This module checks evidence bindings and consistency;
it does not itself hear speech or recognize lettering in video pixels.
"""
from __future__ import annotations

import copy
import unicodedata

from .common import (WorkflowError, file_hash, guarded, inside, object_hash, read_json,
                     require, require_number, write_json)


def normalized(text):
    """Ignore sentence punctuation/spacing, preserving numeric punctuation/units."""
    text = unicodedata.normalize("NFC", text)
    result = []
    for index, char in enumerate(text):
        numeric = 0 < index < len(text)-1 and text[index-1].isdigit() and text[index+1].isdigit()
        if not char.isspace() and (char not in "，,。.!！?？；;：:、" or numeric):
            result.append(char)
    return "".join(result)


def contract(inventory, check_timing=True):
    texts = inventory.get("text_instances", [])
    speeches = inventory.get("speech_segments", [])
    has_speech = inventory.get("audio", {}).get("has_speech")
    captions = [item for item in texts if item.get("text_role") == "speech_caption"]
    require(not captions or has_speech is True, "Caption speech must be identified before synchronization")
    if has_speech is not True:
        return {"version": 1, "required": False, "speech": [], "caption_ids": []}
    require(bool(speeches), "Caption synchronization needs the actual speech inventory")
    for item in texts:
        require(item.get("text_role") in ("speech_caption", "scene_text", "preserve", "publisher_mark"),
                "Classify text_role as speech_caption/scene_text/preserve/publisher_mark: " + item["id"])
        require(item.get("text_role") != "preserve" or item.get("action") == "preserve",
                "Preserved text must use the preserve action")
        if item.get("text_role") == "speech_caption" and check_timing:
            timed = checked_units(units(item), item["end"])
            require(all(unit["start"] >= item["start"] for unit in timed), "Caption units precede their instance window")
            require(normalized("".join(unit["text"] for unit in timed)) == normalized(item["target_text"]),
                    "Caption fragments differ from final instance copy: " + item["id"])
    by_id = {item["id"]: item for item in captions}
    assigned, records = [], []
    for speech in speeches:
        ids = speech.get("caption_ids", [])
        require(isinstance(ids, list), "caption_ids must be an ordered list")
        mode = speech.get("caption_policy")
        require(mode in ("verbatim", "none"), "Choose caption_policy verbatim/none: " + speech["id"])
        if mode == "none":
            require(not ids and bool(speech.get("caption_reason")), "No-caption speech requires a reason")
        else:
            require(bool(ids) and len(ids) == len(set(ids)), "Spoken captions need unique ordered caption_ids")
            require(all(key in by_id for key in ids), "caption_ids must name speech_caption instances")
            require(all(by_id[key].get("speech_id") == speech["id"] for key in ids), "Caption speech_id mismatch")
            text = "".join(by_id[key]["target_text"] for key in ids)
            require(normalized(text) == normalized(speech["target_text"]),
                    "Caption copy differs from final speech script: " + speech["id"])
            assigned.extend(ids)
        records.append({"id": speech["id"], "target_text": speech["target_text"],
                        "caption_policy": mode, "caption_ids": ids,
                        "caption_reason": speech.get("caption_reason", "")})
    require(len(assigned) == len(set(assigned)) and set(assigned) == set(by_id),
            "Every speech caption must be assigned exactly once")
    return {"version": 1, "required": True, "speech": records, "caption_ids": assigned}


def validate_spoken_copy(inventory, lines):
    """Bind TTS/mixer inputs to the same final script used by captions."""
    speeches = {item["id"]: item for item in inventory.get("speech_segments", [])}
    require(bool(lines) and len({line["id"] for line in lines}) == len(lines), "Duplicate/empty narration selection")
    for line in lines:
        require(line["id"] in speeches, "Narration speech id is missing from inventory")
        require(normalized(line["target_text"]) == normalized(speeches[line["id"]]["target_text"]),
                "Narration copy differs from final speech script: " + line["id"])


def units(item):
    fragments = item.get("display", {}).get("timed_fragments")
    if fragments is None:
        return [{"text": item["target_text"], "start": item["start"], "end": item["end"]}]
    return [{"start": start, "end": end, "text": text} for start, end, text in fragments if text]


def track(inventory):
    return [{"id": item["id"], "speech_id": item["speech_id"], "units": units(item)}
            for item in inventory.get("text_instances", []) if item.get("text_role") == "speech_caption"]


def checked_units(values, duration):
    require(isinstance(values, list) and bool(values), "Caption timing units are missing")
    previous = -1.0
    for unit in values:
        require(isinstance(unit.get("text"), str) and bool(normalized(unit["text"])), "Empty caption timing text")
        start = require_number(unit.get("start"), "caption.start", maximum=duration)
        end = require_number(unit.get("end"), "caption.end", maximum=duration + .01)
        require(end > start and start >= previous - .001, "Caption units overlap or are out of order")
        previous = end
    return values


def compile_alignment(run, inventory, alignment, duration):
    """Compile reviewed word/phrase boundaries on the final mixed-audio timeline."""
    # A new alignment is allowed to replace stale fragments after copy/voice edits.
    # The shared final script remains mandatory; only old timing is disregarded.
    spec = contract(inventory, check_timing=False)
    require(alignment.get("schema_version") == 1 and alignment.get("source_sha256") == inventory["source_sha256"],
            "Caption alignment source/schema mismatch")
    require(alignment.get("target_language") == read_json(run / "inputs/request.json")["target_language"],
            "Caption alignment language mismatch")
    require(alignment.get("status") == "reviewed" and alignment.get("reviewer") and alignment.get("method") in
            ("manual_listening", "forced_alignment_reviewed", "asr_reviewed"), "Caption alignment needs attributed audio review")
    require(alignment.get("timeline") == "final_mix_seconds", "Align to the final mix after trimming/atempo/offset")
    audio = alignment.get("audio", {})
    path = inside(run, audio.get("path", "missing"))
    require(path.is_file() and file_hash(path) == audio.get("sha256"), "Caption alignment audio missing or changed")
    require(inventory["audio"].get("strategy") == "replace" and audio["path"] == inventory["audio"].get("replacement_path"),
            "Pre-render caption alignment must use the selected replacement mix")
    rows = alignment.get("segments", [])
    needed = [row for row in spec["speech"] if row["caption_ids"]]
    require(len(rows) == len(needed) and {row.get("speech_id") for row in rows} == {row["id"] for row in needed},
            "Caption alignment speech coverage mismatch")
    texts = {item["id"]: item for item in inventory["text_instances"]}
    compiled = {}
    for speech in needed:
        row = next(row for row in rows if row["speech_id"] == speech["id"])
        words = checked_units(row.get("units"), duration)
        require(normalized("".join(word["text"] for word in words)) == normalized(speech["target_text"]),
                "Aligned audio text differs from final script: " + speech["id"])
        cursor = 0
        for key in speech["caption_ids"]:
            wanted, consumed, selected = normalized(texts[key]["target_text"]), "", []
            while cursor < len(words) and len(consumed) < len(wanted):
                selected.append(words[cursor])
                consumed += normalized(words[cursor]["text"])
                cursor += 1
            require(consumed == wanted, "Alignment units must split at each caption instance boundary: " + key)
            compiled[key] = [[word["start"], word["end"], word["text"]] for word in selected]
        require(cursor == len(words), "Unassigned aligned speech words")
    return compiled


def plan_assets(run, inventory, duration):
    contract(inventory)
    asset = inventory.get("caption_alignment")
    if not asset:
        return []
    path = inside(run, asset.get("path", "missing"))
    require(path.is_file() and file_hash(path) == asset.get("sha256"), "Caption alignment record missing or changed")
    alignment = read_json(path)
    compiled = compile_alignment(run, inventory, alignment, duration)
    for item in inventory["text_instances"]:
        if item["id"] in compiled:
            require(item.get("display", {}).get("timed_fragments") == compiled[item["id"]],
                    "Caption timing changed; apply reviewed alignment before planning")
    return [asset, alignment["audio"]]


@guarded
def apply_alignment(run, relative, apply=False):
    inventory = read_json(run / "analysis/inventory.json")
    path = inside(run, relative)
    compiled = compile_alignment(run, inventory, read_json(path), read_json(run / "analysis/media.json")["duration"])
    if apply:
        for item in inventory["text_instances"]:
            if item["id"] in compiled:
                fragments = compiled[item["id"]]
                item.setdefault("source_interval", [item["start"], item["end"]])
                # Keep the source erase window even if translated speech ends earlier.
                item["start"] = min(item["source_interval"][0], fragments[0][0])
                item["end"] = max(item["source_interval"][1], fragments[-1][1])
                item.setdefault("display", {})["timed_fragments"] = fragments
                item["display"]["reveal_seconds"] = 0
        inventory["caption_alignment"] = {"path": path.relative_to(run).as_posix(), "sha256": file_hash(path)}
        write_json(run / "analysis/inventory.json", inventory)
    return {"applied": apply, "compiled": compiled, "next": "Rebuild plan and language typography layers after applying"}


def render_instances(instances):
    """Expand speech fragments for compositors; ordinary titles retain source timing."""
    result = []
    for item in instances:
        if item.get("text_role") != "speech_caption":
            result.append(item)
            continue
        require(bool(item.get("display", {}).get("timed_fragments")), "Speech captions need actual-audio alignment before local typesetting")
        for unit in units(item):
            fragment = copy.deepcopy(item)
            fragment.update(unit)
            fragment["target_text"] = unit["text"]
            fragment["display"]["reveal_seconds"] = 0
            for point in fragment.get("trajectory", []):
                point.pop("target_text", None)
            result.append(fragment)
    return result


def shift_instances(instances, offset, duration):
    """Move both caption and erase timelines into a segment without mutating inputs."""
    result = copy.deepcopy(instances)
    for item in result:
        item["start"], item["end"] = max(0, item["start"]-offset), min(duration, item["end"]-offset)
        if "source_interval" in item:
            item["source_interval"] = [max(0, item["source_interval"][0]-offset), min(duration, item["source_interval"][1]-offset)]
        if item.get("text_role") == "speech_caption":
            item["display"]["timed_fragments"] = [[start-offset, end-offset, text]
                                                  for start, end, text in item["display"]["timed_fragments"]]
    return result


def review_template(run, candidate, inventory, audio_asset):
    return {"schema_version": 1, "video_sha256": candidate["sha256"], "plan_id": candidate["plan_id"],
            "source_sha256": inventory["source_sha256"], "inventory_sha256": file_hash(run / "analysis/inventory.json"),
            "track_sha256": object_hash(track(inventory)), "audio": audio_asset,
            "reviewer": "", "method": "", "decision": "pending", "evidence": [],
            "instances": [{**item, "planned_units": item["units"], "audio_units": [], "visual_units": [],
                           "decision": "pending", "method": "", "evidence": []}
                          for item in track(inventory)],
            "limitation": "Planned units are instructions, not observations. Review actual WAV and caption boundary frames/full playback."}


def evaluate(run, candidate, inventory, captured, policy, plan=None):
    """Hard gate: explicit classification, exact copy, measured AV timing, hashes."""
    failures, metrics = [], []
    if inventory.get("audio", {}).get("has_speech") is None:
        return {"decision": "revise", "failures": ["caption_speech_presence_unverified"], "metrics": []}
    try:
        spec = contract(inventory)
    except WorkflowError as exc:
        return {"decision": "revise", "failures": ["caption_contract:" + str(exc)], "metrics": []}
    if not spec["required"]:
        return {"decision": "not_applicable", "failures": [], "metrics": []}
    for name in ("max_start_error_seconds", "max_end_error_seconds", "max_visual_plan_error_seconds"):
        require_number(policy.get(name), "caption_sync." + name, maximum=.5)
    if plan is not None and plan.get("caption_contract") != spec:
        failures.append("caption_contract_missing_or_stale")
    record = run / "review" / candidate["sha256"][:12] / "caption-sync.json"
    if not record.exists():
        return {"decision": "revise", "failures": failures + ["caption_sync_review_missing"], "metrics": []}
    report = read_json(record)
    expected = {"schema_version": 1, "video_sha256": candidate["sha256"], "plan_id": candidate["plan_id"],
                "source_sha256": inventory["source_sha256"], "inventory_sha256": file_hash(run / "analysis/inventory.json"),
                "track_sha256": object_hash(track(inventory))}
    if any(report.get(key) != value for key, value in expected.items()):
        failures.append("caption_sync_binding_mismatch")
    files = captured.get("files", {}) if captured.get("video_sha256") == candidate["sha256"] else {}

    def evidence_ok(paths):
        return isinstance(paths, list) and bool(paths) and all(
            path in files and inside(run, path).is_file() and file_hash(inside(run, path)) == files[path] for path in paths)

    audio = report.get("audio", {})
    audio_path = audio.get("path", "")
    if not (audio_path.endswith("/audio.wav") and evidence_ok([audio_path]) and files.get(audio_path) == audio.get("sha256")):
        failures.append("caption_sync_actual_audio_missing_or_changed")

    def av_evidence(paths):
        return evidence_ok(paths) and audio_path in paths and any(path.lower().endswith((".jpg", ".png")) for path in paths)

    if report.get("decision") != "pass" or not report.get("reviewer") or not report.get("method") or not av_evidence(report.get("evidence")):
        failures.append("caption_sync_unverified")
    rows = report.get("instances", [])
    wanted = track(inventory)
    if not isinstance(rows, list) or len(rows) != len(wanted) or {row.get("id") for row in rows} != {row["id"] for row in wanted}:
        return {"decision": "revise", "failures": failures + ["caption_sync_instance_coverage"], "metrics": []}
    duration = read_json(run / "analysis/media.json")["duration"]
    for item in wanted:
        row = next(row for row in rows if row["id"] == item["id"])
        key = item["id"]
        if row.get("speech_id") != item["speech_id"] or row.get("decision") != "pass" or not row.get("method") or not av_evidence(row.get("evidence")):
            failures.append("caption_sync_instance_unverified:" + key)
        if not any("/caption-" + key + "-" in path for path in row.get("evidence", [])):
            failures.append("caption_boundary_evidence_missing:" + key)
        try:
            planned = checked_units(item["units"], duration)
            observed_audio = checked_units(row.get("audio_units"), duration)
            observed_visual = checked_units(row.get("visual_units"), duration)
            require(len(planned) == len(observed_audio) == len(observed_visual), "Caption unit coverage mismatch")
            for index, (target, spoken, visible) in enumerate(zip(planned, observed_audio, observed_visual)):
                require(normalized(target["text"]) == normalized(spoken["text"]) == normalized(visible["text"]),
                        "Spoken/visible caption copy differs")
                start_error, end_error = abs(visible["start"] - spoken["start"]), abs(visible["end"] - spoken["end"])
                metrics.append({"id": key, "unit": index, "start_error_seconds": round(start_error, 4),
                                "end_error_seconds": round(end_error, 4)})
                if start_error > policy["max_start_error_seconds"] + .000001 or end_error > policy["max_end_error_seconds"] + .000001:
                    failures.append(f"caption_audio_out_of_sync:{key}:{index}")
                if max(abs(visible[edge] - target[edge]) for edge in ("start", "end")) > policy["max_visual_plan_error_seconds"] + .000001:
                    failures.append(f"caption_render_timing_mismatch:{key}:{index}")
        except (WorkflowError, KeyError, TypeError, ValueError) as exc:
            failures.append("caption_sync_units:" + key + ":" + str(exc))
    return {"decision": "pass" if not failures else "revise", "failures": failures,
            "metrics": metrics, "review_sha256": file_hash(record),
            "proof_boundary": "Bound, attributed AV observations plus deterministic copy/timing checks; no automatic listening/OCR or lip-sync claim"}
