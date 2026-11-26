"""Journaled independent transcription of actual source or candidate audio."""
import json
import math

from . import audio
from .common import file_hash, guarded, inside, lock, object_hash, read_json, require, require_number, utc_now, write_json
from .kie import ApiError, KieClient, download
from .model_routing import audio_recovery_route
from .retry_activity import observed_job


@guarded
def submit(run, candidate=False, client=None, retry_failed=False):
    from .batches import reserve
    from .workflow import current_plan, execution_limits, reserved_credits, source_path

    route = audio_recovery_route('transcription_evidence')
    source = source_path(run)
    track = run / 'analysis/audio.wav'
    descriptor = {'kind': 'audio_transcription', 'model': route['model'],
                  'source_sha256': file_hash(source), 'timestamps': True}
    if candidate:
        record = read_json(run / 'outputs/candidate.json')
        require(record['plan_id'] == current_plan(run)['id']
                and file_hash(inside(run, record['path'])) == record['sha256'], 'Candidate changed')
        track = run / 'review' / record['sha256'][:12] / 'audio.wav'
        descriptor['video_sha256'] = record['sha256']
    require(track.is_file(), 'Analyze the source or capture the current candidate audio first')
    descriptor['audio_sha256'] = file_hash(track)
    descriptor['audio_path'] = track.relative_to(run).as_posix()
    digest = object_hash(descriptor)
    journal = run / 'jobs' / (digest + '.json')
    with lock(run / 'jobs/.submit.lock'):
        if retry_failed:
            require(journal.is_file(), 'No original transcription to retry')
            original = read_json(journal)
            require(original.get('state') in ('fail', 'failed') and original.get('task_id')
                    and original.get('credits_consumed') == 0
                    and str(original.get('provider_code')) in ('500', '502', '503', '504', '524'),
                    'Transcription retry requires a confirmed zero-credit terminal provider failure')
            descriptor['retry_of'] = digest
            digest = object_hash(descriptor)
            journal = run / 'jobs' / (digest + '.json')
        if journal.exists():
            saved = read_json(journal)
            return {'job': digest, 'state': saved['state'], 'task_id': saved.get('task_id'),
                    'result': saved.get('result'), 'reused': True}
        report, _ = audio.inspect(track)
        duration = require_number(report['duration'], 'Transcription duration', minimum=.001, maximum=3600)
        require(report['has_track'] and track.stat().st_size <= 200 * 1024 * 1024,
                'Transcription requires an actual audio track within the provider size limit')
        estimate = max(route['minimum_reservation'], math.ceil(duration) * route['credits_per_second'])
        limits = execution_limits(run)
        jobs = [read_json(path) for path in journal.parent.glob('*.json')]
        require(len(jobs) < limits['max_paid_jobs_per_run'], 'Paid job budget reached')
        require(sum(reserved_credits(job, limits['max_estimated_credits_per_run']) for job in jobs) + estimate
                <= limits['max_estimated_credits_per_run'], 'Estimated credit budget reached')
        job = {**descriptor, 'id': digest, 'plan_id': None, 'segment': 'audio-analysis',
               'state': 'preparing', 'task_result_kind': 'transcript', 'created_at': utc_now(),
               'estimated_credits': estimate, 'audio_duration_seconds': duration,
               'batch_budget': reserve(run, digest, estimate)}
        observed_job(journal, job)
        try:
            client = client or KieClient()
            url = client.upload(track)
            job['state'] = 'submitting'
            write_json(journal, job)
            job['task_id'] = client.transcribe_audio(url)
            job['state'] = 'submitted'
        except ApiError as exc:
            job['failure_stage'] = 'model_request' if job['state'] == 'submitting' else 'upload'
            job['state'] = 'ambiguous' if exc.ambiguous and job['state'] == 'submitting' else 'failed'
            job['error'] = str(exc)
            if exc.provider_response is not None:
                receipt = run / 'jobs' / (digest + '-response') / 'error.json'
                write_json(receipt, exc.provider_response)
                job['error_response'] = receipt.relative_to(run).as_posix()
                job['error_response_sha256'] = file_hash(receipt)
            observed_job(journal, job)
            raise
        except Exception:
            job['state'] = 'ambiguous' if job['state'] == 'submitting' else 'failed'
            observed_job(journal, job)
            raise
        observed_job(journal, job)
    return {'job': digest, 'state': job['state'], 'task_id': job['task_id']}


def collect(run, job, status):
    directory = run / 'jobs' / (job['id'] + '-response')
    response = directory / 'status.json'
    write_json(response, status)
    raw = status.get('resultJson', {})
    result = (json.loads(raw) if isinstance(raw, str) else raw).get('resultObject', {})
    require(isinstance(result.get('text'), str) and isinstance(result.get('url'), str),
            'Transcription returned no text result or word timing file')
    transcript = directory / 'transcript.json'
    if not transcript.exists():
        download(result['url'], transcript, max_bytes=20 * 1024 * 1024)
    content = read_json(transcript)
    require(isinstance(content, dict) and isinstance(content.get('text'), str)
            and isinstance(content.get('words'), list), 'Invalid transcription evidence')
    output = directory / 'evidence.json'
    write_json(output, {key: job[key] for key in ('model', 'source_sha256', 'audio_sha256', 'audio_path')
                        } | {'video_sha256': job.get('video_sha256'), 'task_id': job['task_id'],
                             'transcript': transcript.relative_to(run).as_posix(),
                             'transcript_sha256': file_hash(transcript),
                             'response': response.relative_to(run).as_posix(),
                             'response_sha256': file_hash(response),
                             'proof_boundary': 'Independent speech recognition only; pronunciation doubts, music, effects, fidelity, sync and head/tail still require review'})
    job.update(result=output.relative_to(run).as_posix(), result_sha256=file_hash(output))
