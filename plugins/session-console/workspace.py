"""Resolve an explicit project binding without mistaking a plugin cache for it."""
import os
from pathlib import Path


def workspace_root(plugin_directory):
    configured = os.environ.get('VIDEO_LOCALIZER_WORKSPACE')
    root = (Path(configured).expanduser() if configured else
            Path(plugin_directory).resolve().parents[1]).resolve()
    if not ((root / 'AGENTS.md').is_file() and
            (root / 'workbench/console_data.py').is_file()):
        raise RuntimeError('Set VIDEO_LOCALIZER_WORKSPACE to the localization project checkout; '
                           'the installed plugin cache is not a project workspace')
    return root
