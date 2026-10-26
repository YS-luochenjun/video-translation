"""Small reusable native-timeline composition primitives.

Do not stretch short model video to fill source time. Protected pixels come from
the corresponding source frame, never a frozen donor from another timestamp.
"""
from pathlib import Path
import subprocess
import wave

from .common import CODE_ROOT, file_hash, require, write_json


def preserve_regions(frame, source_frame, boxes):
    require(frame.shape == source_frame.shape, 'Source/output frame dimensions differ')
    height, width = frame.shape[:2]
    for x1, y1, x2, y2 in boxes:
        require(0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height, 'Protected region outside frame')
        frame[y1:y2, x1:x2] = source_frame[y1:y2, x1:x2]
    return frame


def require_native_timing(source_frames, output_frames, source_fps, output_fps):
    require(source_frames == output_frames and abs(source_fps - output_fps) < .001,
            'Native frame count/timing changed; retimed or blended substitutions need a different reviewed route')


def audit_regions(source, output, regions):
    """Compare sequential, same-index decoded regions; encoder loss is explicit."""
    import sys
    sys.path.insert(0, str(CODE_ROOT / '.runtime/deps/vision'))
    import cv2
    import numpy as np
    a, b = cv2.VideoCapture(str(source)), cv2.VideoCapture(str(output))
    counts = [int(c.get(cv2.CAP_PROP_FRAME_COUNT)) for c in (a, b)]
    fps = [c.get(cv2.CAP_PROP_FPS) for c in (a, b)]
    require_native_timing(counts[0], counts[1], fps[0], fps[1])
    rows = {row['id']: [] for row in regions}
    try:
        for n in range(counts[0]):
            ok1, before = a.read(); ok2, after = b.read()
            require(ok1 and ok2, 'Actual sequential decode ended early')
            for row in regions:
                if row['start_frame'] <= n < row['end_frame']:
                    x1, y1, x2, y2 = row['box']
                    delta = np.abs(before[y1:y2,x1:x2].astype(float) - after[y1:y2,x1:x2].astype(float))
                    require(delta.size > 0, 'Audit region is empty')
                    rows[row['id']].append(float(delta.mean()))
    finally:
        a.release(); b.release()
    result = []
    for row in regions:
        values = rows[row['id']]
        require(len(values) == row['end_frame'] - row['start_frame'], 'Audit did not cover the entire declared region interval')
        result.append({**row, 'frames': len(values), 'mean_mae': sum(values)/len(values),
                       'max_mae': max(values), 'decision': 'pass' if max(values) <= row['max_mae'] else 'fail'})
    return {'source_sha256':file_hash(source), 'video_sha256':file_hash(output),
            'frame_counts':counts, 'fps':fps, 'regions':result,
            'boundary':'Actual same-frame pixel comparison outside translated areas. Lossy encoding tolerance is not a semantic or independent review.'}


def replace_speech_window(run, mixed_path, accompaniment, voice, start, end, offset, rate=44100):
    import numpy as np
    ffmpeg = str(CODE_ROOT / '.runtime/ffmpeg/bin/ffmpeg.exe')
    def decode(path):
        raw = subprocess.run([ffmpeg, '-v', 'error', '-i', str(path), '-f', 'f32le',
                              '-ar', str(rate), '-ac', '2', 'pipe:1'], capture_output=True, check=True).stdout
        return np.frombuffer(raw, '<f4').reshape(-1, 2).copy()
    mixed, music, spoken = decode(mixed_path), decode(accompaniment), decode(voice)
    require(0 <= start <= offset < end <= len(mixed) / rate + .01, 'Speech window outside mix')
    block = rate // 100
    rms = np.array([np.sqrt(np.mean(spoken[i:i+block] ** 2)) for i in range(0, len(spoken), block)])
    active = np.flatnonzero(rms > max(.006, float(rms.max()) * .035))
    require(len(active) > 0, 'Target speech is silent')
    first, last = max(0, active[0]*block-1323), min(len(spoken), (active[-1]+1)*block+2205)
    spoken = spoken[first:last]
    begin, stop, voice_start = int(start*rate), min(len(mixed), int(end*rate)), int(offset*rate)
    voice_stop = voice_start + len(spoken)
    require(voice_stop <= stop, 'Target speech exceeds available source interval; do not truncate words')
    require(len(music) >= stop, 'Music stem does not cover the replacement window')
    mixed[begin:stop] = music[begin:stop]
    spoken *= min(2.5, .13/max(float(np.sqrt(np.mean(spoken**2))), .001))
    mixed[voice_start:voice_stop] *= .75
    mixed[voice_start:voice_stop] += spoken
    peak = float(np.max(np.abs(mixed[begin:stop])))
    if peak > .985: mixed[begin:stop] *= .985/peak
    out = Path(run)/'outputs/native-mix.wav'
    with wave.open(str(out),'wb') as stream:
        stream.setnchannels(2);stream.setsampwidth(2);stream.setframerate(rate)
        stream.writeframes((np.clip(mixed,-1,1)*32767).astype('<i2').tobytes())
    record = {'source_speech_replacement_interval':[start,end], 'voice_interval':[offset,voice_stop/rate],
              'voice_trim_samples':[int(first),int(last)], 'peak_before_limit':peak,
              'assets':[{'path':Path(p).relative_to(run).as_posix(),'sha256':file_hash(p)}
                        for p in (mixed_path, accompaniment, voice)],
              'output':{'path':out.relative_to(run).as_posix(),'sha256':file_hash(out)}}
    write_json(Path(run)/'outputs/tail-audio-selection.json',record)
    return out, record
