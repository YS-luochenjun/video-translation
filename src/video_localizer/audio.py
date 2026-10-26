from __future__ import annotations

import array
import json
import math
import subprocess
import sys
from pathlib import Path

from . import media
from .common import file_hash, require, write_json

SAMPLE_RATE = 16000


def decode(path):
    """Decode the complete mono waveform for measurement, not speech recognition."""
    result = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-map", "0:a:0",
                             "-ac", "1", "-ar", str(SAMPLE_RATE),
                             "-f", "s16le", "pipe:1"], capture_output=True, timeout=90)
    require(result.returncode == 0, "Audio decoding failed")
    require(len(result.stdout) % 2 == 0, 'Incomplete decoded PCM sample')
    samples = array.array("h")
    samples.frombytes(result.stdout)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples


def level(value):
    return round(20 * math.log10(max(value, 1 / 32768)), 2)


def inspect(path):
    raw = json.loads(media.command(["ffprobe", "-v", "error", "-show_streams", "-of", "json", path]).stdout)
    streams = [item for item in raw["streams"] if item["codec_type"] == "audio"]
    if not streams:
        return {"has_track": False, "audible_signal": False, "duration": 0, "windows": []}, array.array("h")
    samples = decode(path)
    require(bool(samples), "Audio stream is empty")
    peak = max(abs(value) for value in samples) / 32768
    rms = math.sqrt(sum(value * value for value in samples) / len(samples)) / 32768
    windows = []
    for start in range(0, len(samples), SAMPLE_RATE // 2):
        part = samples[start:start + SAMPLE_RATE // 2]
        energy = math.sqrt(sum(value * value for value in part) / len(part)) / 32768
        windows.append({"start": round(start / SAMPLE_RATE, 3),
                        "end": round((start + len(part)) / SAMPLE_RATE, 3), "rms_dbfs": level(energy)})
    silent = sum(item["end"] - item["start"] for item in windows if item["rms_dbfs"] < -60)
    duration = len(samples) / SAMPLE_RATE
    return {"has_track": True, "codec": streams[0].get("codec_name"),
            "channels": streams[0].get("channels"), "sample_rate": streams[0].get("sample_rate"),
            "duration": round(duration, 4), "measurement_scope": "complete_decoded_audio",
            "rms_dbfs": level(rms), "peak_dbfs": level(peak),
            "audible_signal": peak > 0.001 and rms > 0.0003,
            "silence_fraction": round(silent / duration, 4),
            "clipped_fraction": round(sum(abs(value) >= 32760 for value in samples) / len(samples), 6),
            "windows": windows}, samples


def waveform_match(source, result):
    """Check retained audio after lossy muxing; report timing as well as correlation."""
    # Decimation limits CPU cost. It is not a semantic comparison of a new soundtrack.
    step = 16
    left, right = source[::step], result[::step]
    best = {"correlation": -1.0, "offset_seconds": 0.0}
    for offset in sorted(range(-100, 101), key=abs):
        first = max(0, -offset)
        last = min(len(left), len(right) - offset)
        if last - first < 100:
            continue
        # Sample the full clip rather than only its opening.
        stride = max(1, (last - first) // 2500)
        pairs = [(left[i], right[i + offset]) for i in range(first, last, stride)]
        count = len(pairs)
        sx, sy = sum(x for x, _ in pairs), sum(y for _, y in pairs)
        xx = sum(x * x for x, _ in pairs) - sx * sx / count
        yy = sum(y * y for _, y in pairs) - sy * sy / count
        xy = sum(x * y for x, y in pairs) - sx * sy / count
        correlation = xy / math.sqrt(xx * yy) if xx > 0 and yy > 0 else 0
        if correlation > best["correlation"] + 0.001:
            best = {"correlation": round(correlation, 6), "offset_seconds": offset / 1000}
    return best


def evaluate(source_path, candidate_path, policy, duration):
    source, source_pcm = inspect(source_path)
    actual, actual_pcm = inspect(candidate_path)
    strategy = policy["strategy"]
    expect_audio = (source["has_track"] if strategy == "preserve" else strategy in ("replace", "model"))
    failures = []
    if actual["has_track"] != expect_audio:
        failures.append("audio_track_mismatch")
    if actual["has_track"]:
        if abs(actual["duration"] - duration) > 0.3:
            failures.append("audio_duration_mismatch")
        if (source["audible_signal"] or strategy in ("replace", "model")) and not actual["audible_signal"]:
            failures.append("audio_silent_or_near_silent")
        if actual["clipped_fraction"] > max(0.005, source.get("clipped_fraction", 0) + 0.003):
            failures.append("audio_clipping")
        if source["audible_signal"] and actual["rms_dbfs"] < source["rms_dbfs"] - 24:
            failures.append("audio_unexpected_level_drop")
    match = None
    if strategy == "preserve" and source["audible_signal"] and actual["audible_signal"]:
        if source.get("channels") != actual.get("channels"):
            failures.append("audio_channels_changed")
        match = waveform_match(source_pcm, actual_pcm)
        if match["correlation"] < 0.97:
            failures.append("source_music_or_effects_changed")
        if abs(match["offset_seconds"]) > 0.04:
            failures.append("audio_sync_shift")
        for before, after in zip(source["windows"], actual["windows"]):
            if before["rms_dbfs"] > -50 and after["rms_dbfs"] < -65:
                failures.append("audio_dropout")
                break
    return {"schema_version": 1, "source_sha256": file_hash(source_path),
            "video_sha256": file_hash(candidate_path), "strategy": strategy,
            "source": source, "candidate": actual, "waveform_match": match,
            "failures": list(dict.fromkeys(failures)),
            "proof_boundary": "Signal, duration and retained-waveform checks; not listening, ASR, dialogue translation or lip-sync proof"}


def prompt(policy, language, source_has_audio, speeches, start, end):
    lines = ["AUDIO REQUIREMENTS: Preserve the source background music and sound effects, their timing and relative levels.",
             f"If intelligible dialogue or narration is present, translate it into natural {language} speech; "
             "keep speaker roles, intent, emotion and timing. Replace foreign dialogue and narration rather than layering both languages.",
             "Keep music and nonverbal effects as music/effects. Do not turn captions or music into spoken narration."]
    if not source_has_audio:
        lines.append("The supplied source has NO audio stream; original music/dialogue cannot be recovered from it.")
        if policy["strategy"] != "model":
            lines.append("Keep this source silent; do not invent voices, music or effects.")
    if policy["strategy"] == "preserve":
        lines.append("Delivery uses the original source soundtrack; retain it in your result too. No dialogue has been identified.")
    elif policy["strategy"] == "replace":
        lines.append("A reviewed complete translated mix will be muxed at delivery; still preserve source music/effects in this edit.")
    elif policy["strategy"] == "model":
        lines.append("Your returned audio is required for delivery. Return an audible synchronized soundtrack; do not mute it.")
        if policy.get("generation_brief"):
            lines.append("User-authorized new soundtrack: " + policy["generation_brief"])
        if policy.get("has_speech") is None:
            lines.append("The controlling agent cannot verify the speech yet. Analyze the supplied audio yourself and translate all intelligible dialogue and narration; uncertainty is not permission to discard it.")
    else:
        lines.append("Explicitly authorized silent delivery; no audio is required in this candidate.")
    for item in speeches:
        if item["start"] < end and item["end"] > start:
            lines.append(f"Speech ({item.get('speech_role', 'dialogue_or_narration')}) {item['id']} at {max(item['start'], start)-start:.2f}-"
                         f"{min(item['end'], end)-start:.2f}s: {item['source_text']!r} -> {item['target_text']!r}.")
    return lines


def extract_track(source, output, start, duration):
    source_info, _ = inspect(source)
    require(source_info["has_track"], "Required model/source audio stream is missing; do not substitute silence or foreign dialogue")
    available = source_info["duration"] - start
    require(available >= duration - 0.3, "Selected audio does not cover its segment")
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    media.ffmpeg(["-ss", start, "-i", source, "-t", duration, "-vn", "-map", "0:a:0",
                  "-af", f"apad=whole_dur={duration}", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", output])
    measured, _ = inspect(output)
    require(abs(measured["duration"] - duration) < 0.005, "Selected audio does not cover its segment")
    write_json(Path(output).with_suffix(".json"), {"source_sha256": file_hash(source), "start": start,
               "source_audio_duration": source_info["duration"], "requested_duration": duration,
               "tail_padding_seconds": round(max(0, duration - available), 4),
               "method": "Pad only a sub-0.3s encoder/model tail to retain segment boundaries; no tempo change or replacement content",
               "limitation": "Padding does not recover missing music/effects; output review must assess any audible seam"})
    return Path(output)


def concatenate(tracks, output):
    listing = Path(output).parent / "audio-concat.txt"
    for path in tracks:
        require("'" not in str(path) and "\n" not in str(path), "Unsupported audio concat path")
    listing.write_text("\n".join(f"file '{Path(path).resolve().as_posix()}'" for path in tracks), encoding="utf-8")
    media.ffmpeg(["-f", "concat", "-safe", "0", "-i", listing, "-c:a", "pcm_s16le", output])
    return Path(output)
