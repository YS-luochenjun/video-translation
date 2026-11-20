"""Bounded source-frame video repair probe; never implies visual approval.

All source geometry, shot boundaries, donor offsets and thresholds are task data.
No model inference, frame repetition, or target lettering is performed here.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from video_localizer.common import file_hash, inside, read_json, require, write_json, run_operation
from video_localizer.repair_masks import select


def execute(run, relative, extension_reason=None, sequence=False):
    import cv2
    import numpy as np
    spec = read_json(inside(run, relative))
    source = inside(run, spec['source']['path'])
    require(file_hash(source) == spec['source']['sha256'], 'Source changed')
    frames_requested = spec['probe_frames']
    require(frames_requested and len(frames_requested) <= (90 if sequence else 12),
            'Use at most twelve probe frames or ninety bounded sequence frames')
    if sequence:
        require(all(b == a+1 for a, b in zip(frames_requested, frames_requested[1:])),
                'A sequence must cover consecutive native source frames')
    folder = inside(run, spec['output'])
    require(not folder.exists(), 'Preserve previous probes; use a new output version')
    folder.mkdir(parents=True)
    ledger_path = ROOT / 'state/repair-trials' / (run.name + '.json')
    ledger = read_json(ledger_path) if ledger_path.exists() else {'attempts': [], 'extensions': []}
    require(not any(x['state'] == 'running' for x in ledger['attempts']), 'Another repair is running')
    spent = sum(x.get('seconds', 0) for x in ledger['attempts'])
    if (len(ledger['attempts']) >= 4 + len(ledger['extensions'])
            or spent >= 600 + 300 * len(ledger['extensions'])):
        require(isinstance(extension_reason, str) and len(extension_reason.strip()) >= 12,
                'Local trial budget reached; explain the bounded next variable')
        from video_localizer.common import utc_now
        ledger['extensions'].append({'reason': extension_reason, 'at': utc_now()})
    started = time.perf_counter()
    attempt = {'recipe': relative, 'sha256': file_hash(inside(run, relative)), 'probe': True,
               'state': 'running', 'output': spec['output'], 'method': 'same_shot_optical_flow_donors'}
    ledger['attempts'].append(attempt)
    write_json(ledger_path, ledger)
    rows = []
    cap = cv2.VideoCapture(str(source))
    require(cap.isOpened(), 'Cannot decode source')
    if any(scene.get('proposal_video') for scene in spec['scenes']):
        require(abs(cap.get(cv2.CAP_PROP_FPS) - spec['fps']) < .001,
                'Source and proposal frame rates must agree')
    try:
        for scene in spec['scenes']:
            a, b = scene['frames']
            required = [n for n in spec['probe_frames'] if a <= n < b]
            if not required:
                continue
            require((b-a) * spec['width'] * spec['height'] * 3 < 512*1024**2, 'Scene exceeds decoded memory cap')
            cap.set(cv2.CAP_PROP_POS_FRAMES, a)
            frames, masks, guides = [], [], []
            for n in range(a, b):
                ok, frame = cap.read()
                require(ok and frame.shape[:2] == (spec['height'], spec['width']), 'Missing or differently sized native source frame')
                mask = np.zeros(frame.shape[:2], np.uint8)
                for box in scene['regions']:
                    x, y, w, h = box
                    region = np.zeros_like(mask)
                    region[y:y+h, x:x+w] = 255
                    mask |= select(frame, region, spec['selector'], cv2, np)
                for x, y, w, h in scene.get('protected_regions', []):
                    require(x >= 0 and y >= 0 and w > 0 and h > 0 and
                            x+w <= spec['width'] and y+h <= spec['height'],
                            'Invalid protected region')
                    mask[y:y+h, x:x+w] = 0
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                guide = cv2.inpaint(gray, mask, 3, cv2.INPAINT_TELEA)
                frames.append(frame)
                masks.append(mask)
                guides.append(cv2.resize(guide, None, fx=.5, fy=.5, interpolation=cv2.INTER_AREA))
            for n in required:
                require(time.perf_counter() - started + spent < 600+300*len(ledger['extensions']), 'Repair trial deadline reached')
                i = n-a
                original, mask = frames[i], masks[i]
                repair = cv2.inpaint(original, mask, 3, cv2.INPAINT_TELEA)
                reference_log = None
                if scene.get('clean_reference') or scene.get('proposal_video'):
                    ref_asset = scene.get('clean_reference') or scene['proposal_video']
                    ref_path = inside(run, ref_asset['path'])
                    require(file_hash(ref_path) == ref_asset['sha256'], 'Clean reference changed')
                    yy0, xx0 = np.mgrid[:spec['height'], :spec['width']].astype(np.float32)
                    affine_log = None
                    if scene.get('proposal_video'):
                        proposal_cap = cv2.VideoCapture(str(ref_path))
                        require(proposal_cap.isOpened(), 'Cannot decode proposal video')
                        try:
                            require(abs(proposal_cap.get(cv2.CAP_PROP_FPS) - spec['fps']) < .001,
                                    'Proposal must use the native source frame rate')
                            proposal_frame = n - scene['proposal_source_start_frame']
                            require(0 <= proposal_frame < round(proposal_cap.get(cv2.CAP_PROP_FRAME_COUNT)),
                                    'Proposal does not cover the source frame')
                            proposal_cap.set(cv2.CAP_PROP_POS_FRAMES, proposal_frame)
                            valid, proposal = proposal_cap.read()
                            require(valid, 'Missing proposal video frame')
                            proposal = cv2.resize(proposal, (spec['width'], spec['height']))
                            blur_points = scene.get('proposal_blur', [])
                            if blur_points:
                                require(all(type(p['frame']) is int and
                                            0 <= p['sigma'] <= 15 for p in blur_points) and
                                        all(p['frame'] < q['frame'] for p, q in zip(blur_points, blur_points[1:])),
                                        'Invalid source-matched proposal blur observations')
                                sigma = float(np.interp(n, [p['frame'] for p in blur_points],
                                                        [p['sigma'] for p in blur_points]))
                                if sigma:
                                    proposal = cv2.GaussianBlur(proposal, (0, 0), sigma)
                        finally:
                            proposal_cap.release()
                        reference_frame = n
                    else:
                        ref = cv2.imread(str(ref_path))
                        require(ref is not None, 'Cannot decode clean reference')
                        ref = cv2.resize(ref, (spec['width'], spec['height']))
                        key = scene['reference_frame'] - a
                        require(0 <= key < len(frames), 'Reference crosses scene')
                        reference_frame = scene['reference_frame']
                    if scene.get('proposal_video'):
                        pass
                    elif spec.get('motion_projection') == 'source_affine':
                        detector = cv2.SIFT_create(nfeatures=1600)
                        ka, da = detector.detectAndCompute(cv2.cvtColor(original, cv2.COLOR_BGR2GRAY), 255-mask)
                        kb, db = detector.detectAndCompute(cv2.cvtColor(frames[key], cv2.COLOR_BGR2GRAY), 255-masks[key])
                        matches = cv2.BFMatcher().knnMatch(da, db, k=2) if da is not None and db is not None else []
                        good = [pair[0] for pair in matches if len(pair)==2 and pair[0].distance < .7*pair[1].distance]
                        matrix, inliers = (cv2.estimateAffinePartial2D(np.float32([ka[x.queryIdx].pt for x in good]), np.float32([kb[x.trainIdx].pt for x in good]), method=cv2.RANSAC, ransacReprojThreshold=3) if len(good)>=6 else (None,None))
                        require(matrix is not None and int(inliers.sum())>=6, 'Insufficient real source motion matches')
                        flow = np.stack([matrix[0,0]*xx0+matrix[0,1]*yy0+matrix[0,2]-xx0, matrix[1,0]*xx0+matrix[1,1]*yy0+matrix[1,2]-yy0],axis=2).astype(np.float32)
                        affine_log = {'matrix':matrix.tolist(), 'inliers':int(inliers.sum()), 'matches':len(good)}
                    else:
                        dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
                        flow = cv2.resize(dis.calc(guides[i], guides[key], None), (spec['width'],spec['height'])) * 2
                        for channel in range(2):
                            flow[:,:,channel] = cv2.inpaint(flow[:,:,channel], mask, 3, cv2.INPAINT_TELEA)
                    if not scene.get('proposal_video'):
                        proposal = cv2.remap(ref, xx0+flow[:,:,0], yy0+flow[:,:,1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
                    clone_mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(15,15)))
                    for x, y, w, h in scene.get('protected_regions', []):
                        clone_mask[y:y+h, x:x+w] = 0
                    # Clone only bounded source glyph neighborhoods; never freeze a whole reference frame.
                    x0,y0,w0,h0 = cv2.boundingRect(clone_mask)
                    if w0 and h0:
                        repair = cv2.seamlessClone(proposal, original, clone_mask.copy(), (x0+w0//2,y0+h0//2), cv2.NORMAL_CLONE)
                        repair[clone_mask == 0] = original[clone_mask == 0]
                        mask = clone_mask
                    reference_log = {'asset': ref_asset, 'source_frame': reference_frame,
                                     'method': ('native-time video proposal plus Poisson local blend' if scene.get('proposal_video')
                                                else 'native-source-motion plus Poisson local blend'),
                                     'affine': affine_log}
                uncovered = mask > 0
                yy, xx = np.mgrid[:spec['height'], :spec['width']].astype(np.float32)
                donor_log = []
                for offset in ([] if reference_log else spec['donor_offsets']):
                    k = i + offset
                    if not 0 <= k < len(frames) or not np.any(uncovered):
                        continue
                    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
                    forward = dis.calc(guides[i], guides[k], None)
                    reverse = dis.calc(guides[k], guides[i], None)
                    f = cv2.resize(forward, (spec['width'],spec['height'])) * 2
                    rev = cv2.resize(reverse, (spec['width'],spec['height'])) * 2
                    mx, my = xx + f[:,:,0], yy + f[:,:,1]
                    warped = cv2.remap(frames[k], mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
                    donor_mask = cv2.remap(masks[k], mx, my, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=255)
                    back = cv2.remap(rev, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
                    cycle = np.linalg.norm(f+back, axis=2)
                    valid = uncovered & (donor_mask == 0) & (cycle < spec['max_cycle_error']) & (mx >= 0) & (mx < spec['width']-1) & (my >= 0) & (my < spec['height']-1)
                    repair[valid] = warped[valid]
                    uncovered[valid] = False
                    donor_log.append({'source_frame': a+k, 'accepted_pixels': int(valid.sum())})
                output = folder / ('probe-%06d.png' % n)
                cv2.imwrite(str(output), repair)
                if not sequence:
                    cv2.imwrite(str(folder / ('mask-%06d.png' % n)), mask)
                    preview = np.hstack([original, repair])
                    cv2.imwrite(str(folder / ('compare-%06d.jpg' % n)), preview)
                require(np.array_equal(repair[mask == 0], original[mask == 0]), 'Undeclared pixels changed')
                rows.append({'frame': n, 'mask_pixels': int((mask>0).sum()), 'fallback_inpaint_pixels': int(uncovered.sum()) if not reference_log else 0, 'reference': reference_log,
                             'donors': donor_log, 'output': {'path': str(output.relative_to(run)), 'sha256': file_hash(output)}})
        require(len(rows) == len(spec['probe_frames']), 'Probe source coverage incomplete')
        result = {'source': spec['source'], 'recipe': {'path': relative, 'sha256': file_hash(inside(run, relative))},
                  'implementation_sha256': file_hash(Path(__file__)),
                  'method': ('Native-time video proposal with local Poisson blend.' if any(s.get('proposal_video') for s in spec['scenes'])
                             else 'Same-shot source optical flow or clean-reference local blend; see per-frame records for fallback.'),
                  'probe_only': True, 'sequence': sequence, 'approved_for_reuse': False, 'rows': rows}
        write_json(folder / 'provenance.json', result)
        attempt['state'] = 'completed'
        return result
    except BaseException:
        attempt['state'] = 'failed'
        raise
    finally:
        cap.release()
        attempt['seconds'] = time.perf_counter() - started
        write_json(ledger_path, ledger)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run')
    parser.add_argument('spec')
    parser.add_argument('--extension-reason')
    parser.add_argument('--sequence', action='store_true')
    args = parser.parse_args()
    run = ROOT / 'runs' / args.run
    with run_operation(run):
        print(json.dumps(execute(run, args.spec, args.extension_reason, args.sequence), ensure_ascii=False, indent=2))
