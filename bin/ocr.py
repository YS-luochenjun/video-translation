"""Compatibility name: prepare Codex visual recognition; never invoke an OCR model."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from video_localizer.cli import main

if __name__ == '__main__':
    raise SystemExit(main(['codex-packet', *sys.argv[1:]]))
