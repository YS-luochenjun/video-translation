"""Verified local segment reuse across plan revisions; model-result audio is excluded."""
from pathlib import Path

from .common import CODE_ROOT, file_hash, inside, object_hash, read_json, require, write_json
from . import media


def implementation_signature():
    # Hash the actual rendering/orchestration modules, not cleanup, reports or
    # evidence viewers. Update this list when rendering gains a new dependency.
    names = ('audio', 'captions', 'common', 'compositor', 'layout', 'media',
             'prepared', 'production', 'render_cache', 'runtime', 'surface', 'workflow', 'typography', 'processes', 'font_environment', 'fonts')
    try:
        from PIL import __version__ as pillow_version
    except ImportError:
        pillow_version = None
    from .typography import code_identity
    from .fonts import policy as font_policy
    return {'version': 2, 'pillow': pillow_version, 'typography':code_identity(),
            'font_policy': object_hash(font_policy(CODE_ROOT)),
            'modules': {name: file_hash(CODE_ROOT / 'src/video_localizer' / (name + '.py')) for name in names}}


def signature(run, plan, segment, inventory, meta, font_hash_cache=None):
    if segment['route'] not in ('local_overlay', 'reference_composite', 'prepared_video'):
        return None  # Preserve the existing paid-result and model-audio selection path.
    items = [item for item in inventory['text_instances'] if item['id'] in segment['instance_ids'] or
             (item['start'] < segment['end'] and item['end'] > segment['start']) or
             (item.get('source_interval', [item['start'], item['end']])[0] < segment['end'] and
              item.get('source_interval', [item['start'], item['end']])[1] > segment['start'])]
    from .typography import selected
    if any(selected(item) for item in items):
        return None  # Re-attempt optional runtime; a prior fallback is never silently cached.
    from .font_environment import fingerprint
    fonts = fingerprint(Path(run).parent.parent, font_hash_cache)
    if not fonts:
        return None
    visual_segment = {k: v for k, v in segment.items() if k not in ('prompt', 'reason')}
    return object_hash({'version': 2, 'source_sha256': plan['source_sha256'], 'segment': visual_segment,
        'items': items, 'video': {key: meta.get(key) for key in ('width', 'height', 'fps', 'duration', 'target_language')},
        'profile': plan.get('profile_sha256'),
        'fonts': fonts,
        'code': implementation_signature(),
        'encoder': media.command(['ffmpeg', '-version']).stdout})


def restore(run, key):
    path = run / 'outputs/render-cache' / (key + '.json')
    if not path.exists():
        return None
    record = read_json(path)
    require(record.get('signature') == key, 'Segment cache identity changed')
    asset = inside(run, record['path'])
    if not asset.exists():
        return None  # Missing disposable intermediates can be rebuilt.
    require(file_hash(asset) == record['sha256'], 'Segment cache bytes changed; preserve and inspect them')
    return asset


def save(run, key, path):
    write_json(run / 'outputs/render-cache' / (key + '.json'),
               {'signature': key, 'path': path.relative_to(run).as_posix(), 'sha256': file_hash(path),
                'scope': 'Silent visual segment only, never an approval or completed final video'})
