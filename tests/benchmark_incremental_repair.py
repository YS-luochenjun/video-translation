"""Offline lossless equivalence benchmark for migrating a legacy repair recipe."""
import argparse
import shutil
import tempfile
import time
from pathlib import Path

from video_localizer import media, repair
from video_localizer.common import ROOT, file_hash, inside, read_json, require, write_json


def frames(path):
    result = media.command(['ffmpeg','-v','error','-i',str(path),'-map','0:v:0',
                            '-pix_fmt','bgr24','-f','framemd5','-']).stdout
    return [line for line in result.splitlines() if line and not line.startswith('#')]


def benchmark(origin, first, second, expected_first, expected_second):
    recipes = [read_json(first), read_json(second)]
    record = read_json(origin/'run.json')
    dependencies = {record['source']: record['source_sha256']}
    for recipe in recipes:
        for name in ('base_video','proposal_video'):
            if name in recipe: dependencies[recipe[name]['path']] = recipe[name]['sha256']
    before = {str(p):file_hash(p) for p in (expected_first,expected_second)}
    with tempfile.TemporaryDirectory(prefix='incremental-repair-',dir=ROOT/'work/test-tmp') as temporary:
        root=Path(temporary); run=root/'runs/migration'; run.mkdir(parents=True)
        write_json(run/'run.json',record)
        for relative,digest in dependencies.items():
            original=inside(origin,relative); target=inside(run,relative)
            require(file_hash(original)==digest,'Migration source changed')
            target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(original,target)
        results=[]
        for n,recipe in enumerate(recipes):
            write_json(run/f'recipe-{n}.json',recipe)
            start=time.perf_counter(); result=repair.execute(run,f'recipe-{n}.json')
            results.append({'seconds':time.perf_counter()-start,'incremental':result['incremental'],
                            'pixels':frames(inside(run,result['output']['path']))})
        first_pixels,second_pixels=frames(expected_first),frames(expected_second)
        comparisons=[results[0]['pixels']==first_pixels,results[1]['pixels']==second_pixels]
        differences=[[n for n,(a,b) in enumerate(zip(r['pixels'],legacy)) if a!=b]
                     for r,legacy in zip(results,(first_pixels,second_pixels))]
        for relative,digest in dependencies.items():
            require(file_hash(inside(origin,relative))==digest,'Original input changed during benchmark')
        require(before=={str(p):file_hash(p) for p in (expected_first,expected_second)},'Original output changed')
        return {'source_sha256':record['source_sha256'],'legacy_outputs':before,
                'frames':len(first_pixels),'legacy_pixels_equal':comparisons,'different_frames':differences,
                'results':[{k:v for k,v in r.items() if k!='pixels'} for r in results],
                'business_inputs_unchanged':True,'paid_calls':0,
                'scope':'Decoded BGR pixel equality, not a new quality approval; full lossless encoding remains.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('run','first','second','expected_first','expected_second','report'):
        parser.add_argument('--'+name.replace('_','-'),type=Path,required=True)
    args=parser.parse_args()
    result=benchmark(args.run,args.first,args.second,args.expected_first,args.expected_second)
    write_json(args.report,result)
    print(result)
    require(all(result['legacy_pixels_equal']),'Migrated recipe differs from legacy; see saved comparison report')
