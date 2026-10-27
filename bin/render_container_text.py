"""Render recipe-owned UI text without painting over the original container."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from video_localizer.container_text import render


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('spec')
    parser.add_argument('output')
    args = parser.parse_args()
    output = Path(args.output)
    result = render(json.loads(Path(args.spec).read_text(encoding='utf-8')), output)
    output.with_suffix('.layout.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
