from __future__ import annotations

import re

from .common import WorkflowError, file_hash, inside, require, require_number


def validate_inventory(inventory, run, meta):
    require(inventory.get("schema_version") == 1, "Unsupported inventory schema")
    for kind in ("visual", "speech", "timeline"):
        coverage = inventory.get("coverage", {}).get(kind, {})
        delegated_speech = (kind == "speech" and inventory.get("audio", {}).get("strategy") == "model"
                            and inventory.get("audio", {}).get("has_speech") is None)
        require(coverage.get("status") == "reviewed" or delegated_speech and coverage.get("status") == "pending",
                f"{kind} coverage needs agent review")
        require(bool(coverage.get("method")) and bool(coverage.get("evidence")),
                f"{kind} review requires method and evidence")
        for path in coverage["evidence"]:
            require(inside(run, path).is_file(), f"Missing coverage evidence: {path}")
    shots = inventory.get("shots", [])
    require(bool(shots), "No shots")
    previous, ids = 0.0, set()
    for shot in shots:
        require(bool(re.fullmatch(r"s[0-9]{3}", shot.get("id", ""))), "Invalid shot id")
        require(shot["id"] not in ids, "Duplicate shot id")
        ids.add(shot["id"])
        start = require_number(shot["start"], "shot.start", maximum=meta["duration"])
        end = require_number(shot["end"], "shot.end", maximum=meta["duration"] + 0.01)
        require(abs(start - previous) < 0.025 and end > start, "Shots must cover time continuously without overlap")
        require(end - start <= 30.01, "Split shots longer than 30 seconds before planning")
        require(shot.get("model_text_mode", "replace") in ("replace", "erase_then_overlay"),
                "Unknown model text mode")
        require(shot.get("video_model", "wan/2-7-videoedit") in
                ("kling-3.0-omni/transformation", "wan/2-6-flash-video-to-video", "wan/2-7-videoedit", "bytedance/seedance-2-fast"), "Unknown video model")
        if "reference_image" in shot:
            asset = shot["reference_image"]
            path = inside(run, asset.get("path", "missing"))
            require(path.is_file() and file_hash(path) == asset.get("sha256"), "Reference image missing or changed")
        require(shot.get("veo_tier", "veo3_fast") in ("veo3_fast", "veo3_lite"), "Unknown Veo tier")
        require(shot.get("veo_generation_type", "FIRST_AND_LAST_FRAMES_2_VIDEO") in
                ("FIRST_AND_LAST_FRAMES_2_VIDEO", "REFERENCE_2_VIDEO"), "Unknown Veo generation mode")
        if "reference_frames" in shot:
            frames = shot["reference_frames"]
            require(1 <= len(frames) <= 3, "Veo reference mode needs 1-3 images")
            require(shot.get("veo_generation_type") == "REFERENCE_2_VIDEO" and abs(end-start-8) < 0.025,
                    "Veo reference images need explicit reference mode and 8-second output")
            for asset in frames:
                path = inside(run, asset.get("path", "missing"))
                require(path.is_file() and file_hash(path) == asset.get("sha256"), "Reference frame missing or changed")
        require(bool(shot.get("description")), f"Describe {shot['id']}")
        require(inside(run, shot["keyframe"]).is_file(), "Missing shot keyframe")
        for region in shot.get("preserve_regions", []):
            require(len(region) == 4, "Preserved region is [x,y,width,height]")
            x, y, width, height = [require_number(value, "preserved region") for value in region]
            require(width > 0 and height > 0 and x + width <= meta["width"] and y + height <= meta["height"],
                    "Preserved region exceeds source frame")
        if "reference_composite" in shot:
            config = shot["reference_composite"]
            for kind in ("day", "night"):
                asset = config.get(kind, {})
                path = inside(run, asset.get("path", "missing"))
                require(path.is_file() and file_hash(path) == asset.get("sha256"), "Reference plate missing or changed")
            require(bool(config.get("method")), "Reference composition requires provenance and limitations")
            previous_time = -1
            for knot in config.get("blend_knots", []):
                require(len(knot) == 2, "Blend knots are [absolute source time, weight]")
                timestamp = require_number(knot[0], "blend time", maximum=meta["duration"]+0.01)
                require(timestamp > previous_time, "Blend knots must increase")
                require_number(knot[1], "blend weight", maximum=1)
                previous_time = timestamp
            require(len(config.get("blend_knots", [])) >= 2, "Reference composition needs a blend curve")
            require(bool(config.get("erase_regions")), "Reference composition needs explicit regions")
            for region in config["erase_regions"]:
                require(len(region) == 4, "Erase region is [x,y,width,height]")
                x, y, w, h = [require_number(v, "erase region") for v in region]
                require(w > 0 and h > 0 and x+w <= meta["width"] and y+h <= meta["height"], "Erase region exceeds frame")
        previous = end
    require(abs(previous - meta["duration"]) < 0.025, "Shots do not cover full source duration")
    text_ids = set()
    for item in inventory.get("text_instances", []):
        require(bool(re.fullmatch(r"t[0-9]{3}", item.get("id", ""))), "Invalid text instance id")
        require(item["id"] not in text_ids, "Duplicate text id")
        text_ids.add(item["id"])
        start = require_number(item["start"], "text.start", maximum=meta["duration"])
        end = require_number(item["end"], "text.end", maximum=meta["duration"] + 0.01)
        require(end > start, "Text interval is empty")
        require(item.get("source_text") and item.get("target_text") and item.get("reason"),
                "Each text needs source, target, and decision reason")
        require(item.get("action") in ("solid_overlay", "model_edit", "regenerate", "reference_plate", "preserve"), "Unknown text action")
        bbox = item.get("bbox", [])
        require(len(bbox) == 4, "bbox must be pixel [x,y,width,height]")
        x, y, width, height = [require_number(v, "bbox") for v in bbox]
        require(width > 0 and height > 0 and x + width <= meta["width"] and y + height <= meta["height"],
                "bbox exceeds frame")
        if item["action"] == "solid_overlay":
            from .layout import validate as validate_layout
            from .captions import render_instances
            measured = render_instances([item]) if item.get("text_role") == "speech_caption" and item.get("display", {}).get("timed_fragments") else [item]
            for fragment in measured:
                validate_layout(fragment, meta)
            require(item.get("background_is_static") is True, "Solid overlay requires a reviewed static background")
            require_number(item.get("font_size", 24), "font_size", minimum=8, maximum=meta["height"])
        for point in item.get("trajectory", []):
            require_number(point["time"], "trajectory.time", minimum=start, maximum=end)
            require(len(point["bbox"]) == 4, "Trajectory bounding box must have four values")
        if "source_interval" in item:
            require(len(item["source_interval"]) == 2, "source_interval needs start/end")
            first, last = [require_number(value, "source_interval", maximum=meta["duration"]+.01) for value in item["source_interval"]]
            require(item["start"] <= first < last <= item["end"], "Source erase interval must remain inside instance bounds")
        display = item.get("display", {})
        for key, default, minimum in (("font_size", 64, 8), ("line_height", 88, 8),
                                     ("outline", 5, 0), ("reveal_seconds", 0, 0)):
            require_number(display.get(key, default), "display." + key, minimum=minimum,
                           maximum=meta["height"] if key != "reveal_seconds" else end-start)
        require(isinstance(display.get("pill", False), bool), "display.pill must be boolean")
        require(bool(item.get("evidence")), "Text instance needs frame evidence")
        for path in item["evidence"]:
            require(inside(run, path).is_file(), "Missing text evidence")
    audio = inventory.get("audio", {})
    require(isinstance(audio.get("has_speech"), bool) or audio.get("has_speech") is None and audio.get("strategy") == "model",
            "Speech presence is unknown; delegate explicitly to model audio or obtain a transcript")
    require(audio.get("strategy") in ("preserve", "replace", "mute", "model"), "Decide audio strategy")
    require(bool(audio.get("reason")), "Audio decision needs a reason")
    require(not audio.get("has_speech") or meta["has_audio"], "Speech cannot be inferred from a source without an audio stream")
    if audio["strategy"] == "mute" and meta["has_audio"]:
        require(audio.get("mute_authorized") is True, "Muting source audio requires explicit authorization")
    if audio["strategy"] == "model" and not meta["has_audio"]:
        require(bool(audio.get("generation_brief")) and audio.get("generation_authorized") is True,
                "A source without audio needs explicit authorization before generating a new soundtrack")
    speeches = inventory.get("speech_segments", [])
    require(not speeches or audio.get('has_speech') is not False, 'Speech inventory contradicts speech presence')
    if audio["has_speech"]:
        require(bool(speeches), "Speech needs timestamped source and translation")
        require(audio["strategy"] in ("replace", "model"), "Foreign speech requires a replacement track or explicit model dialogue translation")
    if audio["strategy"] == "replace":
        replacement = inside(run, audio.get("replacement_path", "missing"))
        require(replacement.is_file(), "Replacement audio is missing; import reviewed dubbing/TTS first")
    speech_ids = set()
    for item in speeches:
        require(bool(re.fullmatch(r"a[0-9]{3}", item.get("id", ""))) and item["id"] not in speech_ids,
                "Invalid/duplicate speech id")
        speech_ids.add(item["id"])
        start = require_number(item["start"], "speech.start", maximum=meta["duration"])
        end = require_number(item["end"], "speech.end", maximum=meta["duration"] + 0.01)
        require(end > start and item.get("source_text") and item.get("target_text"), "Incomplete speech segment")
        require(bool(item.get("evidence")), "Speech needs transcript/audio evidence")
        for path in item["evidence"]:
            require(inside(run, path).is_file(), "Missing speech evidence")
    from .captions import contract
    contract(inventory)
    return inventory

