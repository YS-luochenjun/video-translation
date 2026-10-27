"""Journaled, source-bound KIE audio tasks and small diagnostic video probes."""
from __future__ import annotations

import copy
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import audio, media
from .common import file_hash, guarded, inside, lock, object_hash, read_json, require, require_number, utc_now, write_json
from .kie import ApiError, KieClient, download

VIDEO_MODELS = ('wan/2-7-videoedit', 'bytedance/seedance-2-fast', 'wan/2-6-flash-video-to-video', 'bytedance/seedance-2-mini')
GEMINI_TTS_MODELS = ('google/gemini-2-5-pro-tts', 'google/gemini-3-1-flash-tts', 'google/gemini-3-8-flash-lite-tts')


def packet(run, relative):
    from .workflow import source_path
    data = read_json(inside(run, relative))
    require(data.get('source_sha256') == file_hash(source_path(run)), 'Audio task source binding mismatch')
    require(bool(data.get('purpose')), 'Audio task needs an explicit purpose')
    require_number(data.get('estimated_credits'), 'Audio task estimate', minimum=0.01, maximum=10000)
    payload = data.get('payload', {})
    inputs = payload.get('input', {})
    model = payload.get('model')
    video_model = model in VIDEO_MODELS
    require(video_model or model in (*GEMINI_TTS_MODELS, 'ai-music-api/separate-vocals', 'elevenlabs/text-to-speech-multilingual-v2', 'elevenlabs/text-to-dialogue-v3', 'elevenlabs/text-to-speech-turbo-2-5'), 'Unsupported model task')
    require(set(payload) == {'model', 'input'}, 'Unexpected audio task payload fields')
    if video_model:
        require(isinstance(inputs.get('prompt'), str) and 0 < len(inputs['prompt']) <= 5000, 'Video probe needs a bounded prompt')
        require('video' in data.get('assets', {}) and data.get('source_interval') and len(data['source_interval']) == 2, 'Video probe needs a source interval and clip')
        start, end = data['source_interval']
        require(0 <= start < end and end - start <= 10, 'Diagnostic video probe interval must be at most 10s')
        if model == 'wan/2-6-flash-video-to-video':
            duration=inputs.get('duration')
            require(duration in ('5','10') and abs(end-start-int(duration))<=.15,'Wan Flash probe needs its actual 5/10s interval')
            require(inputs.get('video_urls')==['ASSET:video'] and inputs.get('audio') is False
                    and inputs.get('resolution')=='720p' and inputs.get('multi_shots') is False,'Low-cost Wan Flash probe requires one source video, silent 720p and no new shots')
            require(len(inputs['prompt'])<=1500 and data['estimated_credits']>=int(duration)*4,'Wan Flash prompt/price reservation invalid')
        elif model == 'wan/2-7-videoedit':
            require(inputs.get('video_url') == 'ASSET:video' and inputs.get('audio_setting') == 'origin' and inputs.get('prompt_extend') is False, 'Visual diagnostic probe must keep source audio and exact prompt')
        else:
            require(inputs.get('reference_video_urls') == ['ASSET:video'] and inputs.get('generate_audio') is False, 'Seedance visual probe requires an explicit source video and no generated audio')
    elif model == 'ai-music-api/separate-vocals':
        require(set(inputs) <= {'audio_url', 'type', 'stem_name'} and inputs.get('audio_url') == 'ASSET:audio', 'Separation requires a bound uploaded audio file')
        require(inputs.get('type') in ('separate_vocal', 'split_stem', 'split_stem_advanced'), 'Unknown separation type')
        require(inputs.get('type') != 'split_stem_advanced' or bool(inputs.get('stem_name')), 'Advanced separation needs a stem')
    elif model == 'elevenlabs/text-to-speech-turbo-2-5':
        from .model_routing import require_remote_task
        require_remote_task(model, run=run, authorization=data.get('model_authorization'))
        require(set(inputs) <= {'text', 'voice', 'stability', 'similarity_boost', 'style', 'speed',
                                'timestamps', 'previous_text', 'next_text', 'language_code'},
                'Unsupported ElevenLabs Turbo input field')
        require(isinstance(inputs.get('text'), str) and bool(inputs['text'].strip())
                and len(inputs['text']) <= 5000 and bool(inputs.get('voice')),
                'ElevenLabs Turbo needs bounded exact text and an explicit voice')
        request = read_json(run / 'inputs/request.json')
        require(inputs.get('language_code') == request['target_language'],
                'ElevenLabs Turbo language must match the target request')
        characters = len(inputs['text'].encode('utf-16-le')) // 2
        require(data['estimated_credits'] >= characters * .006,
                'Reserve the documented ElevenLabs Turbo character price')
        for key in ('stability', 'similarity_boost', 'style'):
            if key in inputs:
                require_number(inputs[key], 'ElevenLabs ' + key, minimum=0, maximum=1)
        if 'speed' in inputs:
            require_number(inputs['speed'], 'ElevenLabs speed', minimum=.7, maximum=1.2)
        if 'timestamps' in inputs:
            require(isinstance(inputs['timestamps'], bool), 'ElevenLabs timestamps must be boolean')
    elif model == 'elevenlabs/text-to-dialogue-v3':
        from .model_routing import require_remote_task
        require_remote_task(model, run=run, authorization=data.get('model_authorization'))
        require(set(inputs) <= {'dialogue', 'stability', 'language_code'}, 'Unsupported ElevenLabs V3 input field')
        dialogue = inputs.get('dialogue')
        require(isinstance(dialogue, list) and bool(dialogue) and all(
            isinstance(turn, dict) and set(turn) == {'text', 'voice'}
            and isinstance(turn['text'], str) and turn['text'].strip()
            and isinstance(turn['voice'], str) and turn['voice'].strip() for turn in dialogue),
            'ElevenLabs V3 needs exact dialogue text and explicit voices')
        characters = sum(len(turn['text'].encode('utf-16-le')) // 2 for turn in dialogue)
        require(characters <= 5000, 'ElevenLabs V3 dialogue exceeds 5000 characters')
        require(data['estimated_credits'] >= characters * .014, 'Reserve the documented ElevenLabs V3 character price')
        if 'stability' in inputs:
            require_number(inputs['stability'], 'ElevenLabs stability', minimum=0, maximum=1)
    elif model in GEMINI_TTS_MODELS:
        modern = model == 'google/gemini-3-8-flash-lite-tts'
        if model != 'google/gemini-2-5-pro-tts':
            from .model_routing import require_remote_task
            require_remote_task(model, run=run, authorization=data.get('model_authorization'))
        allowed = ({'speakers', 'dialogue_turns', 'temperature', 'filler_words'} if modern
                   else {'speakers', 'dialogue_turns', 'scene', 'temperature', 'sample_context'})
        require(set(inputs) <= allowed,
                'Unsupported Gemini TTS input field; use tts-packet instead of guessing provider parameters')
        if modern:
            require(1 <= len(inputs.get('speakers', [])) <= 2, 'Gemini 3.8 supports one or two speakers')
            require(inputs.get('filler_words', False) is False, 'Exact-copy localization forbids generated filler words')
            require_number(inputs.get('temperature', 1), 'Gemini temperature', minimum=0, maximum=2)
            require(all(set(turn) <= {'speaker_id', 'text', 'style'}
                        and isinstance(turn.get('text'), str) and 0 < len(turn['text']) <= 10000
                        and ('style' not in turn or isinstance(turn['style'], str))
                        for turn in inputs.get('dialogue_turns', [])), 'Invalid Gemini 3.8 dialogue turn')
        require(bool(inputs.get('speakers')) and bool(inputs.get('dialogue_turns')), 'Gemini TTS needs speaker configuration and lines')
        require(all(isinstance(s, dict) and set(s) <= {'speaker_id', 'voice_name', 'audio_profile', 'accent', 'style', 'pace'}
                    and isinstance(s.get('voice_name'), str) and s['voice_name'].strip()
                    for s in inputs['speakers']), 'Gemini TTS needs explicit voice_name and documented speaker fields')
        # Optional delivery controls remain available. Their provider enums must be
        # verified before submission; the local shape check does not invent enums.
        require(all(isinstance(s[key], str) and s[key].strip() for s in inputs['speakers']
                    for key in ('audio_profile', 'accent', 'style', 'pace') if key in s),
                'Gemini speaker controls must be nonempty strings')
        speakers = {speaker.get('speaker_id') for speaker in inputs['speakers']}
        require(len(speakers) == len(inputs['speakers']), 'Duplicate Gemini TTS speaker')
        import re
        require(all(isinstance(speaker, str) and re.fullmatch(r'Speaker [1-9][0-9]*', speaker) for speaker in speakers), 'Gemini speaker_id must use Speaker N format')
        require(all(turn.get('speaker_id') in speakers and turn.get('text') for turn in inputs['dialogue_turns']), 'Unbound Gemini TTS speaker or text')
    else:
        require(isinstance(inputs.get('text'), str) and bool(inputs['text'].strip()) and len(inputs['text']) <= 10000, 'TTS text missing or too long')
        require(inputs.get('voice') and inputs.get('language_code') == 'zh', 'This TTS route needs an explicit voice and Chinese language')
    if model in (*GEMINI_TTS_MODELS, 'elevenlabs/text-to-speech-multilingual-v2', 'elevenlabs/text-to-dialogue-v3', 'elevenlabs/text-to-speech-turbo-2-5'):
        from .captions import normalized, validate_spoken_copy
        inventory = read_json(run / 'analysis/inventory.json')
        ids = data.get('speech_ids', [])
        require(isinstance(ids, list) and bool(ids) and len(ids) == len(set(ids)), 'TTS needs ordered unique speech_ids from the final script')
        speeches = {item['id']: item for item in inventory.get('speech_segments', [])}
        require(all(key in speeches for key in ids), 'TTS speech_ids not found in final script')
        actual_text = (''.join(turn['text'] for turn in inputs['dialogue_turns']) if model in GEMINI_TTS_MODELS
                       else ''.join(turn['text'] for turn in inputs['dialogue']) if model == 'elevenlabs/text-to-dialogue-v3'
                       else inputs['text'])
        require(normalized(actual_text) == normalized(''.join(speeches[key]['target_text'] for key in ids)),
                'TTS copy differs from final speech script')
        validate_spoken_copy(inventory, [speeches[key] for key in ids])
    for asset in data.get('assets', {}).values():
        path = inside(run, asset['path'])
        require(path.is_file() and file_hash(path) == asset['sha256'], 'Audio task asset missing or changed')
        if video_model:
            meta = media.probe(path)
            require(abs(meta['duration'] - (data['source_interval'][1]-data['source_interval'][0])) <= .15, 'Video probe clip duration differs from interval')
        else:
            require(audio.inspect(path)[0]['has_track'], 'Audio task asset has no audio')
    if model == 'ai-music-api/separate-vocals':
        require('audio' in data.get('assets', {}), 'Missing separation source audio')
    if video_model and (data.get('model_authorization') or model == 'bytedance/seedance-2-mini'):
        from .video_tests import check_packet
        check_packet(run, data)
    return data


def _authorized_rate_limit_retry(run, job):
    """An explicit 429 rejection has no accepted task; keep its old cost reservation."""
    request_path = run / 'inputs/request.json'
    grant = read_json(request_path).get('provider_retry_authorization', {}) if request_path.exists() else {}
    return (grant.get('allow_explicit_429') is True and bool(grant.get('authorization_ref'))
            and bool(grant.get('source_quote')) and job.get('state') == 'failed'
            and not job.get('task_id') and str(job.get('error', '')).startswith('KIE code 429:'))


@guarded
def submit(run, relative, client=None, retry_failed=False):
    from .workflow import execution_limits, reserved_credits
    data = packet(run, relative)
    digest = object_hash(data)
    original = digest
    retry_attempt = 0
    if retry_failed:
        # Follow the recorded chain instead of repeatedly returning a failed
        # first retry. Active/ambiguous attempts are reused, never duplicated.
        for retry_attempt in range(1, min(2, execution_limits(run)['max_revision_rounds']) + 1):
            failed = read_json(run / 'jobs' / (original + '.json'))
            require((failed.get('state') in ('fail', 'failed') and failed.get('task_id') and failed.get('credits_consumed') == 0)
                    or _authorized_rate_limit_retry(run, failed),
                    'Retry requires a known terminal zero-cost provider failure')
            digest = object_hash({'packet': data, 'retry_of': original})
            previous_retry = run / 'jobs' / (digest + '.json')
            if not previous_retry.exists():
                break
            saved = read_json(previous_retry)
            if saved.get('state') not in ('fail', 'failed') or (not saved.get('task_id') and not _authorized_rate_limit_retry(run, saved)):
                break
            original = digest
        else:
            require(False, 'Audio task retry limit reached; preserve all attempts')
    path = run / 'jobs' / (digest + '.json')
    client = client or KieClient()
    with lock(run / 'jobs/.submit.lock'):
        if path.exists():
            saved = read_json(path)
            if saved['state'] == 'failed' and not saved.get('task_id'):
                from .budgets import resume_undispatched
                resume_undispatched(run, digest)
                return _resume_undispatched(run, data, saved, path, client)
            return {'job': digest, 'state': saved['state'], 'task_id': saved.get('task_id'), 'reused': True}
        from .model_routing import require_remote_task
        require_remote_task(data['payload']['model'], run=run, authorization=data.get('model_authorization'))
        if data['payload']['model'] in VIDEO_MODELS:
            from .cost import check_new_video_task
            check_new_video_task(data['payload']['model'], data['estimated_credits'],
                                 run=run, authorization=data.get('model_authorization'))
        limits = execution_limits(run)
        jobs = [read_json(p) for p in (run / 'jobs').glob('*.json')]
        require(len(jobs) < limits['max_paid_jobs_per_run'], 'Paid job budget reached')
        require(sum(reserved_credits(job, limits['max_estimated_credits_per_run']) for job in jobs) + data['estimated_credits'] <= limits['max_estimated_credits_per_run'], 'Estimated credit budget reached')
        from .batches import reserve
        batch_budget = reserve(run, digest, data['estimated_credits'])
        job = {'id': digest, 'kind': 'audio_task', 'plan_id': 'audio:' + digest[:16], 'segment': 'audio-model',
               'packet': relative, 'packet_sha256': digest, 'source_sha256': data['source_sha256'],
               'model': data['payload']['model'], 'purpose': data['purpose'], 'state': 'preparing',
               'estimated_credits': data['estimated_credits'], 'created_at': utc_now(), 'credits_before': None,
               'task_result_kind': 'video' if data['payload']['model'] in VIDEO_MODELS else 'audio',
               'execution_limits': {key: limits[key] for key in ('max_paid_jobs_per_run', 'max_estimated_credits_per_run')}}
        job['batch_budget'] = batch_budget
        if data.get('model_authorization'):
            job['model_authorization'] = data['model_authorization']
        if retry_failed:
            job['retry_of'] = original
            job['retry_attempt'] = retry_attempt
            job['retry_reason'] = ('Explicit user-authorized identical-packet retry after provider 429 rejection; '
                                   'prior billing reservation retained, at most two rounds'
                                   if _authorized_rate_limit_retry(run, failed) else
                                   'Explicit identical-packet retry after known zero-cost terminal provider failure; at most two rounds')
        write_json(path, job)
        try:
            job['credits_before'] = client.credits()
            write_json(path, job)
            uploaded = {}
            for name, asset in data.get('assets', {}).items():
                uploaded[name] = client.upload(inside(run, asset['path']))
            payload = copy.deepcopy(data['payload'])
            for key, value in payload['input'].items():
                if isinstance(value, str) and value.startswith('ASSET:'):
                    payload['input'][key] = uploaded[value.split(':', 1)[1]]
                elif isinstance(value, list):
                    payload['input'][key] = [uploaded[v.split(':', 1)[1]] if isinstance(v, str) and v.startswith('ASSET:') else v for v in value]
            job['state'] = 'submitting'
            write_json(path, job)
            job['task_id'] = (client.create(payload, run=run, model_authorization=data['model_authorization'])
                              if data.get('model_authorization') else client.create(payload))
            job['state'] = 'submitted'
        except ApiError as exc:
            job['state'] = 'ambiguous' if exc.ambiguous and job['state'] == 'submitting' else 'failed'
            job['error'] = str(exc)
            write_json(path, job)
            raise
        except Exception:
            job['state'] = 'ambiguous' if job['state'] == 'submitting' else 'failed'
            job['error'] = 'Local audio task failure; inspect journal before retry'
            write_json(path, job)
            raise
        write_json(path, job)
    return {'job': digest, 'state': job['state'], 'task_id': job['task_id']}


def _resume_undispatched(run, data, job, path, client):
    # The request ledger proves no charged POST was attempted. Keep its identity,
    # budget reservation and failure history rather than minting another job.
    require(not data.get('assets'), 'Asset-bearing failures require explicit upload recovery')
    job.setdefault('recovery_history', []).append({'at': utc_now(), 'previous_error': job.get('error'),
                                                  'basis': 'request ledger has no dispatch'})
    try:
        job['credits_before'] = client.credits()
        job['state'] = 'submitting'
        write_json(path, job)
        job['task_id'] = (client.create(data['payload'], run=run, model_authorization=data['model_authorization'])
                          if data.get('model_authorization') else client.create(data['payload']))
        job['state'] = 'submitted'
        job.pop('error', None)
    except ApiError as exc:
        job['state'] = 'ambiguous' if exc.ambiguous and job['state'] == 'submitting' else 'failed'
        job['error'] = str(exc)
        write_json(path, job)
        raise
    write_json(path, job)
    return {'job': job['id'], 'state': job['state'], 'task_id': job['task_id'], 'resumed_before_dispatch': True}


@guarded
def collect(run, job, urls):
    """Keep every returned stem, its original name, signal report and content hash."""
    records = []
    for index, url in enumerate(urls):
        name = unquote(Path(urlparse(url).path).name)
        suffix = Path(name).suffix.lower()
        require(suffix in ('.mp3', '.wav', '.m4a', '.flac', '.ogg', '.aac', '.json'), 'Unexpected audio result type')
        destination = run / 'outputs/audio-models' / job['id'] / f'{index:02d}{suffix}'
        if not destination.exists():
            download(url, destination)
        record = {'path': destination.relative_to(run).as_posix(), 'sha256': file_hash(destination), 'provider_name': name}
        if suffix == '.json':
            require(isinstance(read_json(destination), (dict, list)), 'Invalid TTS alignment JSON')
        else:
            report, _ = audio.inspect(destination)
            require(report['has_track'] and report['audible_signal'], 'Audio model result is missing or silent')
            record['signal'] = report
        records.append(record)
    require(any('signal' in record for record in records), 'No audio result returned')
    manifest = run / 'outputs/audio-models' / job['id'] / 'manifest.json'
    write_json(manifest, {'task_id': job['task_id'], 'source_sha256': job['source_sha256'], 'model': job['model'], 'results': records})
    first = next(record for record in records if 'signal' in record)
    job.update({'result': first['path'], 'result_sha256': first['sha256'], 'results': records,
                'result_manifest': manifest.relative_to(run).as_posix(), 'result_manifest_sha256': file_hash(manifest)})
