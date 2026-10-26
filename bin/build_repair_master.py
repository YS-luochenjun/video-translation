"""Build a source-based, pre-typography local repair control, without an API call."""
import argparse
import math
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from video_localizer.runtime import vision_path
sys.path.insert(0, str(vision_path(ROOT)))
import cv2
import numpy as np
from video_localizer.common import file_hash,get_run,read_json,require,run_operation,write_json


def glyph_mask(image,items,time,revision):
    hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    mask=np.zeros(image.shape[:2],np.uint8)
    for item in items:
        if not item['start']<=time<item['end']:continue
        poses=[p for p in item.get('trajectory',[]) if p['time']<=time+1e-6]
        point=poses[-1] if poses else {'bbox':item['bbox']}
        x,y,w,h=point['bbox'];kind=item['source_text']
        region=np.zeros_like(mask)
        padding=0 if kind in ('Morning','Children:3') else 10 if kind=='wait!' else 5
        if point.get('polygon'):
            polygon=np.array(point['polygon'],dtype=np.float32)
            centre=polygon.mean(axis=0);polygon=centre+(polygon-centre)*1.06
            cv2.fillConvexPoly(region,np.rint(polygon).astype(np.int32),255)
        else:
            cv2.rectangle(region,(max(0,round(x-padding)),max(0,round(y-padding))),
                          (min(image.shape[1]-1,round(x+w+padding)),min(image.shape[0]-1,round(y+h+padding))),255,-1)
        light=(hsv[:,:,2]>205)&(hsv[:,:,1]<130)
        if kind=='Zzz...':light=(hsv[:,:,2]>110)&(hsv[:,:,1]<55)
        if kind=='wait!':
            white=(hsv[:,:,2]>240)&(hsv[:,:,1]<65)
            red=((hsv[:,:,0]<12)|(hsv[:,:,0]>170))&(hsv[:,:,1]>140)&(hsv[:,:,2]>110)
            yellow=(hsv[:,:,0]>=15)&(hsv[:,:,0]<40)&(hsv[:,:,1]>120)&(hsv[:,:,2]>170)
            light=white|red|yellow
        letters=(light.astype(np.uint8)*255)&region
        radius=2 if kind in ('Morning','Children:3') else 8 if kind in ('wait!','Zzz...','Woof!') else 5
        if revision==2:radius+=1
        letters=cv2.dilate(letters,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(radius*2+1,radius*2+1)))&region
        mask|=letters
    return mask


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('run');parser.add_argument('--revision',type=int,choices=(1,2),default=1)
    args=parser.parse_args();run=get_run(args.run)
    from video_localizer.timing import measure
    from video_localizer.resources import heavy
    with run_operation(run), heavy(run, 'visual.master'), measure(run, 'visual.master'):
        return execute(args, run)


def execute(args, run):
    source=run/'inputs/source.mp4';inventory=read_json(run/'analysis/inventory.json');meta=read_json(run/'analysis/media.json')
    directory=run/'outputs'/f'repair-master-r{args.revision}';directory.mkdir(exist_ok=True)
    record_path=directory/'preparation.json';require(not record_path.exists(),'Recorded master revision exists; preserve it')
    output=directory/'visual-master.mp4'
    capture=cv2.VideoCapture(str(source));fps=capture.get(cv2.CAP_PROP_FPS);last=None;masked=0;processed=0
    process=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','bgr24','-s',
        f"{meta['width']}x{meta['height']}",'-r',str(fps),'-i','pipe:0','-an','-c:v','libx264','-crf','16','-preset','fast','-pix_fmt','yuv420p',str(output)],stdin=subprocess.PIPE,stderr=subprocess.PIPE)
    items=[i for i in inventory['text_instances'] if i['action']=='model_edit']
    for n in range(math.ceil(meta['duration']*fps)):
        ok,frame=capture.read()
        if ok:last=frame
        require(last is not None,'Original source frame missing')
        frame=last.copy();mask=glyph_mask(frame,items,n/fps,args.revision)
        if np.any(mask):frame=cv2.inpaint(frame,mask,5,cv2.INPAINT_TELEA)
        masked+=int(np.count_nonzero(mask));process.stdin.write(frame.tobytes());processed+=1
        if n and n%150==0:print(f'Source-only repair {n/fps:.1f}s',flush=True)
    capture.release();process.stdin.close();error=process.stderr.read().decode('utf-8',errors='replace')
    require(process.wait()==0,'Master encoding failed: '+error[-500:])
    proposals=[];inputs=[{'path':'inputs/source.mp4','sha256':file_hash(source)},
        {'path':'analysis/inventory.json','sha256':file_hash(run/'analysis/inventory.json')}]
    for path in (run/'jobs').glob('*.json'):
        job=read_json(path)
        if job.get('task_result_kind')=='video' and job.get('state')=='success':
            proposals.append({'job_record':path.relative_to(run).as_posix(),'result_sha256':job['result_sha256'],
                'adopted_pixels':0,'reason':'Actual raw proposal rejected for landscape regeneration and changed source motion/composition.'})
            inputs.extend([{'path':path.relative_to(run).as_posix(),'sha256':file_hash(path)},
                {'path':job['result'],'sha256':job['result_sha256']}])
    write_json(record_path,{'source_sha256':file_hash(source),'target_language':None,'contains_target_typography':False,
        'method':'Classical local glyph inpainting on original source frames, before any target-language layout. Separate local control after actual cheap video-model proposal was rejected; no generated video pixels adopted.',
        'inputs':inputs,'model_proposals':proposals,'output':{'path':output.relative_to(run).as_posix(),'sha256':file_hash(output)},
        'frames':processed,'masked_pixels':masked,'source_picture_tail_hold_seconds':max(0,meta['duration']-22.9),
        'approved_for_reuse':False,'source_lettering_may_remain':True,
        'limitations':['Source English in fixed UI remains for locale-specific overlay.','Dynamic residuals and repaired backgrounds require actual review.','This master is not a successful video-AI edit or an accepted clean plate.']})
    # Keep the inventory consumed by preparation immutable. Bind the new asset
    # only after its preparation inputs have been frozen to another file.
    frozen=directory/'input-inventory.json';write_json(frozen,inventory)
    record=read_json(record_path);record['inputs'][1]={'path':frozen.relative_to(run).as_posix(),'sha256':file_hash(frozen)}
    write_json(record_path,record)
    inventory['shots'][0]['prepared_video']={'path':output.relative_to(run).as_posix(),'sha256':file_hash(output),
        'record':record_path.relative_to(run).as_posix(),'record_sha256':file_hash(record_path)}
    write_json(run/'analysis/inventory.json',inventory)
    print({'master':str(output.relative_to(run)),'sha256':file_hash(output),'new_video_model_pixels_adopted':0})


if __name__=='__main__':main()
