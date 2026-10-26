"""Local residual-letter cleanup experiment on a model-edited VIDEO, before native type."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from video_localizer.runtime import vision_path
sys.path.insert(0, str(vision_path(ROOT)))
import cv2
import numpy as np
from video_localizer import compositor,media
from video_localizer.common import file_hash,get_run,inside,read_json,require,run_operation,write_json


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('run')
    parser.add_argument('--revision',type=int,choices=(1,2),default=1)
    args=parser.parse_args()
    run=get_run(args.run)
    from video_localizer.resources import heavy
    from video_localizer.timing import measure
    with run_operation(run), heavy(run, 'visual.residual_repair'), measure(run, 'visual.residual_repair'):
        return execute(args, run)


def execute(args, run):
    plan=read_json(run/'plan.json');inventory=read_json(run/'analysis/inventory.json')
    require(len(plan['segments'])==1,'Residual cleanup experiment currently expects one full-source model segment')
    segment=plan['segments'][0];meta=read_json(run/'analysis/media.json')
    source=run/'outputs/segments'/plan['id']/segment['id']/'source-regions/visual.mp4'
    require(source.is_file(),'Render and review the regional model result first')
    original=read_json(run/'outputs/candidate.json')
    directory=run/'outputs'/('residual-cleanup' if args.revision==1 else 'residual-cleanup-r2')
    require(not (directory/'operation.json').exists(),'This revision is already recorded; preserve its output and review evidence')
    directory.mkdir(exist_ok=True)
    write_json(directory/'parent-candidate.json',original)
    cleaned=directory/'clean-visual.mp4'
    capture=cv2.VideoCapture(str(source));fps=capture.get(cv2.CAP_PROP_FPS)
    original_video=run/'inputs/source.mp4'
    original_capture=cv2.VideoCapture(str(original_video)) if args.revision==2 else None
    last_source=None
    process=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','bgr24','-s',f"{meta['width']}x{meta['height']}",'-r',str(fps),'-i','pipe:0','-an','-c:v','libx264','-crf','16','-preset','fast','-pix_fmt','yuv420p',str(cleaned)],stdin=subprocess.PIPE,stderr=subprocess.PIPE)
    items=[item for item in inventory['text_instances'] if item['action']=='model_edit']
    counts={item['id']:0 for item in items};frame=0
    while True:
        ok,image=capture.read()
        if not ok:break
        model_image=image
        if original_capture is not None:
            ok,actual_source=original_capture.read()
            if ok:last_source=actual_source
            require(last_source is not None,'Source frame unavailable')
            image=last_source.copy()
        time=frame/fps;mask=np.zeros(image.shape[:2],np.uint8)
        hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
        for item in items:
            if not item['start']<=time<item['end']:continue
            poses=[p for p in item.get('trajectory',[]) if p['time']<=time]
            point=poses[-1] if poses else {'bbox':item['bbox']}
            x,y,w,h=point['bbox'];padding=6 if item['source_text']=='wait!' else 4
            if args.revision==2 and item['source_text']=='Morning':padding=0
            region=np.zeros(mask.shape,np.uint8)
            if point.get('polygon'):
                p=np.array(point['polygon'],dtype=np.float32);centre=p.mean(axis=0);p=centre+(p-centre)*1.04
                cv2.fillConvexPoly(region,np.rint(p).astype(np.int32),255)
            else:
                cv2.rectangle(region,(max(0,round(x-padding)),max(0,round(y-padding))),(min(meta['width']-1,round(x+w+padding)),min(meta['height']-1,round(y+h+padding))),255,-1)
            # Isolate light lettering then include its adjoining dark/colored outline.
            # Keep ordinary foliage, character bodies and icon art outside these strokes.
            letters=((hsv[:,:,2]>195)&(hsv[:,:,1]<130)).astype(np.uint8)*255
            if item['source_text']=='wait!':
                letters=((hsv[:,:,2]>220)&(hsv[:,:,1]<95)).astype(np.uint8)*255
                if args.revision==2:
                    letters=((hsv[:,:,2]>245)&(hsv[:,:,1]<65)).astype(np.uint8)*255
            letters=cv2.bitwise_and(letters,region)
            if args.revision==2 and item['source_text']=='wait!':
                count,labels,stats,_=cv2.connectedComponentsWithStats(letters)
                keep=[i for i in range(1,count) if stats[i,cv2.CC_STAT_AREA]>=500 and stats[i,cv2.CC_STAT_HEIGHT]>=30]
                letters=np.isin(labels,keep).astype(np.uint8)*255
            radius=9 if item['source_text']=='wait!' else 5
            letters=cv2.dilate(letters,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(radius*2+1,radius*2+1)))
            letters=cv2.bitwise_and(letters,region)
            mask=cv2.bitwise_or(mask,letters);counts[item['id']]+=int(np.count_nonzero(letters))
        if np.any(mask):
            repaired=cv2.inpaint(model_image,mask,5,cv2.INPAINT_TELEA)
            if args.revision==2:image[mask>0]=repaired[mask>0]
            else:image=repaired
        process.stdin.write(image.tobytes());frame+=1
        if frame%150==0:print(f'Local cleanup {frame/fps:.1f}s',flush=True)
    capture.release()
    if original_capture is not None:original_capture.release()
    process.stdin.close();errors=process.stderr.read().decode('utf-8',errors='replace');require(process.wait()==0,'Residual video encoding failed: '+errors[-500:])
    typeset=compositor.text(cleaned,segment,inventory['text_instances'],meta,directory/'typeset')
    fixed=media.render_local(typeset,segment,inventory['text_instances'],meta,directory/'fixed-ui')
    suffix='local-repair' if args.revision==1 else 'local-repair-r2'
    output=run/'outputs'/f"candidate-{plan['id']}-{suffix}.mp4"
    media.assemble([fixed],run/inventory['audio']['replacement_path'],output,meta['duration'])
    record=directory/'operation.json'
    write_json(record,{'kind':'local_residual_cleanup_experiment','revision':args.revision,'method':'Classical Telea inpainting of observed light glyph strokes in a regional video-model proposal, followed by native tracked Chinese type. Revision 2 uses actual source pixels outside the glyph mask, with tighter Wait components and Morning bounds. This is a separate local repair route, not proof that the video model erased English.',
        'inputs':[{'path':source.relative_to(run).as_posix(),'sha256':file_hash(source)},{'path':'inputs/source.mp4','sha256':file_hash(original_video)},{'path':'analysis/inventory.json','sha256':file_hash(run/'analysis/inventory.json')},{'path':original['path'],'sha256':original['sha256']}],
        'output':{'path':output.relative_to(run).as_posix(),'sha256':file_hash(output)},'frames':frame,'mask_pixel_counts':counts,
        'limitations':['Local background reconstruction can blur occluded details; review actual video before acceptance.','Source timing endpoints inherit OCR proposal uncertainty.','No new paid model task was submitted for this repair.']})
    candidate={**original,'path':output.relative_to(run).as_posix(),'sha256':file_hash(output),'postprocessing':[{'record':record.relative_to(run).as_posix(),'sha256':file_hash(record)}]}
    write_json(run/'outputs/candidate.json',candidate)
    print({'candidate':candidate['path'],'sha256':candidate['sha256']})


if __name__=='__main__':main()
