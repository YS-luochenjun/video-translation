"""Verified local segment reuse across plan revisions; model-result audio is excluded."""
import os
from pathlib import Path

from .common import CODE_ROOT, file_hash, inside, object_hash, read_json, require, write_json
from . import media


def implementation_signature():
    # Hash the actual rendering/orchestration modules, not cleanup, reports or
    # evidence viewers. Update this list when rendering gains a new dependency.
    names = ('audio', 'captions', 'common', 'compositor', 'layout', 'media',
             'prepared', 'production', 'render_cache', 'runtime', 'surface', 'workflow')
    try:
        from PIL import __version__ as pillow_version
    except ImportError:
        pillow_version = None
    return {'version': 1, 'pillow': pillow_version,
            'modules': {name: file_hash(CODE_ROOT / 'src/video_localizer' / (name + '.py')) for name in names}}


def signature(run, plan, segment, inventory, meta):
    if segment['route'] not in ('local_overlay', 'reference_composite', 'prepared_video'):
        return None  # Preserve the existing paid-result and model-audio selection path.
    items = [item for item in inventory['text_instances'] if item['id'] in segment['instance_ids'] or
             (item['start'] < segment['end'] and item['end'] > segment['start']) or
             (item.get('source_interval', [item['start'], item['end']])[0] < segment['end'] and
              item.get('source_interval', [item['start'], item['end']])[1] > segment['start'])]
    # Hash installed renderer fonts as well as project assets. Missing font environments
    # cannot safely reuse this cache (libass may choose different fallback faces).
    font_directory = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    names = ('msyh.ttc', 'msyhbd.ttc', 'simsun.ttc', 'simkai.ttf', 'arial.ttf', 'arialbd.ttf',
             'YuGothM.ttc', 'YuGothB.ttc', 'malgun.ttf', 'malgunbd.ttf')
    fonts = [font_directory / name for name in names if (font_directory / name).is_file()]
    if not fonts:
        return None
    fonts += [p for p in (Path(run).parent.parent / 'assets/fonts').rglob('*') if p.is_file()]
    visual_segment = {k: v for k, v in segment.items() if k not in ('prompt', 'reason')}
    return object_hash({'version': 1, 'source_sha256': plan['source_sha256'], 'segment': visual_segment,
        'items': items, 'video': {key: meta.get(key) for key in ('width', 'height', 'fps', 'duration')},
        'profile': plan.get('profile_sha256'),
        'fonts': {str(p): file_hash(p) for p in fonts},
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
