"""Source-bound local repair recipes, risk probes and a durable trial budget."""
import os
import subprocess
import sys
import time
from pathlib import Path

from . import media
from . import repair_frames, repair_masks
from .common import (CODE_ROOT, ROOT, file_hash, guarded, inside, object_hash, read_json,
                     require, utc_now, write_json)


def preflight(run, detect_cuts=False):
    inv = read_json(run / 'analysis/inventory.json')
    meta = read_json(run / 'analysis/media.json')
    events = {0.: {'start'}, meta['duration']: {'end'}}
    def event(t, reason):
        t = max(0., min(float(t), meta['duration']))
        events.setdefault(t, set()).add(reason)
    for shot in inv.get('shots', []):
        event(shot['start'], 'shot_or_pose_cut'); event(shot['end'], 'shot_or_pose_cut')
    if detect_cuts:
        source = inside(run, read_json(run/'run.json')['source'])
        key = object_hash({'source':file_hash(source),'detector':file_hash(Path(media.__file__))})
        cache = run.parent.parent/'state/repair-preflight'/f'{key}.json'
        points = read_json(cache) if cache.exists() else media.scene_points(source,meta['duration'])
        if not cache.exists(): write_json(cache,points)
        for point in points: event(point,'candidate_visual_cut_not_title_boundary')
    if 'moving_watermark' in inv.get('content_features',[]):
        event(0,'moving_watermark_full_frame_edges'); event(meta['duration'],'moving_watermark_full_frame_edges')
    for item in inv.get('text_instances', []):
        for t in item.get('source_interval', [item['start'], item['end']]):
            event(t, 'source_text_boundary:'+item['id'])
        for pose in item.get('trajectory', []):
            event(pose['time'], 'trajectory_extreme_or_occlusion:'+item['id'])
        if 'watermark' in item.get('text_role', '') or 'watermark' in item.get('action', ''):
            event(item['start'], 'watermark_edge_entry:'+item['id'])
            event(item['end'], 'watermark_edge_exit:'+item['id'])
    fps = float(meta.get('fps', 30))
    return {'source_sha256': read_json(run/'run.json')['source_sha256'],
            'windows': [{'start': max(0, t-2/fps), 'end': min(meta['duration'], t+3/fps),
                         'event': t, 'reasons': sorted(reasons)} for t, reasons in sorted(events.items())],
            'required_manual_checks': ['Verify actual product/pose cuts separately from title boundaries',
                'Cover blurred glyph/outline entry independently from target caption timing',
                'Inspect all four full-frame edges, rotation extremes and protected brands',
                'Review continuous complex-motion intervals and final encoded video after probes'],
            'automatic_pass': False}


def _load(run, relative):
    recipe = read_json(inside(run, relative))
    source = inside(run, read_json(run/'run.json')['source'])
    require(file_hash(source) == recipe.get('source_sha256'), 'Repair recipe source changed')
    require(recipe.get('operations') and recipe.get('shots'), 'Explicit operations and actual shot/pose boundaries required')
    require(all(op.get('method') in ('temporal_frame', 'temporal_median', 'telea', 'lama',
                                    'source_restore', 'horizontal_fill', 'exposure_patch', 'poisson_patch')
                and op.get('reason') for op in recipe['operations']), 'Select an explained repair method')
    for op in recipe['operations']:
        shot = next((s for s in recipe['shots'] if s['id'] == op.get('shot')), None)
        require(shot and shot['start'] <= op['start'] < op['end'] <= shot['end'], 'Repair crosses a shot/pose cut')
        donors = [op['donor_time']] if op['method'] == 'temporal_frame' else op.get('donor_interval', [])
        require(op['method'] != 'temporal_median' or len(donors) == 2 and donors[0] < donors[1], 'Median donor interval required')
        require(all(shot['start'] <= t < shot['end'] for t in donors), 'Donor crosses a shot/pose cut')
        if 'frame_interval' in op:
            interval=op['frame_interval']
            require(isinstance(interval,list) and len(interval)==2 and
                    all(type(n) is int for n in interval) and 0<=interval[0]<interval[1],
                    'Frame interval must be half-open nonnegative integers')
    for name in ('base_video', 'proposal_video'):
        if name in recipe:
            asset = recipe[name]
            require(file_hash(inside(run, asset['path'])) == asset['sha256'], 'Repair dependency changed: '+name)
    require(not any(op['method'] in ('exposure_patch','poisson_patch') for op in recipe['operations']) or 'proposal_video' in recipe,
            'Proposal patch requires a hash-bound proposal video')
    for op in recipe['operations']:
        if op['method']=='poisson_patch':
            require(op.get('experimental') is True, 'Poisson patch remains an explicit experimental operation')
    return recipe, source


def _active(op, n, t):
    if 'frame_interval' in op:
        return op['frame_interval'][0]<=n<op['frame_interval'][1]
    return op['start']<=t<op['end']


def _geometry(op, t):
    poses = op.get('trajectory', [])
    if not poses:
        return op
    require(all(a['time'] < b['time'] for a, b in zip(poses, poses[1:])), 'Trajectory times must increase')
    before = max((p for p in poses if p['time'] <= t), key=lambda p: p['time'], default=poses[0])
    after = min((p for p in poses if p['time'] >= t), key=lambda p: p['time'], default=poses[-1])
    f = 0 if before['time'] == after['time'] else (t-before['time'])/(after['time']-before['time'])
    return {**op, 'bbox': [a+(b-a)*f for a,b in zip(before['bbox'],after['bbox'])],
            'angle': before.get('angle',0)+(after.get('angle',0)-before.get('angle',0))*f}


def _mask(frame, op, t, cv2, np):
    value = _geometry(op, t)
    mask = np.zeros(frame.shape[:2], np.uint8)
    if value['method'] in ('source_restore', 'horizontal_fill', 'exposure_patch'):
        x,y,w,h = value['bbox']
        require(all(type(v) is int for v in (x,y,w,h)) and x>=0 and y>=0 and w>0 and h>0
                and x+w<=frame.shape[1] and y+h<=frame.shape[0], 'Invalid half-open repair rectangle')
        mask[y:y+h,x:x+w] = 255
        polygon = None
    elif value.get('polygon'):
        polygon = np.asarray(value['polygon'], np.int32)
    else:
        x,y,w,h = value['bbox']
        require(w > 0 and h > 0, 'Positive mask geometry required')
        polygon = cv2.boxPoints(((x+w/2,y+h/2),(w,h),value.get('angle',0))).astype(np.int32)
    if polygon is not None:
        cv2.fillPoly(mask, [polygon], 255)
    if value.get('mask_selector'):
        mask = repair_masks.select(frame, mask, value['mask_selector'], cv2, np)
    for protection in value.get('protected_selectors', []):
        region = np.zeros_like(mask)
        x,y,w,h = protection['bbox']
        require(all(type(v) is int for v in (x,y,w,h)) and x>=0 and y>=0 and w>0 and h>0
                and x+w<=frame.shape[1] and y+h<=frame.shape[0], 'Invalid selector protection box')
        region[y:y+h,x:x+w] = 255
        mask[repair_masks.select(frame,region,protection['selector'],cv2,np)>0] = 0
    # Protected source content is copied back exactly, including feathered model edges.
    for x,y,w,h in value.get('protected_regions', []):
        require(x >= 0 and y >= 0 and w > 0 and h > 0, 'Invalid protected region')
        mask[round(y):round(y+h),round(x):round(x+w)] = 0
    return mask


def _special(original, proposal, op, cv2, np):
    """Parameterized legacy operations; intervals/coordinates belong in recipes."""
    if op['method'] == 'source_restore':
        return original
    x,y,w,h = op['bbox']
    result = original.copy()
    if op['method'] == 'horizontal_fill':
        a,b = op['left_columns']; c,d = op['right_columns']
        require(0<=a<b<=original.shape[1] and 0<=c<d<=original.shape[1], 'Invalid clean margins')
        left = original[y:y+h,a:b].mean(axis=1)
        right = original[y:y+h,c:d].mean(axis=1)
        weight = np.linspace(0,1,w)[None,:,None]
        result[y:y+h,x:x+w] = np.rint(left[:,None,:]*(1-weight)+right[:,None,:]*weight).astype(np.uint8)
        return result
    edge, feather = op['edge'], op['feather']
    require(0<=edge<edge+feather<=original.shape[0] and feather>0, 'Invalid exposure transition')
    a,b = op['exposure_rows']
    require(0<=a<b<=original.shape[0], 'Invalid exposure reference')
    mask = np.ones(original.shape[:2], np.float32)
    mask[edge:edge+feather] = np.linspace(1,0,feather)[:,None]
    mask[edge+feather:] = 0
    delta = np.median(original[a:b].astype(float)-proposal[a:b], axis=(0,1))
    corrected = np.clip(proposal.astype(float)+delta,0,255)
    if op.get('local_correction'):
        value = op['local_correction']; height = value['height']; a,b = value['exclude_rows']
        require(0<=a<b<=height<=original.shape[0] and value['sigma']>0, 'Invalid local exposure support')
        valid = np.ones((height,original.shape[1]),np.float32); valid[a:b,:] = 0
        difference = (original[:height].astype(np.float32)-proposal[:height].astype(np.float32))*valid[:,:,None]
        support = cv2.GaussianBlur(valid,(0,0),value['sigma'])
        correction = cv2.GaussianBlur(difference,(0,0),value['sigma'])/np.maximum(support[:,:,None],.001)
        corrected[:height] = np.clip(proposal[:height].astype(float)+correction,0,255)
    return np.rint(original*(1-mask[:,:,None])+corrected*mask[:,:,None]).astype(np.uint8)


def _engine():
    from .runtime import vision_path
    sys.path.insert(0, str(vision_path(CODE_ROOT)))
    import cv2
    import numpy as np
    return {'repair':file_hash(Path(__file__)), 'frames':file_hash(Path(repair_frames.__file__)),
            'masks':file_hash(Path(repair_masks.__file__)),
            'media':file_hash(Path(media.__file__)), 'opencv':cv2.__version__, 'numpy':np.__version__,
            'encoder':media.command(['ffmpeg','-version']).stdout}


@guarded
def execute(run, relative, probe=False, extension_reason=None):
    from .resources import heavy
    from .timing import measure
    recipe, source = _load(run, relative)
    recipe_hash = file_hash(inside(run, relative))
    model = CODE_ROOT/'.runtime/models/inpaint/lama_fp32.onnx'
    uses_lama = any(op['method']=='lama' for op in recipe['operations'])
    require(not uses_lama, 'New image repair belongs to Codex: use codex-packet --stage image. LaMa inference is retired.')
    identity = object_hash({'recipe': recipe_hash, 'implementation': _engine(), 'probe': probe,
                            'model':file_hash(model) if uses_lama else None,
                            'encoder':media.command(['ffmpeg','-version']).stdout})[:24]
    parent = run/'outputs/local-repair'
    folder = parent/identity
    candidates = [folder, *sorted(parent.glob(identity+'-rebuild-*'))]
    for candidate in reversed(candidates):
        record = candidate/'preparation.json'
        if not record.exists(): continue
        result = read_json(record)
        if any(not inside(run,a['path']).is_file() for a in result['artifacts']):
            continue
        for a in result['artifacts']:
            require(file_hash(inside(run,a['path'])) == a['sha256'], 'Repair checkpoint changed')
        return {**result,'reused':True}
    revision = 1
    while folder.exists():
        folder = parent/(identity+f'-rebuild-{revision:04}')
        revision += 1
    record = folder/'preparation.json'
    ledger_path = run.parent.parent/'state/repair-trials'/f'{run.name}.json'
    ledger = read_json(ledger_path) if ledger_path.exists() else {'attempts': [], 'extensions': []}
    require(not any(a['state'] == 'running' for a in ledger['attempts']), 'Reconcile interrupted local repair before retry')
    spent = sum(a.get('seconds',0) for a in ledger['attempts'])
    limit = 4+len(ledger['extensions'])
    if len(ledger['attempts']) >= limit or spent >= 600+300*len(ledger['extensions']):
        require(extension_reason and len(extension_reason.strip()) >= 12, 'Local trial budget exhausted; inspect failures or explain a bounded extension')
        ledger['extensions'].append({'reason': extension_reason, 'at': utc_now()})
    attempt = {'recipe': relative, 'sha256': recipe_hash, 'probe': probe, 'state': 'running',
               'output':record.relative_to(run).as_posix(),
               'pid':os.getpid(), 'started_at': utc_now()}
    ledger['attempts'].append(attempt); write_json(ledger_path,ledger)
    started = time.perf_counter()
    try:
        with heavy(run,'visual.repair_recipe'), measure(run,'visual.repair_recipe'):
            folder.mkdir(parents=True,exist_ok=True)
            frozen=folder/'recipe.json'
            frozen.write_bytes(inside(run,relative).read_bytes())
            require(file_hash(frozen) == recipe_hash and read_json(frozen) == recipe,
                    'Repair recipe changed before freezing')
            deadline = started + max(0,600+300*len(ledger['extensions'])-spent)
            result = _execute(run, recipe, source, frozen.relative_to(run).as_posix(), folder, probe, deadline)
            require(file_hash(source) == recipe['source_sha256'], 'Repair source changed during execution')
            for name in ('base_video', 'proposal_video'):
                if name in recipe:
                    require(file_hash(inside(run,recipe[name]['path'])) == recipe[name]['sha256'], 'Repair dependency changed during execution')
        write_json(record,result)
        attempt.update(state='completed', output=record.relative_to(run).as_posix())
        return result
    except BaseException:
        attempt['state'] = 'failed'
        raise
    finally:
        attempt['seconds'] = round(time.perf_counter()-started,6)
        write_json(ledger_path,ledger)


def _execute(run, recipe, source, relative, folder, probe, deadline=None):
    # Optional native/model packages are imported only for local repair execution.
    from .runtime import vision_path
    sys.path.insert(0, str(vision_path(CODE_ROOT)))
    import cv2
    import numpy as np
    from PIL import Image
    from .visual_audit import _timestamps
    source_times = _timestamps(source)
    base_path = inside(run,recipe['base_video']['path']) if recipe.get('base_video') else source
    times = _timestamps(base_path) if base_path != source else source_times
    meta=media.probe(source)
    require(len(source_times)*meta['width']*meta['height']*3 <= 512*1024**2,
            'Repair decoded memory budget exceeded; select a bounded source clip first')
    fps = media.probe(base_path)['fps']
    require(all(abs((b-a)-1/fps)<.002 for a,b in zip(times,times[1:])), 'Variable frame rate repair needs explicit normalization')
    cap = cv2.VideoCapture(str(source)); frames = []
    while True:
        ok, frame = cap.read()
        if not ok: break
        frames.append(frame)
    cap.release(); require(len(frames)==len(source_times), 'Decoded frame coverage mismatch')
    require(len(times)>=len(frames) and len(times)-len(frames)<=recipe.get('hold_source_tail_frames',0),
            'Base/source coverage differs without an explicit bounded tail hold')
    require(all(abs(a-b)<.002 for a,b in zip(times,source_times)), 'Base/source frame clocks differ')
    for op in recipe['operations']:
        if 'frame_interval' in op:
            a,b=op['frame_interval']
            shot=next(s for s in recipe['shots'] if s['id']==op['shot'])
            require(b<=len(times) and shot['start']<=times[a] and times[b-1]<shot['end'],
                    'Frame interval crosses shot/pose cut or video coverage')
    selected = set(range(len(times)))
    if probe:
        risks = preflight(run,detect_cuts=True)['windows']
        boundaries = [op[k] for op in recipe['operations'] for k in ('start','end')]
        boundaries += [p['time'] for op in recipe['operations'] for p in op.get('trajectory',[])]
        boundaries += [times[n] for op in recipe['operations'] for n in op.get('frame_interval',[])
                       if n<len(times)]
        selected = {n for n,t in enumerate(times) if any(w['start']<=t<=w['end'] for w in risks)
                    or any(abs(t-e)<=2/fps for e in boundaries)}
    folder.mkdir(parents=True,exist_ok=True)
    engine = _engine()
    model = CODE_ROOT/'.runtime/models/inpaint/lama_fp32.onnx'
    model_hash = file_hash(model) if any(o['method']=='lama' for o in recipe['operations']) else None
    def frame_key(n):
        active = []
        for op in recipe['operations']:
            if _active(op,n,times[n]):
                value = {k:v for k,v in _geometry(op,times[n]).items()
                         if k not in ('start','end','reason','trajectory','frame_interval')}
                if op['method']=='lama': value['model_sha256'] = model_hash
                if op['method'] in ('exposure_patch','poisson_patch'): value['proposal'] = recipe['proposal_video']['sha256']
                active.append(value)
        return object_hash({'source':recipe['source_sha256'], 'frame':n, 'pts':times[n],
                            'base':recipe.get('base_video',{}).get('sha256'),
                            'hold':recipe.get('hold_source_tail_frames',0),
                            'engine':engine, 'operations':active})
    keys = {n:frame_key(n) for n in selected}
    previous = repair_frames.PreviousFrames(run,keys,cv2)
    missing = set(selected)-set(previous.rows)
    needed = {i for i,op in enumerate(recipe['operations'])
              if any(_active(op,n,times[n]) for n in missing)}
    donors = {}
    for i,op in enumerate(recipe['operations']):
        if i not in needed: continue
        nearest = lambda t: min(range(len(source_times)),key=lambda n: abs(source_times[n]-t))
        if op['method']=='temporal_frame': donors[i] = frames[nearest(op['donor_time'])]
        elif op['method']=='temporal_median':
            ns=[n for n,t in enumerate(source_times) if op['donor_interval'][0]<=t<op['donor_interval'][1]]
            require(ns, 'Empty temporal donor interval')
            ns=[ns[n] for n in np.linspace(0,len(ns)-1,min(19,len(ns))).astype(int)]
            donors[i]=np.median(np.stack([frames[n] for n in ns]),axis=0).astype(np.uint8)
        elif op['method']=='lama':
            require(False, 'LaMa inference is retired; use Codex image editing')
    artifacts=[]; trace=[]; index=[]; process=None
    base_cap = cv2.VideoCapture(str(base_path)) if base_path != source else None
    proposal_cap = cv2.VideoCapture(str(inside(run,recipe['proposal_video']['path']))) if recipe.get('proposal_video') else None
    base_position = proposal_position = -1
    if not probe:
        h,w=frames[0].shape[:2]
        process=subprocess.Popen(['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','bgr24','-s',f'{w}x{h}',
            '-r',str(fps),'-i','pipe:0','-an','-c:v','ffv1',str(folder/'visual-master.mkv')],stdin=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        for n in sorted(selected):
            require(deadline is None or time.perf_counter() < deadline,
                    'Local repair time budget exhausted; partial output is not a checkpoint')
            original=frames[min(n,len(frames)-1)]
            baseline = original
            if base_cap:
                while base_position < n-1:
                    require(base_cap.grab(), 'Missing base frame'); base_position += 1
                ok,baseline = base_cap.read(); base_position += 1
                require(ok and baseline.shape == original.shape, 'Base frame dimensions/coverage differ')
            current=previous.get(n)
            reused = current is not None
            if not reused: current=baseline.copy()
            changed=np.zeros(original.shape[:2],bool)
            for i,op in enumerate(recipe['operations']):
                if not _active(op,n,times[n]): continue
                mask=_mask(original,op,times[n],cv2,np); active=mask>0
                if not np.any(active): continue
                changed|=active
                if reused: continue
                if op['method'] in ('source_restore','horizontal_fill','exposure_patch','poisson_patch'):
                    proposal = None
                    if op['method'] in ('exposure_patch','poisson_patch'):
                        while proposal_position < n-1:
                            require(proposal_cap.grab(), 'Missing proposal frame'); proposal_position += 1
                        if proposal_position < n:
                            ok,proposal_frame = proposal_cap.read(); proposal_position += 1
                            require(ok, 'Missing proposal frame')
                        proposal=cv2.resize(proposal_frame,(original.shape[1],original.shape[0]))
                    if op['method']=='poisson_patch':
                        x,y,w,h = cv2.boundingRect(mask)
                        repaired=cv2.seamlessClone(proposal,current,mask.copy(),(x+w//2,y+h//2),cv2.NORMAL_CLONE)
                    else:
                        repaired=_special(original,proposal,op,cv2,np)
                elif i in donors: repaired=donors[i]
                elif op['method']=='lama': require(False, 'LaMa inference is retired')
                else: repaired=cv2.inpaint(current,mask,3,cv2.INPAINT_TELEA)
                current[active]=repaired[active];changed|=active
            require(np.array_equal(current[~changed],baseline[~changed]), 'Repair changed undeclared pixels')
            trace.append({'frame':n,'pts':times[n],'mask_bbox':list(cv2.boundingRect(changed.astype(np.uint8)))})
            index.append({'frame':n,'key':keys[n],'pixels_sha256':repair_frames.pixel_hash(current)})
            if probe:
                path=folder/f'probe-{n:06}.png';Image.fromarray(cv2.cvtColor(current,cv2.COLOR_BGR2RGB)).save(path)
                artifacts.append({'path':path.relative_to(run).as_posix(),'sha256':file_hash(path)})
            else: process.stdin.write(current.tobytes())
    finally:
        if base_cap: base_cap.release()
        if proposal_cap: proposal_cap.release()
        if process:
            process.stdin.close(); error=process.stderr.read().decode(errors='replace')
            process.stderr.close()
            require(process.wait()==0,'Repair encoding failed: '+error[-400:])
        previous.close()
    if process:
        path=folder/'visual-master.mkv';artifacts.append({'path':path.relative_to(run).as_posix(),'sha256':file_hash(path)})
    trace_path=folder/'changed-regions.json';write_json(trace_path,trace)
    artifacts.append({'path':trace_path.relative_to(run).as_posix(),'sha256':file_hash(trace_path)})
    index_path=folder/'frame-index.json';write_json(index_path,index)
    frame_index={'path':index_path.relative_to(run).as_posix(),'sha256':file_hash(index_path)}
    artifacts.append(frame_index)
    return {'source_sha256':recipe['source_sha256'],'target_language':None,'contains_target_typography':False,
            'approved_for_reuse':False,'probe_only':probe,'artifacts':artifacts,
            'frame_index':frame_index,
            'incremental':{'reused_frames':previous.hits,'computed_frames':len(selected)-previous.hits,
                           'total_frames':len(selected),'extra_cached_media':0,
                           'previous_output':previous.record['output'] if previous.hits else None},
            **({'output':artifacts[0]} if not probe else {}),
            'inputs':[{'path':read_json(run/'run.json')['source'],'sha256':recipe['source_sha256']},
                      {'path':relative,'sha256':file_hash(inside(run,relative))}]
                     + [recipe[k] for k in ('base_video','proposal_video') if k in recipe],
            'method':'Source-bound local recipe; only declared mask pixels changed; all observations remain pending',
            'automatic_pass':False}


def _alive(pid):
    require(type(pid) is int and pid > 0, 'Unknown local repair owner; inspect before recovery')
    if os.name == 'nt':
        import csv
        result = subprocess.run(['tasklist','/FI',f'PID eq {pid}','/FO','CSV','/NH'],
                                capture_output=True,text=True,check=True)
        return any(len(row)>1 and row[1]==str(pid) for row in csv.reader(result.stdout.splitlines()))
    try:
        os.kill(pid,0)
        return True
    except ProcessLookupError:
        return False


@guarded
def reconcile(run, reason):
    """Resolve a dead local process without clearing locks or retrying any model."""
    require(isinstance(reason,str) and len(reason.strip())>=12, 'Explain the interrupted local repair')
    path=run.parent.parent/'state/repair-trials'/f'{run.name}.json'
    ledger=read_json(path)
    for attempt in ledger['attempts']:
        if attempt['state']!='running': continue
        require(not _alive(attempt.get('pid')), 'Local repair process is still running')
        record=inside(run,attempt['output'])
        completed=False
        if record.exists():
            saved=read_json(record)
            completed=bool(saved.get('artifacts')) and all(file_hash(inside(run,a['path']))==a['sha256'] for a in saved['artifacts'])
            require(completed,'Interrupted repair checkpoint changed')
        attempt.update(state='completed' if completed else 'interrupted',recovery_reason=reason,recovered_at=utc_now())
    write_json(path,ledger)
    return {'attempts':ledger['attempts'],'paid_retry':False,'automatic_pass':False}
