"""Bounded examples are not a second copy of a complete production audit."""
from pathlib import Path

from .common import inside, read_json, require


def select(run, video_sha256=None, history=False):
    run = Path(run).resolve()
    chosen = set()
    def add(path):
        if path.is_file():
            chosen.add(path)
    folders = [run/'review'/video_sha256[:12]] if video_sha256 else []
    if history:
        # All small original observations and failure/recovery records survive pruning.
        for p in run.rglob('*'):
            if p.is_file() and p.suffix.lower() in {'.json','.md','.txt','.ass','.csv','.py'}:
                add(p)
        folders = list((run/'review').glob('*'))
    for folder in folders:
        if not folder.is_dir(): continue
        for p in folder.glob('*'):
            if p.suffix.lower() in {'.json','.wav'} or p.name.startswith(('caption-','boundary-','seam-')):
                add(p)
        for name in ('contact-sheet.jpg','final-bottom-first32.png'):
            add(folder/name)
    # Representative native source/result comparisons plus every explicit failure.
    manifests = list((run/'review').glob('*/visual-audit/*/text-visual-audit.json'))
    manifests += list((run/'inputs/visual-audit').glob('*/text-visual-audit.json'))
    for path in manifests:
        manifest = read_json(path)
        relevant = history or video_sha256 == manifest['binding']['video_sha256']
        if not relevant: continue
        add(path)
        for name in ('source-composition.png','neutral-composition.png','final-composition.png'):
            add(path.parent/name)
        for p in (path.parent/'observations').glob('*.json'):
            add(p)
            record = read_json(p)
            for check in record.get('checks',{}).values():
                if check.get('status') == 'fail':
                    for relative in check.get('evidence_pages',[]):
                        evidence = inside(path.parent,relative)
                        require(evidence.is_file(), 'Explicit failure evidence missing: '+relative)
                        add(evidence)
        for row in manifest['instances']:
            pages = row['pages']
            if pages:
                for p in (pages[0],pages[len(pages)//2],pages[-1]):
                    add(inside(path.parent,p['id']))
        add(path.parent/'reviews.json')
    review = run/'review/review.json'
    if review.exists():
        def references(value):
            if isinstance(value,dict):
                for v in value.values(): references(v)
            elif isinstance(value,list):
                for v in value: references(v)
            elif isinstance(value,str) and value.startswith(('review/','analysis/')) and '\n' not in value:
                p = inside(run,value)
                if p.suffix.lower() in {'.json','.jpg','.png','.webp','.wav'}: add(p)
        references(read_json(review))
    return sorted(chosen)
