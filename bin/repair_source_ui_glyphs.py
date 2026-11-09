"""Stream a source-bound small-UI glyph repair recipe, with no automatic approval."""
import argparse
import os
from pathlib import Path
import subprocess
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from video_localizer.common import file_hash, get_run, inside, read_json, require, run_operation, utc_now, write_json
from video_localizer.repair_masks import select


def execute(run, relative, extension_reason=None):
    import cv2
    import numpy as np
    spec = read_json(inside(run, relative))
    paths = {k: inside(run, spec[k]['path']) for k in ('source','base_video')}
    for k, p in paths.items():
        require(file_hash(p) == spec[k]['sha256'], k+' changed')
    output = inside(run, spec['output'])
    require(not output.exists(), 'Preserve previous output')
    ledger_path = ROOT/'state/repair-trials'/(run.name+'.json')
    ledger = read_json(ledger_path) if ledger_path.exists() else {'attempts':[], 'extensions':[]}
    require(not any(x['state']=='running' for x in ledger['attempts']), 'Repair is already running')
    spent = sum(x.get('seconds',0) for x in ledger['attempts'])
    if len(ledger['attempts']) >= 4+len(ledger['extensions']) or spent >= 600+300*len(ledger['extensions']):
        require(extension_reason and len(extension_reason.strip())>=12, 'A bounded repair extension needs evidence and next variable')
        ledger['extensions'].append({'reason':extension_reason,'at':utc_now()})
    attempt = {'recipe':relative,'sha256':file_hash(inside(run,relative)),'state':'running','pid':os.getpid(),
               'started_at':utc_now(),'output':spec['output'],'method':'source_masked_small_ui_telea'}
    ledger['attempts'].append(attempt)
    write_json(ledger_path,ledger)
    started = time.perf_counter()
    caps = {k:cv2.VideoCapture(str(p)) for k,p in paths.items()}
    for cap in caps.values():
        require(cap.isOpened() and abs(cap.get(cv2.CAP_PROP_FPS)-spec['fps'])<.001
                and round(cap.get(cv2.CAP_PROP_FRAME_COUNT))==spec['frames'], 'Native source/base coverage differs')
    width,height = spec['width'],spec['height']
    output.parent.mkdir(parents=True,exist_ok=True)
    ffmpeg = shutil.which('ffmpeg')
    require(ffmpeg, 'FFmpeg is unavailable; run doctor with the configured media tools')
    encoder = subprocess.Popen([ffmpeg,'-v','error','-f','rawvideo','-pix_fmt','bgr24',
                                '-s',f'{width}x{height}','-r',str(spec['fps']),'-i','pipe:0','-an',
                                '-c:v','libx264','-crf','15','-preset','fast','-pix_fmt','yuv420p',str(output)],
                               stdin=subprocess.PIPE,stderr=subprocess.PIPE)
    counts = {x['id']:0 for x in spec['regions']}
    snapshots = []
    try:
        for n in range(spec['frames']):
            require(time.perf_counter()-started+spent < 600+300*len(ledger['extensions']), 'Bounded repair time exceeded')
            ok,original = caps['source'].read()
            base_ok,base = caps['base_video'].read()
            require(ok and base_ok and original.shape==base.shape==(height,width,3), 'Missing native frame')
            combined = np.zeros((height,width),np.uint8)
            for row in spec['regions']:
                if not row['source_frames'][0]<=n<row['source_frames'][1]:
                    continue
                polygon = row.get('polygons',{}).get(str(n), row.get('polygon'))
                require(polygon is not None, 'Missing reviewed source geometry')
                region = np.zeros_like(combined)
                cv2.fillConvexPoly(region,np.rint(polygon).astype(np.int32),255)
                mask = select(original,region,row['selector'],cv2,np)
                combined |= mask
                counts[row['id']] += int((mask>0).sum())
            current = base.copy()
            if np.any(combined):
                repaired = cv2.inpaint(base, combined, spec.get('inpaint_radius',2), cv2.INPAINT_TELEA)
                current[combined>0] = repaired[combined>0]
            require(np.array_equal(current[combined==0],base[combined==0]), 'Small UI repair changed other pixels')
            if n in spec.get('inspection_frames',[]):
                p = output.parent/(output.stem+f'-frame-{n:04d}.png')
                cv2.imwrite(str(p),current)
                snapshots.append({'path':str(p.relative_to(run)),'sha256':file_hash(p)})
            encoder.stdin.write(current.tobytes())
        encoder.stdin.close()
        error=encoder.stderr.read().decode(errors='replace')
        require(encoder.wait()==0,'Encoding failed: '+error[-400:])
        record={'source_sha256':spec['source']['sha256'],'recipe':{'path':relative,'sha256':file_hash(inside(run,relative))},
                'inputs':[spec['source'],spec['base_video']], 'output':{'path':spec['output'],'sha256':file_hash(output)},
                'native_frames':spec['frames'],'changed_pixels_by_instance':counts,'inspection_frames':snapshots,
                'contains_target_typography':False,'approved_for_reuse':False,
                'method':'Only source-pixel small glyph masks in the explicit native UI polygons use bounded Telea; no new panel or cover. Actual naturalness and remaining letters require review.'}
        write_json(output.with_suffix('.provenance.json'),record)
        attempt['state']='completed'
        return record
    except BaseException:
        attempt['state']='failed'
        raise
    finally:
        for cap in caps.values():cap.release()
        if encoder.poll() is None:
            encoder.terminate()
            try:encoder.wait(timeout=5)
            except subprocess.TimeoutExpired:
                encoder.kill();encoder.wait()
        for stream in (encoder.stdin,encoder.stderr):
            if stream is not None and not stream.closed:
                try:stream.close()
                except OSError:pass
        attempt['seconds']=time.perf_counter()-started
        write_json(ledger_path,ledger)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run');parser.add_argument('recipe');parser.add_argument('--extension-reason')
    args=parser.parse_args();run=get_run(args.run)
    with run_operation(run):
        print(execute(run,args.recipe,args.extension_reason))
