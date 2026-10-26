"""Exact-input OCR caching and compact candidates, never a visual acceptance gate."""
import copy
import hashlib

from .common import file_hash, object_hash, read_json, require, write_json


def signature(source, step, crop_top, model_files):
    return {'version': 2, 'source_sha256': file_hash(source), 'step': step, 'crop_top': crop_top,
            'models': {p.name: file_hash(p) for p in sorted(model_files)}}


def cached(path, expected):
    if not path.exists():
        return None
    record = read_json(path)
    require(record.get('sha256') == object_hash(record['data']), 'OCR cache corrupted; inspect before rerunning with --force')
    data = record['data']
    if data.get('signature') == expected and data.get('complete') is True:
        return data
    return None


def store(path, data):
    require(data.get('complete') is True, 'Partial OCR cannot become a reusable cache')
    write_json(path, {'sha256': object_hash(data), 'data': data})


def infer(image, engine, seen, crop_top):
    """Reuse only byte-identical sampled pixels, not approximate frame similarity."""
    key = hashlib.sha256(image.tobytes()).hexdigest()
    if key in seen:
        return copy.deepcopy(seen[key]), True
    result, _ = engine(image)
    observations = [{'text': text, 'confidence': round(float(confidence), 4),
        'polygon': [[round(float(x), 1), round(float(y)+crop_top, 1)] for x, y in polygon]}
        for polygon, text, confidence in result or []]
    seen[key] = observations
    return copy.deepcopy(observations), False


def summary(data):
    # Exact text/geometry grouping preserves moving text as separate candidates.
    # Raw frame observations remain available for temporal and motion inspection.
    tracks, previous = [], {}
    for frame in data['frames']:
        current = {}
        duplicates = {}
        for observation in frame['observations']:
            base = object_hash({'text': observation['text'], 'polygon': observation['polygon']})
            occurrence = duplicates.get(base, 0)
            duplicates[base] = occurrence + 1
            key = (base, occurrence)
            if key in previous:
                track = tracks[previous[key]]
                track['last_observed'] = frame['time']
                track['samples'] += 1
                track['minimum_confidence'] = min(track['minimum_confidence'], observation['confidence'])
                current[key] = previous[key]
            else:
                current[key] = len(tracks)
                tracks.append({'text': observation['text'], 'polygon': observation['polygon'],
                               'first_observed': frame['time'], 'last_observed': frame['time'],
                               'samples': 1, 'minimum_confidence': observation['confidence']})
        previous = current
    return {'source_sha256': data['source_sha256'], 'complete': data.get('complete', False),
            'sampled_frames': len(data['frames']), 'candidate_tracks': tracks,
            'low_confidence_tracks': sum(t['minimum_confidence'] < .85 for t in tracks),
            'scope': 'Observed sample times, not exact text onset/offset. Empty OCR is not proof of clean pixels; moving/artistic/occluded text and boundaries still need review.'}
