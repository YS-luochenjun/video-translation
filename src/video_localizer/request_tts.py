"""Explicit human-authorized, request-bound Microsoft speech generation.

This optional adapter does not change the default provider or use KIE credentials.
"""
import asyncio
import importlib.metadata
import sys
from pathlib import Path

from . import captions, media, workflow
from .common import (CODE_ROOT, file_hash, guarded, inside, object_hash, read_json,
                     require, utc_now, write_json)

MODEL = 'microsoft/edge-neural-tts'


def validate(run, relative):
    spec = read_json(inside(run, relative))
    source = file_hash(workflow.source_path(run))
    request = read_json(run / 'inputs/request.json')
    require(spec.get('source_sha256') == source, 'Speech source changed')
    authorization = spec.get('model_authorization', {})
    grant_path = inside(run, authorization['path'])
    require(file_hash(grant_path) == authorization['sha256'], 'Speech authorization changed')
    grant = read_json(grant_path)
    require(grant.get('external_destination_consent') is True
            and grant.get('destination') == 'Microsoft online speech',
            'Explicit consent to send this script to Microsoft online speech is required')
    require(grant.get('authority') == 'user' and grant.get('source') and grant.get('quote')
            and grant.get('model') == MODEL and grant.get('source_sha256') == source
            and request['target_language'] in grant.get('target_languages', []),
            'Microsoft speech needs explicit source/model/language-bound human authorization')
    from .budgets import for_source
    require(for_source(source, run.parent.parent)['id'] == grant.get('request_budget'),
            'Speech authorization belongs to another request budget')
    inventory = read_json(run / 'analysis/inventory.json')
    lines = spec.get('lines', [])
    require([row['id'] for row in lines] == [row['id'] for row in inventory['speech_segments']],
            'Speech generation must cover the ordered final script')
    captions.validate_spoken_copy(inventory, lines)
    voices = read_json(inside(run, spec['voice_inventory']['path']))
    require(file_hash(inside(run, spec['voice_inventory']['path'])) == spec['voice_inventory']['sha256'],
            'Available voice inventory changed')
    available = {voice['ShortName'] for voice in voices}
    mapping = {}
    for row, speech in zip(lines, inventory['speech_segments']):
        require(row['voice'] in available, 'Voice is not in the observed available inventory')
        character = speech['character_id']
        require(character not in mapping or mapping[character] == row['voice'],
                'A recurring role must retain its voice')
        mapping[character] = row['voice']
    require(len(set(mapping.values())) == len(mapping), 'Each role needs a distinct voice')
    return spec


async def _generate(run, spec, job, job_path):
    sys.path.insert(0, str(CODE_ROOT / '.runtime/deps/tts'))
    import edge_tts
    from . import audio
    directory = run / 'outputs/request-tts' / job['id'][:20]
    directory.mkdir(parents=True, exist_ok=True)
    results = []
    for line in spec['lines']:
        voice = directory / (line['id'] + '.mp3')
        metadata = directory / (line['id'] + '-boundaries.jsonl')
        previous = next((row for row in job.get('lines', []) if row['id'] == line['id']), None)
        if not previous or not voice.is_file() or file_hash(voice) != previous['sha256']:
            require(not voice.exists(), 'Partial voice output exists; inspect it before an explicit recovery')
            communicator = edge_tts.Communicate(line['target_text'], voice=line['voice'],
                                                rate=line.get('rate', '+10%'))
            await communicator.save(str(voice), str(metadata))
            signal, _ = audio.inspect(voice)
            require(signal['audible_signal'], 'Microsoft speech returned no audible signal')
            previous = {'id': line['id'], 'path': voice.relative_to(run).as_posix(),
                        'sha256': file_hash(voice), 'voice': line['voice'],
                        'target_text': line['target_text'], 'signal': signal,
                        'boundary_metadata': metadata.relative_to(run).as_posix()}
            job.setdefault('lines', []).append(previous)
            write_json(job_path, job)
        results.append(previous)
    listing = directory / 'concat.txt'
    listing.write_text('\n'.join("file '" + Path(row['path']).name + "'" for row in results), encoding='utf-8')
    combined = directory / 'combined.wav'
    media.ffmpeg(['-f', 'concat', '-safe', '0', '-i', listing,
                  '-c:a', 'pcm_s16le', '-ar', '24000', '-ac', '1', combined])
    job.update(state='success', credits_consumed=0, result=combined.relative_to(run).as_posix(),
               result_sha256=file_hash(combined), completed_at=utc_now(),
               package_version=importlib.metadata.version('edge-tts'), results=results,
               billing_evidence='Microsoft public online read-aloud client; no account or paid API credentials used. KIE was not called.')
    write_json(job_path, job)
    from .budgets import sync
    sync(run)
    return {'job': job['id'], 'result': job['result'], 'state': job['state'], 'credits_consumed': 0}


@guarded
def generate(run, relative):
    spec = validate(run, relative)
    digest = object_hash(spec)
    path = run / 'jobs' / (digest + '.json')
    if path.exists():
        job = read_json(path)
        if job.get('state') == 'success':
            require(file_hash(inside(run, job['result'])) == job['result_sha256'], 'Speech result changed')
            return {'job': digest, 'result': job['result'], 'state': 'success', 'reused': True}
    else:
        from .batches import reserve
        binding = reserve(run, digest, .001)
        job = {'id': digest, 'kind': 'audio_task', 'model': MODEL, 'provider': 'Microsoft',
               'packet': relative, 'source_sha256': spec['source_sha256'],
               'state': 'preparing', 'estimated_credits': .001, 'credits_consumed': 0,
               'batch_budget': binding, 'created_at': utc_now(), 'lines': [],
               'billing_evidence': 'Unpaid public read-aloud route; no paid account configured.'}
        write_json(path, job)
    try:
        return asyncio.run(_generate(run, spec, job, path))
    except Exception as exc:
        job.update(state='failed', error=type(exc).__name__, credits_consumed=0)
        write_json(path, job)
        raise
