"""Compose hash-bound, native-time video regions with explicit source-pixel masks.

This deterministic media operation supplies no review or production approval.
All geometry and model/source time mappings belong to the per-run JSON recipe.
"""
import argparse
from pathlib import Path
import subprocess
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from video_localizer.common import file_hash, get_run, inside, read_json, require, run_operation, write_json
from video_localizer.runtime import vision_path
sys.path.insert(0, str(vision_path(ROOT)))
import cv2
import numpy as np
from video_localizer.repair_masks import select


def execute(run, relative):
    recipe = read_json(inside(run, relative))
    meta = read_json(run / 'analysis/media.json')
    source = inside(run, read_json(run / 'run.json')['source'])
    require(file_hash(source) == recipe['source_sha256'], 'Source changed')
    source_cap = cv2.VideoCapture(str(source))
    try:
        require(source_cap.isOpened() and
                abs(source_cap.get(cv2.CAP_PROP_FPS) - meta['fps']) < .001 and
                round(source_cap.get(cv2.CAP_PROP_FRAME_COUNT)) == recipe['frames'],
                'Composition must cover the original native frame rate and full frame count')
    finally:
        source_cap.release()
    captures = {}
    inputs = [{'path': source.relative_to(run).as_posix(), 'sha256': file_hash(source)},
              {'path': relative, 'sha256': file_hash(inside(run, relative))}]
    baseline_cap = None
    if recipe.get('base_video'):
        baseline = inside(run, recipe['base_video']['path'])
        require(file_hash(baseline) == recipe['base_video']['sha256'], 'Base video changed')
        baseline_cap = cv2.VideoCapture(str(baseline))
        require(baseline_cap.isOpened(), 'Cannot decode base video')
        require(abs(baseline_cap.get(cv2.CAP_PROP_FPS)-meta['fps']) < .001,
                'Base must use the original native frame rate')
        require(round(baseline_cap.get(cv2.CAP_PROP_FRAME_COUNT)) == recipe['frames'],
                'Base must cover the exact original frame count')
        inputs.append(recipe['base_video'])
    for row in recipe['regions']:
        a, b = row['source_frames']
        require(0 <= a < b <= recipe['frames'], 'Invalid native source range')
        bx, by, bw, bh = row['mask_bbox']
        require(bx >= 0 and by >= 0 and bw > 0 and bh > 0 and
                bx + bw <= meta['width'] and by + bh <= meta['height'],
                'Source mask out of bounds')
        if row.get('method') == 'source_flat_surface':
            require(row.get('sample_selector') and row.get('mask_selector'),
                    'Flat source repair needs explicit source sample and glyph selectors')
            continue
        asset = row['asset']
        path = inside(run, asset['path'])
        require(file_hash(path) == asset['sha256'], 'Region asset changed')
        if asset['path'] not in captures:
            cap = cv2.VideoCapture(str(path))
            require(cap.isOpened(), 'Cannot decode proposal')
            if abs(cap.get(cv2.CAP_PROP_FPS) - meta['fps']) >= .001:
                cap.release()
                require(False, 'Proposal must use the original native frame rate; no stretching')
            boxes = {tuple(item['proposal_crop']) for item in recipe['regions']
                     if item.get('asset', {}).get('path') == asset['path']}
            frames = {box: [] for box in boxes}
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                for box in boxes:
                    x, y, w, h = box
                    require(x >= 0 and y >= 0 and x+w <= frame.shape[1] and y+h <= frame.shape[0],
                            'Proposal crop out of bounds')
                    frames[box].append(frame[y:y+h, x:x+w].copy())
            cap.release()
            require(all(frames.values()), 'Empty proposal')
            captures[asset['path']] = frames
            inputs.append(asset)
        a, b = row['source_frames']
        require(0 <= a < b <= recipe['frames'], 'Invalid native source range')
        require(row.get('proposal_fps', meta['fps']) == meta['fps'],
                'Explicit source/proposal frame-rate agreement required; no stretching')
        start = row['proposal_start_frame']
        require(start >= 0 and start + b - a <= len(captures[asset['path']][tuple(row['proposal_crop'])]),
                'Proposal does not cover the declared source range')
    output = inside(run, recipe['output'])
    require(not output.exists(), 'Keep existing outputs; choose a versioned filename')
    output.parent.mkdir(parents=True, exist_ok=True)
    width, height = meta['width'], meta['height']
    encoder = shutil.which('ffmpeg')
    require(encoder, 'FFmpeg is unavailable; run doctor with the configured media tools')
    command = [encoder, '-v', 'error', '-f', 'rawvideo',
               '-pix_fmt', 'bgr24', '-s', f'{width}x{height}', '-r', str(meta['fps']), '-i', 'pipe:0',
               '-an', '-c:v', 'libx264', '-crf', '16', '-preset', 'fast', '-pix_fmt', 'yuv420p', str(output)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    cap = cv2.VideoCapture(str(source))
    changed_total = 0
    try:
        for n in range(recipe['frames']):
            ok, original = cap.read()
            require(ok and original.shape == (height, width, 3),
                    'Missing or differently sized original frame; never hold or stretch')
            result = original.copy()
            if baseline_cap is not None:
                base_ok, result = baseline_cap.read()
                require(base_ok and result.shape == original.shape, 'Base frame coverage/geometry differs')
            for row in recipe['regions']:
                a, b = row['source_frames']
                if not a <= n < b:
                    continue
                if row.get('method') == 'source_flat_surface':
                    bx, by, bw, bh = row['mask_bbox']
                    region = np.zeros((height, width), np.uint8)
                    region[by:by+bh, bx:bx+bw] = 255
                    samples = select(original, region, row['sample_selector'], cv2, np)
                    if not np.any(samples):
                        continue
                    mask = select(original, region, row['mask_selector'], cv2, np)
                    if row.get('enclosed_surface_only'):
                        support = select(original, region, {**row['sample_selector'], 'fill_holes': True}, cv2, np)
                        mask &= support
                    for selector in row.get('protected_selectors', []):
                        mask[select(original, region, selector, cv2, np) > 0] = 0
                    fill = np.median(original[samples > 0], axis=0)
                    result[mask > 0] = np.rint(fill).astype(np.uint8)
                    changed_total += int(np.count_nonzero(mask))
                    continue
                proposal = captures[row['asset']['path']][tuple(row['proposal_crop'])][row['proposal_start_frame'] + n - a]
                dx, dy, dw, dh = row['destination']
                require(dx >= 0 and dy >= 0 and dx+dw <= width and dy+dh <= height,
                        'Destination out of bounds')
                patch = cv2.resize(proposal, (dw, dh), interpolation=cv2.INTER_LANCZOS4)
                region = np.zeros((height, width), np.uint8)
                bx, by, bw, bh = row['mask_bbox']
                require(dx <= bx and dy <= by and bx+bw <= dx+dw and by+bh <= dy+dh,
                        'Letter mask exceeds mapped proposal')
                region[by:by+bh, bx:bx+bw] = 255
                mask = select(original, region, row['mask_selector'], cv2, np) if row.get('mask_selector') else region
                for px, py, pw, ph in row.get('protected_regions', []):
                    mask[py:py+ph, px:px+pw] = 0
                alpha = mask[dy:dy+dh, dx:dx+dw].astype(np.float32) / 255
                # A small edge blend is an internal glyph mask, never a color cover.
                if row.get('edge_sigma', 0):
                    alpha = cv2.GaussianBlur(alpha, (0, 0), row['edge_sigma'])
                if row.get('match_local_exposure'):
                    # Estimate source/model color differences only from visible,
                    # non-letter neighbors. Hidden pixels remain model proposals.
                    original_crop = original[dy:dy+dh, dx:dx+dw].astype(np.float32)
                    valid = (alpha < .01).astype(np.float32)
                    sigma = float(row['match_local_exposure'])
                    difference = (original_crop-patch.astype(np.float32))*valid[:, :, None]
                    weight = cv2.GaussianBlur(valid, (0, 0), sigma)
                    correction = cv2.GaussianBlur(difference, (0, 0), sigma)/np.maximum(weight[:, :, None], .01)
                    patch = np.clip(patch.astype(np.float32)+correction, 0, 255)
                current = result[dy:dy+dh, dx:dx+dw]
                current[:] = np.rint(current*(1-alpha[:, :, None]) + patch*alpha[:, :, None]).astype(np.uint8)
                changed_total += int(np.count_nonzero(alpha))
            process.stdin.write(result.tobytes())
        process.stdin.close()
        error = process.stderr.read().decode(errors='replace')
        require(process.wait() == 0, 'Encoding failed: ' + error[-500:])
    finally:
        cap.release()
        if baseline_cap is not None:
            baseline_cap.release()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for stream in (process.stdin, process.stderr):
            if stream is not None and not stream.closed:
                try:
                    stream.close()
                except OSError:
                    pass
    record = {'source_sha256': recipe['source_sha256'], 'target_language': None,
              'contains_target_typography': False, 'inputs': inputs,
              'output': {'path': recipe['output'], 'sha256': file_hash(output)},
              'frames': recipe['frames'], 'fps': meta['fps'], 'changed_mask_pixels': changed_total,
              'method': 'Native source-time mapping of existing video proposals; explicit source-pixel lettering masks. No new inference, static donor, scene time stretch or visible covering panel.',
              'approved_for_reuse': False, 'review': 'pending actual source/base/target playback and boundaries'}
    write_json(output.with_suffix('.provenance.json'), record)
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run')
    parser.add_argument('recipe')
    args = parser.parse_args()
    run = get_run(args.run)
    with run_operation(run):
        print(execute(run, args.recipe))
