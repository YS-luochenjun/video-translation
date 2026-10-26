"""Verify and composite a source-bound transparent typography video layer."""
from .common import file_hash, inside, object_hash, read_json, require
from . import media


def instance_bindings(items):
    keys = ('id', 'target_text', 'start', 'end', 'bbox', 'trajectory', 'display')
    return {item['id']: object_hash({key: item.get(key) for key in keys}) for item in items
            if item.get('display', {}).get('typography_layer')}


def verify(run, asset, source_sha256, target_language, items):
    marked = {item['id']: item['target_text'] for item in items
              if item.get('display', {}).get('typography_layer')}
    require(bool(asset) == bool(marked), 'Surface typography needs both its layer and marked text instances')
    if not asset:
        return None
    from .layout import overlaps
    for item in items:
        if not item.get('display', {}).get('typography_layer'):
            continue
        for point in item.get('trajectory', []):
            for protected in point.get('protected_regions', []):
                require(not overlaps(point['bbox'], protected), 'Surface glyphs overlap a protected icon region')
    layer = inside(run, asset['path'])
    record_path = inside(run, asset['record'])
    require(layer.is_file() and file_hash(layer) == asset['sha256'], 'Surface typography video changed')
    require(record_path.is_file() and file_hash(record_path) == asset['record_sha256'], 'Surface typography provenance changed')
    record = read_json(record_path)
    require(record.get('source_sha256') == source_sha256 and record.get('target_language') == target_language,
            'Surface typography belongs to another source or language')
    require(record.get('texts') == marked, 'Surface typography copy is stale; rebuild the layer')
    if any(item.get('text_role') == 'speech_caption' and item.get('display', {}).get('typography_layer') for item in items):
        require('instance_bindings' in record, 'Speech-caption surface layer needs timing/geometry bindings')
    if 'instance_bindings' in record:
        require(record['instance_bindings'] == instance_bindings(items), 'Surface typography geometry or style is stale')
    require(record.get('output') == {'path': asset['path'], 'sha256': asset['sha256']}, 'Surface layer output binding mismatch')
    require(record.get('alpha_channel') is True and bool(record.get('inputs')), 'Surface layer needs alpha and input evidence')
    for item in record['inputs']:
        path = inside(run, item['path'])
        require(path.is_file() and file_hash(path) == item['sha256'], 'Surface typography input changed')
    return layer


def composite(source, layer, duration, directory):
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / 'visual.mp4'
    meta = media.probe(layer)
    source_meta = media.probe(source)
    require((meta['width'], meta['height']) == (source_meta['width'], source_meta['height']),
            'Surface layer dimensions differ from the visual master')
    stream = next(s for s in meta['raw']['streams'] if s['codec_type'] == 'video')
    require(stream.get('pix_fmt') in ('argb', 'rgba', 'bgra', 'yuva444p', 'yuva420p', 'gbrap'),
            'Surface typography video has no alpha pixel format')
    require(abs(meta['duration'] - duration) <= .15, 'Surface layer timeline differs')
    media.ffmpeg(['-i', source, '-i', layer, '-filter_complex',
                  '[0:v][1:v]overlay=0:0:format=auto:shortest=1[out]', '-map', '[out]',
                  '-t', duration, '-an', '-r', '30', '-c:v', 'libx264', '-crf', '16',
                  '-pix_fmt', 'yuv420p', output])
    return output
