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
from video_localizer.repair import _special


def registered_donor(original, donor, mask, bbox, cv2, np, projection='optical_flow', registration_reference=None):
    left, top, width, height = bbox
    target = original[top:top+height, left:left+width]
    reference = donor[top:top+height, left:left+width]
    local_mask = mask[top:top+height, left:left+width]
    if projection == 'source_affine':
        detector = cv2.SIFT_create(nfeatures=2000)
        excluded = cv2.dilate(local_mask, np.ones((21,21),np.uint8))
        target_keys, target_features = detector.detectAndCompute(cv2.cvtColor(target, cv2.COLOR_BGR2GRAY),255-excluded)
        anchor = registration_reference[top:top+height, left:left+width] if registration_reference is not None else reference
        donor_keys, donor_features = detector.detectAndCompute(cv2.cvtColor(anchor, cv2.COLOR_BGR2GRAY),None)
        matches = cv2.BFMatcher().knnMatch(target_features,donor_features,k=2) if target_features is not None and donor_features is not None else []
        good = [pair[0] for pair in matches if len(pair)==2 and pair[0].distance < .7*pair[1].distance]
        require(len(good)>=6,'Insufficient real donor registration matches')
        matrix,inliers = cv2.estimateAffinePartial2D(np.float32([target_keys[match.queryIdx].pt for match in good]),
                                                    np.float32([donor_keys[match.trainIdx].pt for match in good]),
                                                    method=cv2.RANSAC,ransacReprojThreshold=3)
        require(matrix is not None and int(inliers.sum())>=6,'Real donor motion could not be established')
        replacement = cv2.warpAffine(reference,matrix,(width,height),flags=cv2.INTER_LINEAR|cv2.WARP_INVERSE_MAP,
                                     borderMode=cv2.BORDER_REFLECT101)
        result = original.copy()
        result[top:top+height,left:left+width] = replacement
        return result
    require(projection == 'optical_flow','Unsupported donor projection')
    if registration_reference is None:
        target = cv2.inpaint(target, local_mask, 5, cv2.INPAINT_TELEA)
        motion_reference = reference
    else:
        motion_reference = registration_reference[top:top+height, left:left+width]
    scale = min(1, 540/width)
    dimensions = (round(width*scale), round(height*scale))
    target_gray = cv2.cvtColor(cv2.resize(target, dimensions), cv2.COLOR_BGR2GRAY)
    donor_gray = cv2.cvtColor(cv2.resize(motion_reference, dimensions), cv2.COLOR_BGR2GRAY)
    flow = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM).calc(target_gray, donor_gray, None)
    flow = cv2.resize(flow, (width, height))/scale
    grid_x, grid_y = np.meshgrid(np.arange(width, dtype=np.float32), np.arange(height, dtype=np.float32))
    replacement = cv2.remap(reference, grid_x+flow[:,:,0], grid_y+flow[:,:,1], cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_REFLECT101)
    result = original.copy()
    result[top:top+height, left:left+width] = replacement
    return result


def execute(run, relative, extension_reason=None, probe_frames=None):
    import cv2
    import numpy as np
    spec = read_json(inside(run, relative))
    for row in spec['regions']:
        require(row.get('repair_method', 'telea') in ('telea', 'source_restore', 'horizontal_fill'),
                'Unsupported streaming glyph repair method')
        require(not row.get('donor') or row.get('repair_method', 'telea') == 'telea',
                'Donor repair cannot also select a source reconstruction method')
        if row.get('repair_method', 'telea') != 'telea':
            bbox = row.get('bbox', [])
            require(len(bbox) == 4 and all(type(value) is int for value in bbox)
                    and bbox[0] >= 0 and bbox[1] >= 0 and bbox[2] > 0 and bbox[3] > 0
                    and bbox[0]+bbox[2] <= spec['width'] and bbox[1]+bbox[3] <= spec['height'],
                    'Invalid source reconstruction rectangle')
    paths = {k: inside(run, spec[k]['path']) for k in ('source','base_video')}
    for k, p in paths.items():
        require(file_hash(p) == spec[k]['sha256'], k+' changed')
    output = inside(run, spec['output'])
    if probe_frames:
        output = output.with_name(output.stem+'-probe.mp4')
    require(not output.exists(), 'Preserve previous output')
    ledger_path = ROOT/'state/repair-trials'/(run.name+'.json')
    ledger = read_json(ledger_path) if ledger_path.exists() else {'attempts':[], 'extensions':[]}
    require(not any(x['state']=='running' for x in ledger['attempts']), 'Repair is already running')
    spent = sum(x.get('seconds',0) for x in ledger['attempts'])
    if len(ledger['attempts']) >= 4+len(ledger['extensions']) or spent >= 600+300*len(ledger['extensions']):
        require(extension_reason and len(extension_reason.strip())>=12, 'A bounded repair extension needs evidence and next variable')
        ledger['extensions'].append({'reason':extension_reason,'at':utc_now()})
    attempt = {'recipe':relative,'sha256':file_hash(inside(run,relative)),'state':'running','pid':os.getpid(),
               'started_at':utc_now(),'output':str(output.relative_to(run)),
               'method':'source_glyph_masks_with_optional_registered_donors', 'probe_frames':probe_frames}
    ledger['attempts'].append(attempt)
    write_json(ledger_path,ledger)
    started = time.perf_counter()
    caps = {k:cv2.VideoCapture(str(p)) for k,p in paths.items()}
    for cap in caps.values():
        require(cap.isOpened() and abs(cap.get(cv2.CAP_PROP_FPS)-spec['fps'])<.001
                and round(cap.get(cv2.CAP_PROP_FRAME_COUNT))==spec['frames'], 'Native source/base coverage differs')
    width,height = spec['width'],spec['height']
    source_reader = cv2.VideoCapture(str(paths['source']))
    references = {}
    donors = {}
    registration_references = {}
    for row in spec['regions']:
        if row.get('mask_reference_frames'):
            references[row['id']] = []
            for frame_number in row['mask_reference_frames']:
                source_reader.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
                valid, image = source_reader.read()
                require(valid, 'Missing mask reference frame')
                references[row['id']].append(image)
        if row.get('donor'):
            donor_spec = row['donor']
            donor_path = inside(run, donor_spec['path'])
            require(file_hash(donor_path)==donor_spec['sha256'], 'Donor changed')
            if 'frame' in donor_spec:
                donor_reader = cv2.VideoCapture(str(donor_path))
                donor_reader.set(cv2.CAP_PROP_POS_FRAMES, donor_spec['frame'])
                valid, donor = donor_reader.read()
                donor_reader.release()
                require(valid, 'Missing donor frame')
            else:
                donor = cv2.imread(str(donor_path))
            require(donor is not None, 'Missing donor image')
            donors[row['id']] = cv2.resize(donor, (width,height))
            if row.get('registration_reference'):
                anchor_spec = row['registration_reference']
                anchor_path = inside(run, anchor_spec['path'])
                require(file_hash(anchor_path)==anchor_spec['sha256'], 'Registration reference changed')
                anchor = cv2.imread(str(anchor_path))
                require(anchor is not None and anchor.shape[:2]==(height,width), 'Registration reference must be a native source frame')
                registration_references[row['id']] = anchor
    source_reader.release()
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
        for n in (probe_frames or range(spec['frames'])):
            require(time.perf_counter()-started+spent < 600+300*len(ledger['extensions']), 'Bounded repair time exceeded')
            if probe_frames:
                for cap in caps.values():
                    cap.set(cv2.CAP_PROP_POS_FRAMES,n)
            ok,original = caps['source'].read()
            base_ok,base = caps['base_video'].read()
            require(ok and base_ok and original.shape==base.shape==(height,width,3), 'Missing native frame')
            combined = np.zeros((height,width),np.uint8)
            inpaint_mask = np.zeros_like(combined)
            row_masks = []
            for row in spec['regions']:
                if not row['source_frames'][0]<=n<row['source_frames'][1]:
                    continue
                polygon = row.get('polygons',{}).get(str(n), row.get('polygon'))
                require(polygon is not None, 'Missing reviewed source geometry')
                region = np.zeros_like(combined)
                cv2.fillConvexPoly(region,np.rint(polygon).astype(np.int32),255)
                mask = np.zeros_like(combined)
                for reference in references.get(row['id'],[original]):
                    mask |= select(reference,region,row['selector'],cv2,np)
                if row.get('mask_shape') == 'bounding_box' and np.any(mask):
                    mask_left, mask_top, mask_width, mask_height = cv2.boundingRect(mask)
                    margin = row.get('mask_margin',0)
                    mask[max(0,mask_top-margin):min(height,mask_top+mask_height+margin),
                         max(0,mask_left-margin):min(width,mask_left+mask_width+margin)] = 255
                    mask &= region
                combined |= mask
                if row.get('repair_method', 'telea') == 'telea':
                    inpaint_mask |= mask
                row_masks.append((row,mask))
                counts[row['id']] += int((mask>0).sum())
            current = base.copy()
            if np.any(inpaint_mask):
                repaired = cv2.inpaint(base, inpaint_mask, spec.get('inpaint_radius',2), cv2.INPAINT_TELEA)
                current[inpaint_mask>0] = repaired[inpaint_mask>0]
            for row, mask in row_masks:
                if row.get('repair_method', 'telea') != 'telea' and np.any(mask):
                    replacement = _special(original, None, {**row, 'method': row['repair_method']}, cv2, np)
                    current[mask>0] = replacement[mask>0]
                if row['id'] in donors and np.any(mask):
                    replacement = registered_donor(original, donors[row['id']], mask,
                                                    row['registration_bbox'],cv2,np,row.get('motion_projection','optical_flow'),
                                                    registration_references.get(row['id']))
                    if row.get('blend') == 'poisson':
                        blend_left, blend_top, blend_width, blend_height = cv2.boundingRect(mask)
                        replacement = cv2.seamlessClone(replacement, original, mask.copy(),
                                                       (blend_left+blend_width//2,blend_top+blend_height//2),cv2.NORMAL_CLONE)
                    current[mask>0] = replacement[mask>0]
                if row.get('original_panel_black_boundary'):
                    boundary = row['original_panel_black_boundary']
                    sample = row['original_panel_clean_sample']
                    sample_left, sample_top, sample_width, sample_height = sample
                    color = np.median(original[sample_top:sample_top+sample_height,
                                               sample_left:sample_left+sample_width].reshape(-1,3),axis=0).astype(np.uint8)
                    known_background = mask.copy()
                    known_background[:boundary] = 0
                    current[known_background>0] = color
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
                'inputs':[spec['source'],spec['base_video']]+[row['donor'] for row in spec['regions'] if row.get('donor')]
                         +[row['registration_reference'] for row in spec['regions'] if row.get('registration_reference')],
                'output':{'path':str(output.relative_to(run)),'sha256':file_hash(output)},
                'native_frames':len(probe_frames) if probe_frames else spec['frames'],
                'probe_frames':probe_frames,'changed_pixels_by_instance':counts,'inspection_frames':snapshots,
                'contains_target_typography':False,'approved_for_reuse':False,
                'method':'Source-bound masks use Telea, declared registered donors, native source restoration or existing same-row horizontal reconstruction only inside masks. Actual naturalness and remaining letters require review.'}
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
    parser.add_argument('--probe-frames', nargs='+', type=int)
    args=parser.parse_args();run=get_run(args.run)
    with run_operation(run):
        print(execute(run,args.recipe,args.extension_reason,args.probe_frames))
