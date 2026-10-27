"""Publication judgment is separate from internal quality and actual upload."""
from pathlib import Path

from .common import ROOT, file_hash, inside, lock, object_hash, read_json, require, utc_now, write_json


def _path(root, code, digest):
    from .fireplay import _code
    _code(code)
    require(isinstance(digest, str) and len(digest) == 64 and all(c in '0123456789abcdef' for c in digest), 'Invalid video SHA256')
    return Path(root) / 'state/fireplay' / code / 'publication-reviews' / (digest + '.json')


def _complete(folder, manifest):
    meta = manifest['metadata']
    require(manifest['kind'] == 'delivery' and meta.get('status') == 'delivered_with_issues',
            'Only quality-passed or complete finalized output packages can be published')
    completion = folder / 'payload/outputs/completion.json'
    paths = {asset['path'] for asset in manifest['files']}
    require({'payload/outputs/completion.json', 'payload/inputs/request.json', 'payload/analysis/inventory.json'} <= paths,
            'Only quality-passed or complete finalized packages with bound completion/input evidence can auto-return')
    require(completion.is_file(), 'Complete finalized output needs its completion record')
    value = read_json(completion)
    require(value.get('decode_passed') is True and value.get('video_sha256') == meta['video_sha256']
            and value.get('source_sha256') == meta['source_sha256'] and value.get('completed_at'),
            'Finalized output completion must match the actual source/video and full decode')
    request = read_json(folder / 'payload/inputs/request.json')
    inventory = read_json(folder / 'payload/analysis/inventory.json')
    speech = bool(inventory.get('speech_segments') or inventory.get('audio', {}).get('has_speech'))
    require(not (request.get('require_target_audio') and speech) or value.get('speech_mode') == 'dubbed',
            'Required target audio is incomplete; subtitles alone cannot auto-publish')
    return value


def review(code, spec, root=ROOT):
    from . import bundles, fireplay
    spec = fireplay.payload(spec)
    record = fireplay._record(code, root)
    folder = inside(root, spec['package'])
    require(folder.is_relative_to((Path(root) / 'outputs').resolve()), 'Publication review needs a formal outputs package')
    manifest = bundles.verify(folder)
    meta = manifest['metadata']
    require(meta['target_language'] in record['targets'] and any(
            v.get('source', {}).get('sha256') == meta['source_sha256'] for v in record['videos']),
            'Publication review belongs to a different requirement source/locale')
    _complete(folder, manifest)
    require(file_hash(folder / 'final.mp4') == meta['video_sha256'], 'Publication video hash changed')
    assessment = spec['assessment']
    require(assessment.get('reviewer') and assessment.get('reason') and
            all(isinstance(assessment.get(k), bool) for k in ('translation_complete', 'required_audio_complete', 'watchable', 'too_many_issues')),
            'Record actual completeness, audio, watchability and issue severity judgments')
    defects = assessment.get('defects')
    require(isinstance(defects, list) and all(isinstance(d, dict) and d.get('severity') in ('minor', 'major', 'critical')
            and d.get('description') for d in defects), 'Describe observed defects and their severity')
    evidence = assessment.get('evidence')
    require(isinstance(evidence, list) and evidence, 'Publication judgment needs actual output evidence')
    files = {asset['path']: asset['sha256'] for asset in manifest['files']}
    for item in evidence:
        require(isinstance(item, str) and item in files and file_hash(inside(folder, item)) == files[item],
                'Publication evidence must be a verified file inside the delivery package')
    acceptable = (all(assessment[k] for k in ('translation_complete', 'required_audio_complete', 'watchable'))
                  and not assessment['too_many_issues'] and all(d['severity'] == 'minor' for d in defects))
    value = {'code': code, 'package': str(folder.relative_to(root)), 'video_sha256': meta['video_sha256'],
             'manifest_sha256': file_hash(folder / 'manifest.json'), 'assessment': assessment,
             'decision': 'minor_issues_acceptable' if acceptable else 'blocked_major_or_incomplete',
             'internal_quality_unchanged': True}
    path = _path(root, code, meta['video_sha256'])
    with lock(path.with_suffix('.lock')):
        if path.exists():
            old = read_json(path)
            require(all(old.get(k) == v for k, v in value.items()), 'Publication judgment is immutable; preserve the prior review and use a new revised video')
            return old
        value['reviewed_at'] = utc_now()
        write_json(path, value)
    return value


def eligible(code, folder, manifest, root=ROOT):
    policy_path = Path(root) / 'config/fireplay-publication.json'
    policy = read_json(policy_path) if policy_path.exists() else {}
    require(policy.get('authority') == 'user' and policy.get('authorization_ref') and policy.get('source_quote')
            and policy.get('severity_quote') and policy.get('mode') == 'complete_outputs_with_minor_issues',
            'No user policy allowing completed outputs with minor issues')
    _complete(folder, manifest)
    path = _path(root, code, manifest['metadata']['video_sha256'])
    require(path.exists(), 'Complete output needs an actual minor/major publication review, not an automatic quality-pass label')
    value = read_json(path)
    require(value.get('decision') == 'minor_issues_acceptable' and
            value.get('manifest_sha256') == file_hash(folder / 'manifest.json'),
            'Major/many issues, incomplete work or changed output block publication')
    return {'mode': 'minor_issues_accepted_for_publication', 'authority': policy,
            'review_path': str(path.relative_to(root)), 'review_sha256': object_hash(value), 'quality_passed': False}
