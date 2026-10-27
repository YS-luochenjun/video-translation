"""Project-owned tools and caches; no host-specific Codex paths."""
import os
import sys
import tempfile
from pathlib import Path


ASSET_PATHS = ('.runtime/deps/asr', '.runtime/deps/vision', '.runtime/deps/separation',
               '.runtime/models/asr/small', '.runtime/models/separation', 'assets/fonts',
               '.runtime/deps/remotion', '.runtime/deps/remotion-font-tools')


def vision_path(root):
    """Image-processing dependencies have one current installation location."""
    return Path(root) / '.runtime/deps/vision'


def configure(root):
    root = Path(root).resolve()
    cache = root / 'work/cache'
    for key, relative in {
        'HF_HOME': 'huggingface', 'HF_HUB_CACHE': 'huggingface/hub',
        'HUGGINGFACE_HUB_CACHE': 'huggingface/hub', 'TORCH_HOME': 'torch',
        'XDG_CACHE_HOME': 'xdg', 'MPLCONFIGDIR': 'matplotlib',
        'NUMBA_CACHE_DIR': 'numba', 'UV_CACHE_DIR': 'uv',
    }.items():
        os.environ[key] = str(cache / relative)
    os.environ['HF_HUB_DISABLE_XET'] = '1'
    temporary = root / 'work/tmp'
    temporary.mkdir(parents=True, exist_ok=True)
    # tempfile may have been initialized before importing the executor.
    tempfile.tempdir = str(temporary)
    os.environ['TMP'] = os.environ['TEMP'] = os.environ['TMPDIR'] = str(temporary)
    media_bin = root / '.runtime/ffmpeg/bin'
    if media_bin.is_dir():
        entries = os.environ.get('PATH', '').split(os.pathsep)
        os.environ['PATH'] = os.pathsep.join([str(media_bin), *[p for p in entries if p != str(media_bin)]])


def report(root):
    root = Path(root).resolve()
    assets = []
    for relative in ASSET_PATHS:
        path = root / relative
        exists = path.exists()
        resolved = path.resolve()
        assets.append({'path': relative, 'exists': exists,
                       'project_owned': exists and resolved.is_relative_to(root)})
    return {'python_executable': sys.executable,
            'python_project_owned': Path(sys.executable).resolve().is_relative_to(root),
            'python_base_project_owned': Path(sys.base_prefix).resolve().is_relative_to(root),
            'assets': assets, 'external_assets': [r['path'] for r in assets if r['exists'] and not r['project_owned']],
            'vision_dependency_path': str(vision_path(root).relative_to(root)),
            'vision_dependency_available': (vision_path(root) / 'cv2').is_dir(),
            'install_command': 'bin/setup.ps1',
            'scope': 'Paths and installation presence only, not model inference or video acceptance'}
