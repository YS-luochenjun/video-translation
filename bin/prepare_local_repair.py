"""Prepare a protected local merge from a reviewed, model-independent recipe."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from video_localizer.local_repair import prepare


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recipe')
    parser.add_argument('output_directory')
    args = parser.parse_args()
    report = prepare(json.loads(Path(args.recipe).read_text(encoding='utf-8')), args.output_directory)
    Path(args.output_directory, 'preparation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
