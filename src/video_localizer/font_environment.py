"""Fingerprint installed and project fonts without assuming a Windows host."""
import os
from pathlib import Path
import sys

from .common import CODE_ROOT, operation_hash

FONT_SUFFIXES = {'.ttf', '.ttc', '.otf', '.otc', '.woff', '.woff2'}


def files(root):
    directories = [CODE_ROOT/'assets/fonts', Path(root)/'assets/fonts']
    configs = []
    if sys.platform == 'win32':
        directories.append(Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts')
    elif sys.platform == 'darwin':
        directories += [Path('/System/Library/Fonts'), Path('/Library/Fonts'), Path.home()/'Library/Fonts']
    elif sys.platform.startswith('linux'):
        directories += [Path('/usr/share/fonts'), Path('/usr/local/share/fonts'),
                        Path.home()/'.local/share/fonts', Path.home()/'.fonts']
        configs = [Path('/etc/fonts'), Path.home()/'.config/fontconfig']
    found = {}
    for directory in directories:
        if directory.is_dir():
            for path in directory.rglob('*'):
                if path.is_file() and path.suffix.lower() in FONT_SUFFIXES:
                    found[str(path.resolve())] = path.resolve()
    if not found:
        return []
    for directory in configs:
        if directory.is_dir():
            for path in directory.rglob('*.conf'):
                if path.is_file():found[str(path.resolve())] = path.resolve()
    explicit = os.environ.get('FONTCONFIG_FILE')
    if explicit and Path(explicit).is_file():
        found[str(Path(explicit).resolve())] = Path(explicit).resolve()
    return [found[name] for name in sorted(found)]


def fingerprint(root, cache=None):
    paths = files(root)
    if not paths:return None
    # The caller may share this cache only inside one locked render operation.
    cache = {} if cache is None else cache
    return {'platform':sys.platform, 'files':{str(p):operation_hash(p,cache) for p in paths}}
