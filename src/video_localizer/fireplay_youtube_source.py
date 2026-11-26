"""Fetch the exact registered YouTube source without importing it into Fireplay."""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from .common import WorkflowError, file_hash, inside, read_json, require, utc_now, write_json
from .media import probe
from .runtime import YOUTUBE_DEPENDENCY_DIR


def download(root, video_id, run_folder):
    deps = Path(root) / YOUTUBE_DEPENDENCY_DIR
    if not (deps / 'yt_dlp/__main__.py').is_file():
        return {'state': 'unavailable', 'reason': 'Project yt-dlp dependency is not installed'}

    folder = inside(root, f'work/runs/{run_folder}/youtube-source')
    evidence = folder / 'receipt.json'
    destination = folder / 'source.mp4'
    if evidence.is_file():
        result = read_json(evidence)
        require(result['youtube_video_id'] == video_id, 'Local YouTube receipt belongs to a different video')
        if result['state'] == 'downloaded':
            require(destination.is_file() and file_hash(destination) == result['source']['sha256'],
                    'Local YouTube source changed after verification')
        return result

    folder.mkdir(parents=True, exist_ok=True)
    node = shutil.which('node')
    node_settings = Path(root) / 'config/remotion.local.json'
    if not node and node_settings.is_file():
        node = read_json(node_settings).get('node')
    log = folder / 'download.log'
    url = f'https://www.youtube.com/watch?v={video_id}'
    result = {'youtube_video_id': video_id, 'source_url': url, 'attempted_at': utc_now(),
              'log': log.relative_to(root).as_posix()}
    with TemporaryDirectory(dir=folder) as temporary:
        staging = Path(temporary)
        args = [sys.executable, '-m', 'yt_dlp', '--ignore-config', '--no-playlist',
                '--socket-timeout', '10', '--retries', '0', '--fragment-retries', '0',
                '--extractor-retries', '0', '--no-progress', '--no-cache-dir',
                '--merge-output-format', 'mp4', '--remux-video', 'mp4', '--write-info-json',
                '-o', str(staging / 'source.%(ext)s')]
        if node:
            args.extend(('--js-runtimes', f'node:{node}'))
        env = {**os.environ, 'PYTHONPATH': str(deps)}
        try:
            with log.open('w', encoding='utf-8') as stream:
                subprocess.run([*args, '--', url], env=env, stdout=stream, stderr=subprocess.STDOUT,
                               timeout=55, check=True)
            info = read_json(staging / 'source.info.json')
            require(info.get('id') == video_id and info.get('extractor_key') == 'Youtube',
                    'Downloaded media identity does not match the registered YouTube video')
            staged_video = staging / 'source.mp4'
            media = probe(staged_video)
            require(media['width'] > 0 and media['height'] > 0, 'Downloaded video dimensions must be positive')
            duration = info.get('duration')
            require(not duration or abs(media['duration'] - duration) < 1,
                    'Downloaded duration differs from YouTube metadata')
            source = {key: media[key] for key in ('duration', 'width', 'height')}
            source.update(path=destination.relative_to(root).as_posix(), sha256=file_hash(staged_video))
            staged_video.replace(destination)
            result.update(state='downloaded', source=source, has_audio=media['has_audio'])
        except (OSError, ValueError, WorkflowError, subprocess.SubprocessError) as exc:
            result.update(state='failed', reason=str(exc))
    write_json(evidence, result)
    return result
