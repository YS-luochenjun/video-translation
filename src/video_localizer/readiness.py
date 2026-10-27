"""Local route diagnostics; never invokes remote models or approves content."""
import re
from pathlib import Path

from .common import WorkflowError
from . import media
from .layout import FONT_FILES, measurement_font


def inspect(root):
    root = Path(root)
    result = {'scope': 'Route prerequisites only; no rendering or quality approval',
              'issues': [], 'fonts': {}, 'reference_composite': {}}
    try:
        from PIL import ImageFont
        # Import the native extension too: importing PIL alone can hide ABI failures.
        from PIL import _imaging
        result['pillow_native'] = True
    except (ImportError, OSError):
        result['pillow_native'] = False
        result['issues'].append('Pillow native support unavailable; measured text fitting unavailable')
        ImageFont = None
    faces = {filename: (family, bold) for family, pair in FONT_FILES.items()
             for bold, filename in enumerate(pair)}
    result['font_paths'] = {}
    for name, (family, bold) in faces.items():
        path = measurement_font(root, family, bold)
        result['font_paths'][name] = str(path)
        status = 'missing'
        if path.is_file():
            status = 'unverified'
            if ImageFont is not None:
                try:
                    ImageFont.truetype(str(path), 16)
                    status = 'loadable'
                except (OSError, ValueError):
                    status = 'invalid'
        result['fonts'][name] = status
    result['optional_legacy_fonts_unavailable'] = [name for name, status in result['fonts'].items() if status != 'loadable']
    if ImageFont is not None:
        from .fonts import language_report
        result['language_fonts'] = language_report(root)
        missing = [name for name, report in result['language_fonts'].items() if report['status'] != 'ready']
        if missing:
            result['issues'].append('Required language font coverage unavailable: ' + ', '.join(missing))
    try:
        help_result = media.command(['ffmpeg', '-hide_banner', '-h', 'full'], timeout=15)
        help_text = help_result.stdout + help_result.stderr
        supported = bool(re.search(r'(?m)^\s*-filter_complex(?:\s|$)', help_text))
        result['reference_composite']['filter_complex_supported'] = supported
        if not supported:
            result['issues'].append('Reference compositor requires unsupported FFmpeg option: filter_complex')
    except WorkflowError:
        result['reference_composite']['filter_complex_supported'] = None
        result['issues'].append('Could not inspect FFmpeg capabilities')
    from .typography import environment_identity
    optional=environment_identity(root)
    result['typography']={'optional':True,'node_available':bool(optional['node']['sha256']),
                          'browser_configured':bool(optional['browser']['sha256']),
                          'remotion_installed':bool(optional['runtime_package']['sha256']),
                          'fallback':'ffmpeg_static; font/content gates still enforced',
                          'scope':'Presence only, no browser launch or quality approval'}
    result['status'] = 'ready' if not result['issues'] else 'attention'
    return result
