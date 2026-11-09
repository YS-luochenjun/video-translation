"""Publication judgment is separate from internal quality and actual upload."""
from pathlib import Path

from .common import ROOT, file_hash, inside, lock, object_hash, read_json, require, utc_now, write_json

ACCEPTABLE = {'minor_issues_acceptable', 'bounded_best_available_acceptable', 'exact_version_accepted_by_user'}
SEVERE_KINDS = {'large_area_tearing', 'unwatchable', 'severe_subject_damage', 'corrupt_file',
                'incomplete_translation', 'missing_required_audio', 'wrong_locale', 'unreadable_core_copy'}
VISUAL_REPAIR_KINDS = {'visible_solid_coverup', 'hard_edged_coverup', 'unapproved_blur_coverup'}


def publication_decision(code, digest, root=ROOT):
    """Read a current judgment without replacing an older rejection."""
    canonical = _path(root, code, digest)
    accepted = canonical.parent.parent / 'publication-acceptances' / (digest + '.json')
    if accepted.exists():
        value = read_json(accepted)
        prior = value.get('prior_review', {})
        require(file_hash(inside(root, prior['path'])) == prior['sha256'], 'Prior publication review changed')
        return value.get('decision')
    revised = canonical.parent.parent / 'publication-reassessments' / (digest + '.json')
    if revised.exists():
        value = read_json(revised)
        require(canonical.exists() and file_hash(canonical) == value['prior_review']['sha256'],
                'Prior publication review changed')
        return value.get('decision')
    return read_json(canonical).get('decision') if canonical.exists() else None


def _ordinary_best(assessment, files, policy):
    if policy.get('mode') != 'bounded_best_available':
        return False
    if any(d['severity'] == 'critical' or d.get('kind') in SEVERE_KINDS or
           d.get('publication_impact', 'ordinary' if d['severity'] == 'minor' else 'unclassified') != 'ordinary'
           for d in assessment['defects']):
        return False
    best = assessment.get('best_available', {})
    if not best:
        return False
    require(best.get('stop_condition') in {'retry_limit', 'budget_limit', 'capability_limit', 'no_evidence_backed_improvement'}
            and best.get('reason') and best.get('evidence'), 'Best available needs the actual bounded stopping reason and evidence')
    require(all(isinstance(p, str) and p in files for p in best['evidence']),
            'Best-available evidence must be inside the verified delivery package')
    return True


def _path(root, code, digest):
    from .fireplay import _code
    _code(code)
    require(isinstance(digest, str) and len(digest) == 64 and all(c in '0123456789abcdef' for c in digest), 'Invalid video SHA256')
    return Path(root) / 'state/fireplay' / code / 'publication-reviews' / (digest + '.json')


def _new_audio_evidence(previous, folder, manifest, root):
    """Resolve missing verification with new evidence for unchanged video bytes."""
    require(previous.get('decision') == 'blocked_major_or_incomplete'
            and previous.get('assessment', {}).get('required_audio_complete') is False
            and previous.get('assessment', {}).get('defects')
            and all(d.get('kind') == 'required_audio_unverified'
                    for d in previous['assessment']['defects']),
            'Audio evidence cannot waive an actual audio defect or visual rejection')
    from . import bundles
    old_folder = inside(root, previous['package'])
    old_manifest = bundles.verify(old_folder)
    require(file_hash(old_folder / 'manifest.json') == previous['manifest_sha256'],
            'Preserve the original rejected package')
    meta = manifest['metadata']
    require(all(old_manifest['metadata'].get(k) == meta.get(k)
                for k in ('source_sha256', 'video_sha256', 'target_language')),
            'New verification must concern the same source, locale and video')
    old_files = {a['path']: a['sha256'] for a in old_manifest['files']}
    files = {a['path']: a['sha256'] for a in manifest['files']}
    require(all(files.get(p) and files[p] == old_files.get(p)
                for p in ('payload/inputs/request.json', 'payload/analysis/inventory.json')),
            'Audio-evidence reassessment cannot change the request or inventory')
    digest = meta['video_sha256']
    path = f'payload/review/{digest[:12]}/audio-model-review.json'
    require(path in files and files[path] != old_files.get(path),
            'Supply a genuinely new captured audio report')
    report = read_json(inside(folder, path))
    quality = read_json(folder / 'payload/outputs/quality.json')
    require(report.get('video_sha256') == digest
            and report.get('source_sha256') == meta['source_sha256'] and report.get('response_id')
            and quality.get('video_sha256') == digest
            and quality.get('audio_model_check', {}).get('decision') == 'pass'
            and quality['audio_model_check'].get('review_sha256') == files[path],
            'New audio evidence must pass current captured source/video-bound audio checks')
    response_path = f'payload/review/{digest[:12]}/audio-model-response.json'
    require(response_path in files and read_json(inside(folder, response_path)).get('id') == report['response_id'],
            'Keep the matching actual provider response')
    return {'basis': 'new_audio_verification_for_unchanged_video',
            'audio_report': {'path': path, 'sha256': files[path]},
            'response_id': report['response_id'], 'quality_passed': False}


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


def _observed_findings(folder, manifest):
    """Read explicit current-video findings, never classify pixels or search prose."""
    digest = manifest['metadata']['video_sha256']
    findings = []
    for asset in manifest['files']:
        path = asset['path']
        if not path.startswith('payload/review/') or not path.endswith('.json'):
            continue
        data = read_json(inside(folder, path))
        if not isinstance(data, dict) or data.get('video_sha256') != digest:
            continue
        for row in data.get('text_restoration_review') or []:
            if isinstance(row, dict) and row.get('visible_coverup') is True:
                findings.append({'path': path, 'id': row.get('id'), 'kind': 'visible_coverup', 'publication_impact': 'requires_bounded_stop'})
            if isinstance(row, dict) and row.get('source_text_removed') is False:
                findings.append({'path': path, 'id': row.get('id'), 'kind': 'residual_source_lettering', 'publication_impact': 'requires_bounded_stop'})
        finish = data.get('visual_finish')
        for defect in (finish.get('defects') or []) if isinstance(finish, dict) else []:
            if not isinstance(defect, dict):
                continue
            if (defect.get('kind') in SEVERE_KINDS or defect.get('severity') == 'critical'
                    or defect.get('publication_impact') == 'severe'):
                findings.append({'path': path, 'kind': defect.get('kind'), 'publication_impact': 'severe'})
            elif defect.get('kind') in VISUAL_REPAIR_KINDS:
                findings.append({'path': path, 'kind': defect['kind'], 'publication_impact': 'requires_bounded_stop'})
    return findings


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
    if spec.get('user_acceptance'):
        approval = spec['user_acceptance']
        require(approval.get('authority') == 'user' and approval.get('accepted') is True
                and approval.get('authorization_ref') and approval.get('source_quote')
                and approval.get('video_sha256') == meta['video_sha256'],
                'User acceptance needs the exact video hash and attributed human instruction')
        prior_path = _path(root, code, meta['video_sha256'])
        require(prior_path.exists(), 'Preserve an actual publication review before user acceptance')
        prior = read_json(prior_path)
        require(prior.get('manifest_sha256') == file_hash(folder / 'manifest.json') and all(
                prior.get('assessment', {}).get(k) is True
                for k in ('translation_complete', 'required_audio_complete', 'watchable')),
                'Visual acceptance cannot waive incomplete translation, required audio or an unwatchable output')
        value = {'code': code, 'package': str(folder.relative_to(root)),
                 'source_sha256': meta['source_sha256'], 'video_sha256': meta['video_sha256'],
                 'manifest_sha256': file_hash(folder / 'manifest.json'), 'user_acceptance': approval,
                 'prior_review': {'path': str(prior_path.relative_to(root)), 'sha256': file_hash(prior_path)},
                 'decision': 'exact_version_accepted_by_user', 'internal_quality_unchanged': True}
        accepted = Path(root) / 'state/fireplay' / code / 'publication-acceptances' / (meta['video_sha256'] + '.json')
        with lock(accepted.with_suffix('.lock')):
            if accepted.exists():
                old = read_json(accepted)
                require(all(old.get(k) == v for k, v in value.items()), 'Exact-version user acceptance is immutable')
                return old
            value['accepted_at'] = utc_now()
            write_json(accepted, value)
        return value
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
    observed_findings = _observed_findings(folder, manifest)
    basic = all(assessment[k] for k in ('translation_complete', 'required_audio_complete', 'watchable'))
    severe = any(f['publication_impact'] == 'severe' for f in observed_findings) or any(d['severity'] == 'critical' or d.get('kind') in SEVERE_KINDS or
                 d.get('publication_impact') == 'severe' for d in defects)
    policy = read_json(Path(root) / 'config/fireplay-publication.json')
    bounded = basic and not severe and _ordinary_best(assessment, files, policy)
    repair_limitations = bool(observed_findings) or any(d.get('kind') in VISUAL_REPAIR_KINDS for d in defects)
    acceptable = (basic and not severe and not repair_limitations
                  and not assessment['too_many_issues'] and all(d['severity'] == 'minor' for d in defects))
    value = {'code': code, 'package': str(folder.relative_to(root)), 'video_sha256': meta['video_sha256'],
             'manifest_sha256': file_hash(folder / 'manifest.json'), 'assessment': assessment,
             'decision': ('bounded_best_available_acceptable' if bounded else
                          'minor_issues_acceptable' if acceptable else 'blocked_major_or_incomplete'),
             'policy_authorization_ref': policy.get('authorization_ref'),
             'internal_quality_unchanged': True}
    if observed_findings:
        value['observed_visual_findings'] = observed_findings
    path = _path(root, code, meta['video_sha256'])
    if spec.get('reassess_with_new_audio_evidence'):
        require(path.exists() and basic and not severe and (bounded or acceptable),
                'New audio evidence needs an existing rejection and an otherwise eligible current review')
        previous = read_json(path)
        value['evidence_reassessment'] = _new_audio_evidence(previous, folder, manifest, root)
        value['prior_review'] = {'path': str(path.relative_to(root)), 'sha256': file_hash(path)}
        path = path.parent.parent / 'publication-reassessments' / path.name
    elif spec.get('reassess_under_current_policy'):
        require(path.exists(), 'Policy reassessment requires the preserved original review')
        previous = read_json(path)
        require(previous.get('decision') == 'blocked_major_or_incomplete' and
                previous.get('manifest_sha256') == value['manifest_sha256'] and bounded,
                'Policy reassessment cannot waive severe damage, missing translation/audio or changed output')
        value['prior_review'] = {'path': str(path.relative_to(root)), 'sha256': file_hash(path)}
        path = path.parent.parent / 'publication-reassessments' / path.name
    with lock(path.with_suffix('.lock')):
        if path.exists():
            old = read_json(path)
            # Legacy minor/rejected judgments predate the policy-reference field.
            # Retain their bytes when the actual assessment is unchanged.
            compared = {k: v for k, v in value.items() if k != 'policy_authorization_ref' or bounded}
            require(all(old.get(k) == v for k, v in compared.items()), 'Publication judgment is immutable; preserve the prior review and use a new revised video')
            return old
        value['reviewed_at'] = utc_now()
        write_json(path, value)
    return value


def eligible(code, folder, manifest, root=ROOT):
    policy_path = Path(root) / 'config/fireplay-publication.json'
    policy = read_json(policy_path) if policy_path.exists() else {}
    require(policy.get('authority') == 'user' and policy.get('authorization_ref') and policy.get('source_quote')
            and policy.get('severity_quote') and policy.get('mode') in {'complete_outputs_with_minor_issues', 'bounded_best_available'},
            'No user policy allowing completed outputs with minor issues')
    _complete(folder, manifest)
    accepted = Path(root) / 'state/fireplay' / code / 'publication-acceptances' / (manifest['metadata']['video_sha256'] + '.json')
    if accepted.exists():
        value = read_json(accepted)
        approval = value.get('user_acceptance', {})
        prior = value.get('prior_review', {})
        require(value.get('decision') == 'exact_version_accepted_by_user'
                and value.get('manifest_sha256') == file_hash(folder / 'manifest.json')
                and value.get('source_sha256') == manifest['metadata']['source_sha256']
                and value.get('video_sha256') == manifest['metadata']['video_sha256']
                and approval.get('authority') == 'user' and approval.get('accepted') is True
                and approval.get('video_sha256') == manifest['metadata']['video_sha256']
                and approval.get('authorization_ref') and approval.get('source_quote')
                and file_hash(inside(root, prior['path'])) == prior['sha256'],
                'Exact-version user acceptance or its preserved review changed')
        return {'mode': 'exact_version_user_acceptance', 'authority': approval,
                'review_path': str(accepted.relative_to(root)), 'review_sha256': object_hash(value),
                'quality_passed': False}
    path = _path(root, code, manifest['metadata']['video_sha256'])
    require(path.exists(), 'Complete output needs an actual minor/major publication review, not an automatic quality-pass label')
    reassessed = path.parent.parent / 'publication-reassessments' / path.name
    if reassessed.exists():
        revised = read_json(reassessed)
        require(file_hash(path) == revised['prior_review']['sha256'], 'Prior publication review changed')
        path = reassessed
    value = read_json(path)
    require(value.get('decision') in {'minor_issues_acceptable', 'bounded_best_available_acceptable'} and
            value.get('manifest_sha256') == file_hash(folder / 'manifest.json'),
            'Major/many issues, incomplete work or changed output block publication')
    require(value.get('decision') != 'bounded_best_available_acceptable' or
            policy.get('mode') == 'bounded_best_available' and value.get('policy_authorization_ref') == policy['authorization_ref'],
            'Best-available publication authority changed; review the current policy')
    return {'mode': ('bounded_best_available_publication' if value['decision'] == 'bounded_best_available_acceptable'
                     else 'minor_issues_accepted_for_publication'), 'authority': policy,
            'review_path': str(path.relative_to(root)), 'review_sha256': object_hash(value), 'quality_passed': False}
