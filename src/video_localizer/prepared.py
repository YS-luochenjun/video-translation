"""Bind a reusable visual repair master to its source and preparation evidence."""
from .common import file_hash, inside, read_json, require
from . import compositor, media


def verify(run, asset, source_sha256):
    path=inside(run,asset['path'])
    require(path.is_file() and file_hash(path)==asset['sha256'],'Prepared video missing or changed')
    record_path=inside(run,asset['record'])
    require(record_path.is_file() and file_hash(record_path)==asset['record_sha256'],'Prepared video provenance changed')
    record=read_json(record_path)
    require(record.get('source_sha256')==source_sha256,'Prepared video belongs to another source')
    require(record.get('output',{}).get('sha256')==asset['sha256'] and record['output'].get('path')==asset['path'],
            'Prepared video output binding mismatch')
    require(record.get('target_language') is None and record.get('contains_target_typography') is False,
            'Reusable visual master must precede target-language typography')
    require(bool(record.get('inputs')),'Prepared video has no source evidence')
    for item in record['inputs']:
        original=inside(run,item['path'])
        require(original.is_file() and file_hash(original)==item['sha256'],'Prepared video input changed')
    for proposal in record.get('model_proposals',[]):
        job=read_json(inside(run,proposal['job_record']))
        require(job.get('state')=='success' and job.get('source_sha256')==source_sha256,
                'Prepared proposal has no successful source-bound model task')
        require(job.get('result_sha256')==proposal['result_sha256'],'Prepared proposal result binding mismatch')
    return path


def verify_for_production(run, asset, source_sha256, root=None):
    """Require a reviewed neutral master before language rendering.

    verify() remains an integrity check for restoring historical/failed packages.
    A valid archive is not approval to use its visual repair in another output.
    """
    from pathlib import Path
    from .common import ROOT
    from .quality_holds import require_clear
    workspace = root or (Path(run).parent.parent if Path(run).parent.name == "runs" else ROOT)
    require_clear(source_sha256, asset['sha256'], workspace)
    path = verify(run, asset, source_sha256)
    record = read_json(inside(run, asset['record']))
    require(record.get('approved_for_reuse') is True,
            'Neutral visual master is not approved for production; review the text-free video first')
    review_asset = record.get('visual_review', {})
    require(isinstance(review_asset, dict) and review_asset.get('path') and review_asset.get('sha256'),
            'Neutral visual master needs a bound visual review')
    review_path = inside(run, review_asset['path'])
    require(review_path.is_file() and file_hash(review_path) == review_asset['sha256'],
            'Neutral visual review missing or changed')
    review = read_json(review_path)
    require(review.get('source_sha256') == source_sha256 and
            review.get('video_sha256') == asset['sha256'],
            'Neutral visual review belongs to another source or video')
    require(review.get('decision') == 'pass' and bool(review.get('reviewer')),
            'Neutral visual review has not passed')
    for check in ('source_text_removal', 'texture_and_color', 'foreground_motion', 'temporal_boundaries'):
        require(review.get('checks', {}).get(check) == 'pass',
                f'Neutral visual review missing or failing check: {check}')
    evidence = review.get('evidence', [])
    require(isinstance(evidence, list) and bool(evidence), 'Neutral visual review has no evidence')
    for item in evidence:
        require(isinstance(item, dict) and item.get('path') and item.get('sha256'),
                'Neutral visual review evidence binding is incomplete')
        original = inside(run, item['path'])
        require(original.is_file() and file_hash(original) == item['sha256'],
                'Neutral visual review evidence missing or changed')
        require(any(bound.get('path') == item['path'] and bound.get('sha256') == item['sha256']
                    for bound in record['inputs']),
                'Neutral visual review evidence must be included in preparation inputs for portable reuse')
    from .visual_audit import verify_neutral
    verify_neutral(run, asset)
    return path


def render(run,segment,items,meta,directory,source_sha256):
    master=verify_for_production(run,segment['prepared_video'],source_sha256)
    actual=media.probe(master)
    require((actual['width'],actual['height'])==(meta['width'],meta['height']),'Prepared video dimensions differ')
    require(abs(actual['duration']-(segment['end']-segment['start']))<=.15,'Prepared video duration differs')
    output=directory/'visual.mp4'
    media.normalize(master,segment['end']-segment['start'],meta,output)
    output=compositor.text(output,segment,items,meta,directory/'target-overlay')
    if segment.get('surface_typography'):
        from . import surface
        layer = surface.verify(run, segment['surface_typography'], source_sha256,
                               read_json(run/'inputs/request.json')['target_language'], items)
        output = surface.composite(output, layer, segment['end']-segment['start'], directory/'surface-overlay')
    from .captions import shift_instances
    shifted=shift_instances([item for item in items if item['action']=='solid_overlay'
                            and item['start']<segment['end'] and item['end']>segment['start']],
                           segment['start'],segment['end']-segment['start'])
    if shifted:output=media.render_local(output,{'start':0,'end':segment['end']-segment['start']},shifted,meta,directory/'fixed-ui')
    return output
