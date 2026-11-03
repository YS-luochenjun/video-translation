"""Reject packed repair crops that omit the inventoried lettering/effects."""
import math
from .common import file_hash, inside, read_json, require, require_number


def _intervals(item):
    values = [item.get('source_interval',[item['start'],item['end']])]
    if item.get('source_ghost_interval') and not item.get('ghost_restoration_instance'):
        values.append(item['source_ghost_interval'])
    return values


def validate_packed(run, packet):
    path = run/'inputs/source-derivation.json'
    if not path.exists():
        return
    derived = read_json(path)
    if not derived.get('mapping') or not derived.get('packed_video'):
        return  # Ordinary same-shot full-frame probes are not spatially packed.
    require(packet.get('source_derivation') ==
            {'path':'inputs/source-derivation.json','sha256':file_hash(path)},
            'Packed repair must freeze its actual source-derivation mapping in the task packet')
    parent = inside(run.parent, derived['parent_run'])
    require(parent != run and parent.parent == run.parent, 'Packed repair needs an existing sibling parent run')
    metadata = read_json(parent/'run.json')
    source_sha = file_hash(inside(parent, metadata['source']))
    inventory = read_json(parent/'analysis/inventory.json')
    require(source_sha == derived.get('parent_source_sha256') == inventory.get('source_sha256'),
            'Packed repair parent source changed')
    require(packet['assets']['video']['sha256'] == derived['packed_video']['sha256'],
            'Packed repair mapping belongs to another video')
    texts = {i['id']:i for i in inventory.get('text_instances', [])}
    fps = read_json(parent/'analysis/media.json')['fps']
    scope = derived.get('mapping_scope','complete_instances')
    require(scope in {'complete_instances','partial_probe'}, 'Declare packed repair mapping_scope')
    coverage = {}
    for row in derived['mapping']:
        ids = row.get('instance_ids')
        require(isinstance(ids, list) and ids and len(ids) == len(set(ids)) and all(i in texts for i in ids),
                'Every packed repair crop needs explicit actual instance_ids; generic title/body labels are insufficient')
        crop = row['parent_crop']
        require(isinstance(crop,list) and len(crop)==4, 'Packed repair needs an explicit source crop')
        x,y,w,h = [require_number(v,'packed crop') for v in crop]
        require(w>0 and h>0, 'Packed repair crop must be positive')
        first,last = row['parent_frame_interval']
        require(type(first) is int and type(last) is int and 0<=first<last, 'Invalid packed source interval')
        for identity in ids:
            item = texts[identity]
            require(any(first/fps < end and last/fps > start for start,end in _intervals(item)),
                    'Packed crop instance is outside its source interval')
            coverage.setdefault(identity,[]).append((first,last))
            boxes = [item['bbox']]
            if item.get('source_effect_bbox'):
                boxes.append(item['source_effect_bbox'])
            for box in boxes:
                require(len(box)==4, 'Invalid source lettering/effect region')
                bx,by,bw,bh = [require_number(v,'source effect box') for v in box]
                require(bw>0 and bh>0 and x<=bx and y<=by and x+w>=bx+bw and y+h>=by+bh,
                        'Packed repair crop truncates source glyphs/outline/shadow: '+identity+
                        '; enlarge the crop instead of clipping the required repair scope')
    if scope == 'complete_instances':
        for identity, spans in coverage.items():
            item = texts[identity]
            for start,end in _intervals(item):
                cursor = max(0,math.ceil((start-.00001)*fps))
                stop = math.ceil((end-.00001)*fps)
                for first,last in sorted(spans):
                    if first > cursor:
                        break
                    cursor = max(cursor,last)
                require(cursor >= stop,
                        'Packed repair omits native source/effect frames: '+identity+
                        '; use complete half-open frame coverage, not rounded end times')
