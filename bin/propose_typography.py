"""Print measured layout candidates without changing inventory or choosing a design."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from video_localizer.common import get_run, read_json, inside, require, file_hash
from video_localizer.layout import typography_candidates
from video_localizer.typography import contract


def propose(run, instance_id):
    inventory = read_json(run/'analysis/inventory.json')
    item = next((entry for entry in inventory['text_instances'] if entry['id'] == instance_id), None)
    require(item is not None, 'Unknown text instance')
    contract(run, {'text_instances':[item]})
    display = item['display']
    require('font_asset' in display, 'Bind an actual font before proposing layouts')
    font = inside(run, display['font_asset']['path'])
    require(font.is_file() and file_hash(font) == display['font_asset']['sha256'], 'Layout font missing or changed')
    candidates = typography_candidates(item['target_text'], font,
                    item['bbox'], display.get('font_size', 48), display.get('min_font_size', 16),
                    display.get('outline', 2), display.get('direction', 'ltr'))
    return {'instance_id':instance_id, 'canonical_text':item['target_text'], 'candidates':candidates,
            'next':'Compare against source style and select display.layout_lines explicitly; review actual rendered glyphs'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run')
    parser.add_argument('--instance', required=True)
    args = parser.parse_args()
    print(json.dumps(propose(get_run(args.run), args.instance), ensure_ascii=False, indent=2))
