"""Prepare request-bound Gemini fallback packets from settled TTS failures."""

import re

from . import budgets, model_tasks
from .captions import normalized
from .common import file_hash, guarded, inside, object_hash, read_json, require, write_json
from .model_routing import policy, require_remote_task


def tts_recovery_model(root, job):
    if (job.get('kind') != 'audio_task' or job.get('model') not in model_tasks.GEMINI_38_TTS_MODELS
            or not job.get('packet') or job.get('state') not in ('fail', 'failed') or not job.get('task_id')
            or isinstance(job.get('credits_consumed'), bool) or job.get('credits_consumed') != 0):
        return None
    recovery = policy(root).get('tts_recovery', {})
    if str(job.get('provider_code')) in recovery.get('transient_provider_codes', []):
        return recovery.get('preferred_fallback')
    return None


@guarded
def prepare_tts_fallback(run, relative, failed_job_id, *, failed_run=None, speech_ids=None):
    root = run.parent.parent
    evidence_run = failed_run or run
    require(evidence_run.parent == run.parent and re.fullmatch(r'[a-f0-9]{64}', failed_job_id),
            'Use a recorded job ID from this workspace')
    failure = read_json(inside(evidence_run, f'jobs/{failed_job_id}.json'))
    require(failure.get('id') == failed_job_id, 'Fallback failure receipt does not match the recorded job')
    model = tts_recovery_model(root, failure)
    require(model == 'google/gemini-2-5-pro-tts',
            'Fallback requires a confirmed terminal zero-credit Gemini 3.8 TTS provider failure')
    current = model_tasks.packet(run, relative)
    require(current['payload']['model'] in model_tasks.GEMINI_38_TTS_MODELS
            and current['source_sha256'] == failure.get('source_sha256'),
            'Fallback must use a current Gemini 3.8 packet and evidence from the same source')
    budget = budgets.for_run(run)
    require(budget['id'] == budgets.for_run(evidence_run)['id'] and budget['state'] == 'open',
            'Fallback must use the original open request budget')
    for job_path in (run / 'jobs').glob('*.json'):
        job = read_json(job_path)
        if job.get('model') in model_tasks.GEMINI_38_TTS_MODELS:
            require(job.get('state') in ('success', 'fail', 'failed')
                    and job.get('credits_consumed') is not None,
                    'Reconcile outstanding Gemini 3.8 TTS tasks and billing before preparing fallback')

    request = read_json(run / 'inputs/request.json')
    locale = request['target_language']
    recovery = policy(root)['tts_recovery']
    require(recovery.get('authority') == 'user' and recovery.get('authorization_ref') and recovery.get('source_quote'),
            'TTS fallback needs a standing user authorization')
    original_ids = current['speech_ids']
    ids = speech_ids or original_ids
    require(len(ids) == len(set(ids)) and set(ids) <= set(original_ids), 'Select distinct speech IDs from the supplied packet')
    speeches = {item['id']: item['target_text'] for item in read_json(run / 'analysis/inventory.json')['speech_segments']}
    inputs = current['payload']['input']
    turns = inputs['dialogue_turns']
    if len(turns) == 1:
        turns = turns * len(original_ids)
    else:
        require(len(turns) == len(original_ids) and all(
            normalized(turn['text']) == normalized(speeches[key]) for key, turn in zip(original_ids, turns)),
            'Provide a current packet with exactly one voice turn per speech ID')
    voices = {entry['speaker_id']: entry['voice_name'] for entry in inputs['speakers']}
    grant = {'authority': recovery['authority'], 'source': recovery['authorization_ref'],
             'quote': recovery['source_quote'], 'model': model, 'source_sha256': current['source_sha256'],
             'target_languages': [locale], 'request_budget': budget['id']}
    grant_path = f'inputs/tts-fallback-authority-{object_hash(grant)[:16]}.json'
    write_json(run / grant_path, grant)
    authorization = {'path': grant_path, 'sha256': file_hash(run / grant_path)}
    require_remote_task(model, run=run, authorization=authorization)

    packets = []
    for speech_id, turn in zip(original_ids, turns):
        if speech_id not in ids:
            continue
        voice = voices[turn['speaker_id']]
        style = turn.get('style', '').strip()
        scene = (f'Speak only the exact supplied line in {locale}. Use natural, clear speech. '
                 'Finish every word. Voice only, with no speaker labels, extra words, music or effects.')
        if style:
            scene += ' Delivery: ' + style
        data = {'source_sha256': current['source_sha256'], 'purpose': 'Gemini 2.5 Pro fallback for finalized TTS',
                'estimated_credits': recovery['estimated_credits_per_line'], 'speech_ids': [speech_id],
                'model_authorization': authorization, 'payload': {'model': model, 'input': {
                    'scene': scene, 'speakers': [{'speaker_id': 'Speaker 1', 'voice_name': voice}],
                    'dialogue_turns': [{'speaker_id': 'Speaker 1', 'text': speeches[speech_id]}]}}}
        digest = object_hash(data)
        packet_path = f'inputs/tts-fallback-{digest[:16]}.json'
        write_json(run / packet_path, data)
        model_tasks.packet(run, packet_path)
        existing_job = run / 'jobs' / f'{digest}.json'
        existing = read_json(existing_job) if existing_job.exists() else {}
        packets.append({'speech_id': speech_id, 'packet': packet_path, 'job': digest,
                        'state': existing.get('state', 'prepared'), 'task_id': existing.get('task_id')})
    receipt = {'model': model, 'request_budget': budget['id'], 'failed_run': evidence_run.name,
               'failed_job': failed_job_id, 'failed_task_id': failure['task_id'], 'packets': packets}
    receipt_path = f'inputs/tts-fallback-receipt-{object_hash(receipt)[:16]}.json'
    write_json(run / receipt_path, receipt)
    return {**receipt, 'receipt': receipt_path, 'paid_submission': False}
