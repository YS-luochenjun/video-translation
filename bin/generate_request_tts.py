"""Generate only explicitly authorized request-specific Microsoft speech."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from video_localizer.common import get_run
from video_localizer.request_tts import generate

if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: generate_request_tts.py RUN SPEC')
    print(json.dumps(generate(get_run(sys.argv[1]), sys.argv[2])), flush=True)
