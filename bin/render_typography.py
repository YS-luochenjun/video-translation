"""Render one inventory shot's reviewed neutral master, for a fast recipe.

Normal workflow.render invokes this same typography adapter automatically.
This command creates media and evidence, never acceptance or a new paid task.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from video_localizer.common import get_run, read_json, file_hash, guarded, require
from video_localizer import workflow, prepared, contracts, resources


@guarded
def compose(run, shot_id):
    inventory=read_json(run/'analysis/inventory.json');meta=read_json(run/'analysis/media.json')
    contracts.validate_inventory(inventory,run,meta)
    shot=next((s for s in inventory['shots'] if s['id']==shot_id),None)
    require(shot and shot.get('prepared_video'),'Select an actual shot with a reviewed prepared neutral master')
    source=workflow.source_path(run)
    items=[i for i in inventory['text_instances'] if i['start']<shot['end'] and i['end']>shot['start']]
    from video_localizer.typography import contract
    binding=contract(run,inventory)
    from video_localizer.common import object_hash
    key=object_hash({'shot':shot,'items':items,'source':file_hash(source),'typography':binding})[:16]
    directory=run/'outputs/typography'/key
    with resources.heavy(run,'typography.compose'):
        directory.mkdir(parents=True,exist_ok=True)
        output=prepared.render(run,shot,items,meta,directory,file_hash(source))
    receipt=directory/'target-overlay/typography-result.json'
    return {'output':{'path':output.relative_to(run).as_posix(),'sha256':file_hash(output)},
            'typography_assets':[{'path':receipt.relative_to(run).as_posix(),'sha256':file_hash(receipt)}] if receipt.exists() else [],
            'state':'needs_review','next':'Bind output and receipts in the fast recipe; inspect actual video before fast-review'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run');parser.add_argument('--shot',required=True)
    args=parser.parse_args();print(json.dumps(compose(get_run(args.run),args.shot),ensure_ascii=False,indent=2))
