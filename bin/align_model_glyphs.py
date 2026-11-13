"""Same-frame model registration with explicit same-shot reference fallback.

This never retimes a video. Unedited pixels always come from the native base.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from video_localizer.common import file_hash,inside,read_json,require,run_operation,utc_now,write_json
from video_localizer.repair_masks import select


def execute(run,relative,extension_reason):
    import cv2
    import numpy as np
    spec=read_json(inside(run,relative))
    def checked(asset):
        path=inside(run,asset['path'])
        require(path.is_file() and file_hash(path)==asset['sha256'],'Dependency changed: '+asset['path'])
        return path
    source=checked(spec['source']);base=checked(spec['base_video'])
    output=inside(run,spec['output']);require(not output.exists(),'Preserve prior outputs')
    ledger_path=ROOT/'state/repair-trials'/(run.name+'.json')
    ledger=read_json(ledger_path) if ledger_path.exists() else {'attempts':[],'extensions':[]}
    require(not any(x['state']=='running' for x in ledger['attempts']),'Another local repair is active')
    spent=sum(x.get('seconds',0) for x in ledger['attempts'])
    if len(ledger['attempts'])>=4+len(ledger['extensions']) or spent>=600+300*len(ledger['extensions']):
        require(extension_reason and len(extension_reason)>=12,'Bounded extension requires actual defect and next variable')
        ledger['extensions'].append({'reason':extension_reason,'at':utc_now()})
    attempt={'recipe':relative,'sha256':file_hash(inside(run,relative)),'state':'running','pid':os.getpid(),
             'started_at':utc_now(),'output':spec['output'],'method':'same_frame_registration_or_same_shot_reference'}
    ledger['attempts'].append(attempt);write_json(ledger_path,ledger)
    start=time.perf_counter();width,height=spec['width'],spec['height']
    sift=cv2.SIFT_create(nfeatures=spec.get('features',1000))
    matcher=cv2.BFMatcher()
    def features(frame,exclude=None):
        gray=cv2.resize(cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY),None,fx=.5,fy=.5)
        allowed=None if exclude is None else cv2.resize(255-exclude,(gray.shape[1],gray.shape[0]),interpolation=cv2.INTER_NEAREST)
        return sift.detectAndCompute(gray,allowed)
    def matrix(fa,fb):
        ka,da=fa;kb,db=fb
        if da is None or db is None:return None,0,0
        pairs=matcher.knnMatch(da,db,k=2)
        good=[p[0] for p in pairs if len(p)==2 and p[0].distance<.7*p[1].distance]
        if len(good)<6:return None,0,len(good)
        a=np.float32([ka[m.queryIdx].pt for m in good])*2
        b=np.float32([kb[m.trainIdx].pt for m in good])*2
        H,mask=cv2.findHomography(a,b,cv2.RANSAC,4)
        if H is None:return None,0,len(good)
        return H,int(mask.sum()),len(good)
    yy,xx=np.mgrid[:height,:width].astype(np.float32)
    def warp(frame,H):
        z=H[2,0]*xx+H[2,1]*yy+H[2,2]
        require(np.isfinite(H).all() and np.min(np.abs(z))>.1,'Invalid projective transform')
        mx=(H[0,0]*xx+H[0,1]*yy+H[0,2])/z
        my=(H[1,0]*xx+H[1,1]*yy+H[1,2])/z
        return cv2.remap(frame,mx.astype(np.float32),my.astype(np.float32),cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT)
    refs=[]
    for scene in spec['scenes']:
        original=cv2.imread(str(checked(scene['source_key'])))
        clean=cv2.imread(str(checked(scene['clean_reference'])))
        require(original is not None and clean is not None,'Reference decode failed')
        clean=cv2.resize(clean,(width,height))
        sf=features(original)
        H,n,m=matrix(sf,features(clean))
        refs.append({'scene':scene,'original':original,'clean':clean,'source_features':sf,'key_to_clean':np.eye(3) if spec.get('reference_projection')=='native_source_flow_identity_reference' else (H if H is not None and n>=6 else np.eye(3)),
                     'reference_inliers':n,'reference_matches':m})
    model_caps=[]
    for row in spec['models']:
        cap=cv2.VideoCapture(str(checked(row['asset'])))
        require(cap.isOpened() and abs(cap.get(cv2.CAP_PROP_FPS)-spec['fps'])<.001,'Model native fps mismatch')
        require(round(cap.get(cv2.CAP_PROP_FRAME_COUNT))>=row['asset_start_frame']+row['source_frames'][1]-row['source_frames'][0],
                'Model source-time coverage insufficient; no padding or stretching')
        cap.set(cv2.CAP_PROP_POS_FRAMES,row['asset_start_frame'])
        model_caps.append((row,cap))
    caps=[cv2.VideoCapture(str(source)),cv2.VideoCapture(str(base))]
    for cap in caps:
        require(cap.isOpened() and round(cap.get(cv2.CAP_PROP_FRAME_COUNT))==spec['frames']
                and abs(cap.get(cv2.CAP_PROP_FPS)-spec['fps'])<.001,'Source/base native coverage mismatch')
    output.parent.mkdir(parents=True,exist_ok=True)
    enc=subprocess.Popen([str(ROOT/'.runtime/ffmpeg/bin/ffmpeg'),'-v','error','-f','rawvideo','-pix_fmt','bgr24',
                          '-s',f'{width}x{height}','-r',str(spec['fps']),'-i','pipe:0','-an','-c:v','libx264',
                          '-crf','15','-preset','fast','-pix_fmt','yuv420p',str(output)],stdin=subprocess.PIPE,stderr=subprocess.PIPE)
    trace=[]
    try:
        for n in range(spec['frames']):
            require(time.perf_counter()-start<spec['max_seconds'] and time.perf_counter()-start+spent<600+300*len(ledger['extensions']),
                    'Bounded alignment time exhausted')
            ok,original=caps[0].read();base_ok,current=caps[1].read()
            require(ok and base_ok and original.shape==current.shape==(height,width,3),'Missing native source/base frame')
            baseline=current.copy();mask=np.zeros((height,width),np.uint8);exclude=np.zeros_like(mask)
            for row in spec['regions']:
                if row['source_frames'][0]<=n<row['source_frames'][1]:
                    x,y,w,h=row['mask_bbox'];region=np.zeros_like(mask);region[y:y+h,x:x+w]=255
                    mask|=select(original,region,row['mask_selector'],cv2,np);exclude|=region
            source_features=features(original,exclude)
            model_row,model_cap=next((a,c) for a,c in model_caps if a['source_frames'][0]<=n<a['source_frames'][1])
            model_ok,model=model_cap.read();require(model_ok,'Missing exact native model frame')
            H,inliers,matches=matrix(source_features,features(model))
            ref=next(r for r in refs if r['scene']['frames'][0]<=n<r['scene']['frames'][1])
            reason='same_frame_model';error=None;proposal=None
            if H is not None and inliers>=spec['min_model_inliers'] and inliers/max(matches,1)>=spec['min_model_inlier_ratio']:
                try:
                    warped=warp(model,H)
                    valid=exclude[::12,::12]==0
                    error=float(np.median(np.abs(original[::12,::12].astype(np.float32)-warped[::12,::12].astype(np.float32)).mean(axis=2)[valid]))
                    if error<=spec['max_model_color_error']:proposal=warped
                except Exception:
                    proposal=None
            if ref['scene'].get('prefer_reference') or proposal is None:
                reason='same_shot_reference_preferred' if ref['scene'].get('prefer_reference') else 'model_correspondence_rejected'
                M,ref_inliers,ref_matches=matrix(source_features,ref['source_features'])
                if M is not None and ref_inliers>=6 and ref['scene'].get('prefer_reference'):
                    try:proposal=warp(ref['clean'],ref['key_to_clean']@M)
                    except Exception:proposal=None
                else:proposal=None
                if proposal is None:
                    # Animated poses can lack six global feature correspondences.
                    # Project a declared same-shot plate using actual source flow;
                    # never borrow a neighboring scene or freeze a video frame.
                    key_mask=np.zeros_like(mask)
                    for row in spec['regions']:
                        if row['source_frames'][0]<=ref['scene']['keyframe']<row['source_frames'][1]:
                            x,y,w,h=row['mask_bbox'];region=np.zeros_like(mask);region[y:y+h,x:x+w]=255
                            key_mask|=select(ref['original'],region,row['mask_selector'],cv2,np)
                    def guide(frame,glyphs):
                        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
                        return cv2.resize(cv2.inpaint(gray,glyphs,3,cv2.INPAINT_TELEA),None,fx=.5,fy=.5)
                    dis=cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
                    flow=cv2.resize(dis.calc(guide(original,mask),guide(ref['original'],key_mask),None),(width,height))*2
                    for channel in range(2):flow[:,:,channel]=cv2.inpaint(flow[:,:,channel],mask,3,cv2.INPAINT_TELEA)
                    clean_key=warp(ref['clean'],ref['key_to_clean'])
                    proposal=cv2.remap(clean_key,xx+flow[:,:,0],yy+flow[:,:,1],cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT)
                    reason+=':source_dense_flow'
            else:ref_inliers=ref_matches=None
            alpha=cv2.GaussianBlur(mask.astype(np.float32)/255,(0,0),spec['edge_sigma'])
            visible=(alpha<.01).astype(np.float32);sigma=spec['exposure_sigma']
            difference=(original.astype(np.float32)-proposal.astype(np.float32))*visible[:,:,None]
            weight=cv2.GaussianBlur(visible,(0,0),sigma)
            correction=cv2.GaussianBlur(difference,(0,0),sigma)/np.maximum(weight[:,:,None],.01)
            proposal=np.clip(proposal.astype(np.float32)+correction,0,255)
            current=np.rint(current*(1-alpha[:,:,None])+proposal*alpha[:,:,None]).astype(np.uint8)
            require(np.array_equal(current[alpha==0],baseline[alpha==0]),'Non-mask source/base pixels changed')
            enc.stdin.write(current.tobytes())
            trace.append({'frame':n,'source_pts':n/spec['fps'],'model_frame':n-model_row['source_frames'][0]+model_row['asset_start_frame'],
                          'model_inliers':inliers,'model_matches':matches,'model_color_error':error,'adoption':reason,
                          'scene':ref['scene']['id'],'reference_frame':ref['scene']['keyframe'],
                          'reference_inliers':ref_inliers,'reference_matches':ref_matches,'changed_mask_pixels':int((alpha>0).sum())})
            if n in spec.get('inspection_frames',[]):cv2.imwrite(str(output.parent/(output.stem+f'-frame-{n:04d}.png')),current)
        enc.stdin.close();error=enc.stderr.read().decode(errors='replace');require(enc.wait()==0,'Encoding failed: '+error[-400:])
        trace_path=output.with_suffix('.alignment.json');write_json(trace_path,trace)
        record={'source_sha256':spec['source']['sha256'],'recipe':{'path':relative,'sha256':file_hash(inside(run,relative))},
                'implementation_sha256':file_hash(Path(__file__)),'output':{'path':spec['output'],'sha256':file_hash(output)},
                'alignment':{'path':str(trace_path.relative_to(run)),'sha256':file_hash(trace_path)},'native_frames':spec['frames'],
                'adoption_counts':{reason:sum(x['adoption']==reason for x in trace) for reason in set(x['adoption'] for x in trace)},
                'contains_target_typography':False,'approved_for_reuse':False,
                'method':'No retiming: exact native source/model frame registration, rejecting inconsistent scene evidence; fallback uses only the declared same-shot ImageGen plate projected by actual source features. Non-mask pixels retain native base. Actual outcome review required.'}
        write_json(output.with_suffix('.provenance.json'),record);attempt['state']='completed';return record
    except BaseException:
        attempt['state']='failed';raise
    finally:
        for cap in caps+[c for _,c in model_caps]:cap.release()
        if enc.poll() is None:enc.terminate()
        attempt['seconds']=time.perf_counter()-start;write_json(ledger_path,ledger)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run');p.add_argument('spec');p.add_argument('--extension-reason',required=True)
    args=p.parse_args();run=ROOT/'runs'/args.run
    with run_operation(run):print(execute(run,args.spec,args.extension_reason))
