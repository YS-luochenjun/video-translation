"""Prepare request-bound fallback packets from recorded TTS failures."""

import re

from . import budgets, model_tasks
from .captions import normalized
from .common import file_hash, guarded, inside, object_hash, read_json, require, write_json
from .model_routing import policy, require_remote_task


def _explicit_rejection(recovery, job):
    return (job.get('state') == 'failed' and not job.get('task_id')
            and job.get('error') in recovery.get('explicit_submission_rejections', []))


def tts_recovery_model(root, job, *, locale=None):
    if (job.get('kind') != 'audio_task' or job.get('model') not in model_tasks.TTS_MODELS
            or not job.get('packet') or job.get('state') not in ('fail', 'failed')):
        return None
    recovery = policy(root).get('tts_recovery', {})
    settled_failure = (job.get('task_id') and not isinstance(job.get('credits_consumed'), bool)
                       and job.get('credits_consumed') == 0
                       and str(job.get('provider_code')) in recovery.get('transient_provider_codes', []))
    if not settled_failure and not _explicit_rejection(recovery, job):
        return None
    if not locale:
        return None
    routes = recovery['fallbacks']
    models = [route['model'] for route in routes]
    failed = job['model']
    start = models.index(failed) + 1 if failed in models else 0
    language = model_tasks.tts_language_code(locale)
    return next((route['model'] for route in routes[start:]
                 if language in route['language_codes'].split()), None)


@guarded
def prepare_tts_fallback(run, relative, failed_job_id, *, failed_run=None, speech_ids=None,
                         elevenlabs_voices=None, combine=False):
    root = run.parent.parent
    evidence_run = failed_run or run
    require(evidence_run.parent == run.parent and re.fullmatch(r'[a-f0-9]{64}', failed_job_id),
            'Use a recorded job ID from this workspace')
    failure = read_json(inside(evidence_run, f'jobs/{failed_job_id}.json'))
    require(failure.get('id') == failed_job_id, 'Fallback failure receipt does not match the recorded job')
    locale = read_json(run / 'inputs/request.json')['target_language']
    recovery = policy(root)['tts_recovery']
    model = tts_recovery_model(root, failure, locale=locale)
    require(model, 'No compatible next TTS route after the recorded terminal zero-credit provider failure or explicit submission rejection')
    route = next(route for route in recovery['fallbacks'] if route['model'] == model)
    current = model_tasks.packet(run, relative)
    require(current['payload']['model'] in model_tasks.GEMINI_TTS_MODELS
            and current['source_sha256'] == failure.get('source_sha256'),
            'Fallback must use a current Gemini packet and evidence from the same source')
    budget = budgets.for_run(run)
    require(budget['id'] == budgets.for_run(evidence_run)['id'] and budget['state'] == 'open',
            'Fallback must use the original open request budget')
    if _explicit_rejection(recovery, failure):
        require(evidence_run == run, 'Use explicit submission rejection evidence from the same run')
    original_ids = current['speech_ids']
    ids = speech_ids or original_ids
    require(len(ids) == len(set(ids)) and set(ids) <= set(original_ids), 'Select distinct speech IDs from the supplied packet')
    if _explicit_rejection(recovery, failure):
        rejected_packet = read_json(inside(run, failure['packet']))
        rejected_payload = rejected_packet['payload']
        reservation = budget.get('reservations', {}).get(failed_job_id, {})
        dispatch = reservation.get('dispatch') or {}
        require(object_hash(rejected_packet) == failure.get('packet_sha256')
                and set(ids) <= set(rejected_packet.get('speech_ids', []))
                and rejected_payload.get('model') == failure['model']
                and reservation.get('run') == run.name and reservation.get('job') == failed_job_id
                and not reservation.get('receipt')
                and dispatch.get('endpoint') == '/api/v1/jobs/createTask'
                and dispatch.get('request_sha256') == object_hash(rejected_payload),
                'Explicit rejection must match the recorded task, selected speech and ledger dispatch')
    selected_voices = {}
    for entry in elevenlabs_voices or []:
        speech_id, separator, voice = entry.partition('=')
        require(separator and speech_id in ids and speech_id not in selected_voices
                and re.fullmatch(r'[A-Za-z0-9]{20}', voice), 'Use --voice SPEECH_ID=OFFICIAL_VOICE_ID once per selected speech')
        selected_voices[speech_id] = voice
    for job_path in (run / 'jobs').glob('*.json'):
        job = read_json(job_path)
        if job.get('model') not in model_tasks.TTS_MODELS:
            continue
        if job.get('state') in ('success', 'fail', 'failed') and job.get('credits_consumed') is not None:
            continue
        previous_path = inside(run, job['packet']) if job.get('packet') else None
        if previous_path and previous_path.is_file():
            previous = read_json(previous_path)
            hashed = {'packet': previous, 'retry_of': job['retry_of']} if job.get('retry_of') else previous
            previous_ids = previous.get('speech_ids')
            if object_hash(hashed) == job.get('packet_sha256') and previous_ids:
                if set(ids).isdisjoint(previous_ids):
                    continue
                reservation = budget.get('reservations', {}).get(job.get('id'), {})
                if (job.get('state') == 'ambiguous' and not job.get('task_id')
                        and job.get('error') == 'Local audio task failure; inspect journal before retry'
                        and reservation.get('run') == run.name and reservation.get('job') == job.get('id')
                        and reservation.get('created_at') and not reservation.get('imported')
                        and not reservation.get('receipt') and not reservation.get('dispatch')):
                    continue
                rejected_voice = re.fullmatch(
                    r'KIE code 422: Invalid voice parameter: ([A-Za-z0-9]{20})\. Please refer to the documentation for the list of supported voices\.',
                    job.get('error') or '',
                )
                previous_payload = previous.get('payload', {})
                dispatch = reservation.get('dispatch') or {}
                ordered_models = [policy(root)['tts'], *(item['model'] for item in recovery['fallbacks'])]
                if (_explicit_rejection(recovery, job)
                        and job.get('model') in ordered_models
                        and ordered_models.index(job['model']) < ordered_models.index(model)
                        and job.get('model') == previous_payload.get('model')
                        and reservation.get('run') == run.name and reservation.get('job') == job.get('id')
                        and not reservation.get('receipt')
                        and dispatch.get('endpoint') == '/api/v1/jobs/createTask'
                        and dispatch.get('request_sha256') == object_hash(previous_payload)):
                    continue
                if (rejected_voice and job.get('state') == 'failed' and not job.get('task_id')
                        and model == job.get('model') == previous_payload.get('model') == model_tasks.ELEVENLABS_V3
                        and reservation.get('run') == run.name and reservation.get('job') == job.get('id')
                        and not reservation.get('receipt') and dispatch.get('endpoint') == '/api/v1/jobs/createTask'
                        and dispatch.get('request_sha256') == object_hash(previous_payload)
                        and rejected_voice[1] in {turn.get('voice') for turn in previous_payload['input']['dialogue']}
                        and all(selected_voices.get(key) not in (None, rejected_voice[1])
                                for key in set(ids).intersection(previous_ids))):
                    continue
        require(False, 'Reconcile outstanding TTS tasks and billing for the selected speech before preparing fallback')

    authority = recovery
    require(authority.get('authority') == 'user' and authority.get('authorization_ref') and authority.get('source_quote'),
            'TTS fallback needs a standing user authorization')
    require(set(selected_voices) == set(ids), 'Supply an official ElevenLabs voice with --voice for each selected speech ID')
    speeches = {item['id']: item['target_text'] for item in read_json(run / 'analysis/inventory.json')['speech_segments']}
    turns = current['payload']['input']['dialogue_turns']
    if len(turns) > 1:
        require(len(turns) == len(original_ids) and all(
            normalized(turn['text']) == normalized(speeches[key]) for key, turn in zip(original_ids, turns)),
            'Provide a current packet with exactly one voice turn per speech ID')
    selected = [speech_id for speech_id in original_ids if speech_id in ids]
    if combine:
        positions = [original_ids.index(speech_id) for speech_id in selected]
        require(positions[-1] - positions[0] + 1 == len(positions),
                'Combine only contiguous missing lines in the supplied packet')
        require(model == model_tasks.ELEVENLABS_V3 or len(set(selected_voices.values())) == 1,
                'Multilingual v2 uses one voice per task. Submit different roles separately.')
    groups = [selected] if combine else [[speech_id] for speech_id in selected]
    grant = {'authority': authority['authority'], 'source': authority['authorization_ref'],
             'quote': authority['source_quote'], 'model': model, 'source_sha256': current['source_sha256'],
             'target_languages': [locale], 'request_budget': budget['id']}
    grant_path = f'inputs/tts-fallback-authority-{object_hash(grant)[:16]}.json'
    write_json(run / grant_path, grant)
    authorization = {'path': grant_path, 'sha256': file_hash(run / grant_path)}
    require_remote_task(model, run=run, authorization=authorization)

    packets = []
    for group_ids in groups:
        texts = [speeches[speech_id] for speech_id in group_ids]
        inputs = {'language_code': model_tasks.tts_language_code(locale)}
        if model == model_tasks.ELEVENLABS_V3:
            inputs['dialogue'] = [{'text': speeches[speech_id], 'voice': selected_voices[speech_id]}
                                  for speech_id in group_ids]
        else:
            texts = [' '.join(texts)]
            inputs.update(text=texts[0], voice=selected_voices[group_ids[0]])
        estimate = model_tasks.elevenlabs_estimate(route, texts)
        purpose = 'ElevenLabs fallback for finalized TTS'
        data = {'source_sha256': current['source_sha256'], 'purpose': purpose, 'estimated_credits': estimate,
                'speech_ids': group_ids, 'model_authorization': authorization,
                'tts_fallback_source_packet': relative,
                'payload': {'model': model, 'input': inputs}}
        digest = object_hash(data)
        packet_path = f'inputs/tts-fallback-{digest[:16]}.json'
        write_json(run / packet_path, data)
        model_tasks.packet(run, packet_path)
        existing_job = run / 'jobs' / f'{digest}.json'
        existing = read_json(existing_job) if existing_job.exists() else {}
        selection = {'speech_id': group_ids[0]} if len(group_ids) == 1 else {'speech_ids': group_ids}
        packets.append({**selection, 'packet': packet_path, 'job': digest, 'estimated_credits': estimate,
                        'state': existing.get('state', 'prepared'), 'task_id': existing.get('task_id')})
    receipt = {'model': model, 'request_budget': budget['id'], 'failed_run': evidence_run.name,
               'failed_job': failed_job_id, 'failed_task_id': failure.get('task_id'), 'packets': packets}
    receipt_path = f'inputs/tts-fallback-receipt-{object_hash(receipt)[:16]}.json'
    write_json(run / receipt_path, receipt)
    return {**receipt, 'receipt': receipt_path, 'paid_submission': False}
