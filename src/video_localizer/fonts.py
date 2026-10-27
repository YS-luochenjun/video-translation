"""Explicit native font faces, glyph coverage and run-local single-face binding."""
from pathlib import Path
import sys
import unicodedata

from .common import CODE_ROOT, WorkflowError, file_hash, guarded, inside, read_json, require, write_json


def policy(root=CODE_ROOT):
    path = Path(root) / 'config/fonts.json'
    return read_json(path if path.is_file() else CODE_ROOT / 'config/fonts.json')


def native_face(root, family, bold=False):
    spec = policy(root)['native_families'][family]
    slot = int(bool(bold))
    project = Path(root) / 'assets/fonts' / spec['project_files'][slot]
    if project.is_file():
        return {'path': project, 'index': 0, 'family': family}
    system = Path('/System/Library/Fonts') / unicodedata.normalize('NFD', spec['files'][slot])
    if sys.platform == 'darwin' and system.is_file():
        return {'path': system, 'index': spec['indices'][slot], 'family': family}
    return {'path': project, 'index': 0, 'family': family}


def default_family(text='', locale=None, root=CODE_ROOT):
    locale = (locale or '').lower()
    script = ('zh-TW' if locale in ('zh-tw', 'zh-hk', 'zh-hant') else locale.split('-')[0])
    if not script:
        ranges = [('ja', 0x3040, 0x30ff), ('ko', 0xac00, 0xd7af), ('th', 0x0e00, 0x0e7f),
                  ('hi', 0x0900, 0x097f), ('ar', 0x0600, 0x06ff), ('zh', 0x3400, 0x9fff)]
        script = next((s for s, low, high in ranges if any(low <= ord(c) <= high for c in text)), 'latin')
    if sys.platform == 'darwin':
        return policy(root)['darwin_defaults'].get(script, 'Arial')
    return {'zh': 'Microsoft YaHei', 'zh-TW': 'Microsoft YaHei', 'ja': 'Yu Gothic', 'ko': 'Malgun Gothic'}.get(script, 'Arial')


def missing_glyphs(face, text):
    from .typography import _font_modules
    with _font_modules().TTFont(face['path'], fontNumber=face['index'], lazy=True) as font:
        cmap = font.getBestCmap() or {}
        return sorted({c for c in text if not c.isspace() and unicodedata.category(c) != 'Cf'
                       and not 0xfe00 <= ord(c) <= 0xfe0f and ord(c) not in cmap})


def ass_name(root, family, bold=False, directory=None):
    """CoreText may misresolve a spaced family name; select the exact native face."""
    if directory is None and family not in policy(root)['native_families']:
        return family
    from .layout import measurement_face
    from .typography import _font_modules
    face = measurement_face(root, family, bold)
    require(face['path'].is_file(), f'Requested font is unavailable: {family}')
    with _font_modules().TTFont(face['path'], fontNumber=face['index'], recalcTimestamp=False) as font:
        require(font['name'].getDebugName(1) == family, 'Requested and actual font family differ')
        name = font['name'].getDebugName(6)
        if directory is not None:
            # Supplying the exact single face to libass avoids CoreText family
            # substitutions (notably Geeza Pro -> Helvetica before glyph fallback).
            suffix = '.otf' if 'CFF ' in font else '.ttf'
            path = Path(directory) / 'fonts' / f'{file_hash(face["path"])[:16]}-{face["index"]}{suffix}'
            path.parent.mkdir(parents=True, exist_ok=True)
            manifest = Path(directory) / 'font-records' / (path.stem + '.json')
            if path.exists():
                require(read_json(manifest)['sha256'] == file_hash(path), 'Generated renderer font changed')
            else:
                font.save(path)
                write_json(manifest, {'path': path.name, 'sha256': file_hash(path), 'source_sha256': file_hash(face['path']),
                                     'source_face_index': face['index'], 'family': family})
            # libass matches its supplied memory fonts by family, not by their
            # PostScript name. This takes precedence over CoreText discovery.
            name = font['name'].getDebugName(1)
    require(name and not any(c in name for c in ',\n\r{}\\'), 'Invalid font PostScript name')
    return name


def language_report(root):
    from PIL import ImageFont
    from .layout import measurement_face
    output = {}
    for locale, sample in policy(root)['samples'].items():
        family = default_family(sample, None if locale == 'latin' else locale, root)
        faces = []
        for bold in (False, True):
            face = measurement_face(root, family, bold)
            row = {'path': str(face['path']), 'index': face['index'], 'bold': bold, 'status': 'missing'}
            if face['path'].is_file():
                try:
                    font = ImageFont.truetype(str(face['path']), 24, index=face['index'])
                    require(font.getname()[0] == family, f'Configured font face is not {family}')
                    missing = missing_glyphs(face, sample)
                    row.update(status='missing_glyphs' if missing else 'loadable', actual_face=list(font.getname()),
                               missing_glyphs=[f'U+{ord(c):04X}' for c in missing])
                except (OSError, ValueError, WorkflowError, ImportError) as exc:
                    row.update(status='invalid', error=str(exc))
            faces.append(row)
        output[locale] = {'family': family, 'sample': sample, 'faces': faces,
                          'status': 'ready' if all(f['status'] == 'loadable' for f in faces) else 'attention'}
    return output


@guarded
def bind(run, family, bold=False, text=''):
    """Extract the real TTC face without renaming its internal family or weight."""
    from .layout import measurement_face
    from .typography import _font_modules
    run = Path(run)
    face = measurement_face(run.parent.parent, family, bold)
    require(face['path'].is_file(), f'Requested font is unavailable: {family}')
    missing = missing_glyphs(face, text)
    require(not missing, 'Font missing glyphs: ' + ', '.join(f'U+{ord(c):04X}' for c in missing))
    digest = file_hash(face['path'])
    with _font_modules().TTFont(face['path'], fontNumber=face['index'], recalcTimestamp=False) as font:
        require(font['name'].getDebugName(1) == family, 'Font collection face has a different family')
        suffix = '.otf' if 'CFF ' in font else '.ttf'
        path = inside(run, f'inputs/fonts/{digest[:16]}-{face["index"]}{suffix}')
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            previous = read_json(path.with_suffix('.font.json'))
            require(previous['source_sha256'] == digest and previous['source_face_index'] == face['index']
                    and previous['output']['sha256'] == file_hash(path), 'Previously bound font changed; inspect rather than overwrite')
        else:
            font.save(path)
    result = {'path': path.relative_to(run).as_posix(), 'sha256': file_hash(path)}
    write_json(path.with_suffix('.font.json'), {'family': family, 'bold': bold, 'source_sha256': digest,
               'source_face_index': face['index'], 'output': result, 'text_checked': text})
    return result
