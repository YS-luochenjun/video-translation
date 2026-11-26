"""Owner-authorized delivery when both remote comparative reviewers are unavailable."""
import re

from . import audio, captions, media
from .common import file_hash, inside, read_json, require, write_json
from .model_routing import policy


def inaccessible_audio(report):
    analysis = report.get('analysis', {})
    if not isinstance(analysis, dict) or analysis.get('has_speech', True) is not None:
        return False
    if any(analysis.get(key) != [] for key in ('speech_segments', 'foreign_speech_remaining', 'uncertain_intervals')):
        return False
    if analysis.get('character_voices'):
        return False
    for field, decision in (('dialogue_translation', 'complete'), ('background_music', 'same_track'),
                            ('sound_effects', 'preserved'), ('sync', 'acceptable')):
        value = analysis.get(field)
        if not isinstance(value, dict) or decision not in value or value[decision] is not None:
            return False
        reason = value.get('reason', '')
        if not isinstance(reason, str) or not re.search(
                r'\b(?:audio|files?)\b.*\b(?:could not|cannot|unable to)\b.*\b(?:open|access|load|retrieve)\w*\b'
                r'|\b(?:could not|cannot|unable to)\b.*\b(?:open|access|load|retrieve)\w*\b.*\b(?:audio|files?)\b',
                reason, re.I):
            return False
    return True


def failure(run, job, authorization):
    if job.get('state') == 'success' and job.get('result') and job.get('result_sha256'):
        result = inside(run, job['result'])
        if result.is_file() and file_hash(result) == job['result_sha256']:
            report = read_json(result)
            if (all(report.get(key) == job.get(key) for key in ('source_sha256', 'video_sha256', 'model', 'response_id'))
                    and report.get('response_id') and inaccessible_audio(report)):
                return {'provider_code': 'media_unavailable', 'state': 'success',
                        'review_sha256': file_hash(result)}
    error = job.get('error') or ''
    match = re.search(r'KIE code (\d+):|HTTP (\d+)', error)
    code = str(job.get('provider_code') or (next(value for value in match.groups() if value) if match else ''))
    if re.match(r'KIE transport/response failure \((URLError|TimeoutError|OSError|ConnectionError|ConnectionResetError|BrokenPipeError)\)', error):
        code = 'transport'
    if (job.get('state') in ('failed', 'fail', 'ambiguous') and job.get('failure_stage') == 'model_request'
            and code in authorization['provider_codes']):
        return {'provider_code': code, 'state': job['state']}
    return None


def review_with_fallback(run):
    from . import workflow
    from .kie import ApiError
    from .model_routing import audio_recovery_route, selected

    candidate = read_json(run / 'outputs/candidate.json')
    authorization = policy(run.parent.parent)['audio_analysis_recovery']['outage_delivery']
    attempts = []
    for model in (selected('audio_analysis'), audio_recovery_route('comparative_audio_review')['model']):
        try:
            result = workflow.analyze_audio(run, candidate=True, model=model)
        except ApiError:
            jobs = [read_json(path) for path in (run / 'jobs').glob('*.json')]
            matching = [job for job in jobs if job.get('kind') == 'audio_review'
                        and job.get('video_sha256') == candidate['sha256'] and job.get('model') == model]
            if not matching:
                raise
            job = max(matching, key=lambda item: item.get('created_at', ''))
            if not failure(run, job, authorization):
                raise
            result = {'job': job['id'], 'state': job['state'], 'error': job.get('error')}
        job = read_json(run / 'jobs' / (result['job'] + '.json'))
        unavailable = failure(run, job, authorization)
        attempts.append({'model': model, **result})
        if not unavailable:
            return {**result, 'review_attempts': attempts}
    return {'state': 'remote_review_unavailable', 'review_attempts': attempts,
            'next_action': 'Use finalize with remote_audio_review_outage=true after checking complete TTS and visual evidence'}


def receipt(run, video):
    from .workflow import source_path

    authorization = policy(run.parent.parent)['audio_analysis_recovery']['outage_delivery']
    require(authorization['enabled'] and authorization['authority'] == 'user',
            'Remote audio review outage delivery is not authorized')
    source = source_path(run)
    source_digest, video_digest = file_hash(source), file_hash(video)
    directory = run / 'review' / video_digest[:12]
    review_path = directory / 'audio-model-review.json'
    require(not review_path.exists() or inaccessible_audio(read_json(review_path)),
            'An actual comparative review exists; do not waive its findings')
    failed = {}
    for path in (run / 'jobs').glob('*.json'):
        job = read_json(path)
        if (job.get('kind') != 'audio_review' or job.get('source_sha256') != source_digest
                or job.get('video_sha256') != video_digest or job.get('model') not in authorization['required_models']):
            continue
        unavailable = failure(run, job, authorization)
        require(unavailable or job.get('state') not in ('success', 'response_received', 'response_invalid'),
                'A returned comparative review requires inspection rather than outage delivery')
        if unavailable:
            failed[job['model']] = {'job_id': job['id'], 'journal_sha256': file_hash(path),
                                    **unavailable}
    if review_path.exists():
        require(any(row.get('review_sha256') == file_hash(review_path) for row in failed.values()),
                'Unavailable review must match a saved provider response')
    require(set(failed) == set(authorization['required_models']),
            'Outage delivery requires actual provider failure on both comparative review routes for this video')
    inventory = read_json(run / 'analysis/inventory.json')
    require(inventory['audio']['strategy'] == 'replace', 'Outage delivery requires an actual generated dubbing mix')
    mix = inside(run, inventory['audio']['replacement_path'])
    provenance_path = mix.parent / 'provenance.json'
    provenance = read_json(provenance_path)
    require(provenance['source_sha256'] == source_digest
            and inside(run, provenance['output']['path']) == mix
            and file_hash(mix) == provenance['output']['sha256'], 'Dubbing mix provenance changed')
    expected = {line['id']: captions.normalized(line['target_text']) for line in inventory['speech_segments']
                if line.get('action') != 'preserve'}
    lines = provenance['lines']
    require(expected and all(expected.values()) and len(lines) == len(expected)
            and {line['id']: captions.normalized(line['target_text']) for line in lines} == expected,
            'Dubbing mix must contain every required target speech line')
    for line in lines:
        voice = line['voice']
        require(file_hash(inside(run, voice['path'])) == voice['sha256'], 'Generated voice asset changed')
    technical = audio.evaluate(source, video, inventory['audio'], media.probe(source)['duration'])
    require(not technical['failures'], 'Actual soundtrack failed technical checks: ' + str(technical['failures']))
    _, mixed_pcm = audio.inspect(mix)
    _, encoded_pcm = audio.inspect(video)
    match = audio.waveform_match(mixed_pcm, encoded_pcm)
    require(match['correlation'] >= .95 and abs(match['offset_seconds']) <= .04,
            'Actual encoded soundtrack does not match the registered TTS mix')
    value = {'source_sha256': source_digest, 'video_sha256': video_digest,
             'authorization_ref': authorization['authorization_ref'], 'remote_audio_review': 'skipped_provider_outage',
             'semantic_review_passed': False, 'failed_models': failed, 'speech_ids': sorted(expected),
             'mix_sha256': file_hash(mix), 'provenance_sha256': file_hash(provenance_path),
             'technical': technical, 'mix_waveform_match': match,
             'proof_boundary': 'Generated TTS coverage and encoded soundtrack only; actual pronunciation, semantic completeness and head/tail listening were not verified by the unavailable remote reviewers.'}
    write_json(directory / 'remote-audio-review-outage.json', value)
    return value
