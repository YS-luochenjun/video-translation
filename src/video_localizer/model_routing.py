"""One current model per specialist capability; history is never resubmitted implicitly."""
from pathlib import Path

from .common import CODE_ROOT, ROOT, file_hash, inside, read_json, require


def policy(root=None):
    path = Path(root or ROOT) / 'config/model-routing.json'
    if not path.is_file():
        path = CODE_ROOT / 'config/model-routing.json'
    result = read_json(path)
    require(result.get('schema_version') == 1, 'Unsupported model routing policy')
    return result


def selected(capability, root=None):
    value = policy(root).get(capability)
    require(isinstance(value, str) and value, f'Missing model for {capability}')
    return value


def require_current(capability, model, root=None):
    expected = selected(capability, root)
    require(model == expected,
            f'New {capability} work uses {expected}; {model} is historical only. No automatic model fallback.')


def require_audio_analysis_model(model, run=None, authorization=None):
    if model == selected('audio_analysis'):
        return
    require(model == 'gemini-3.1-pro' and run is not None and authorization,
            'Alternative audio analysis needs explicit source/request-bound user authorization')
    run = Path(run).resolve()
    path = inside(run, authorization['path'])
    require(file_hash(path) == authorization['sha256'], 'Audio model authorization changed')
    grant = read_json(path)
    source = read_json(run / 'run.json')['source_sha256']
    request = read_json(run / 'inputs/request.json')
    require(grant.get('authority') == 'user' and grant.get('quote') and grant.get('source')
            and grant.get('model') == model and grant.get('source_sha256') == source
            and grant.get('capability') == 'audio_analysis'
            and request['target_language'] in grant.get('target_languages', []),
            'Audio model authorization does not cover this source/model/language')
    from .budgets import bind
    require(bind(run)['id'] == grant.get('request_budget'),
            'Audio model authorization does not match this request budget')


def require_remote_task(model, root=None, run=None, authorization=None):
    if model in ('wan/2-6-flash-video-to-video', 'bytedance/seedance-2-mini'):
        from .video_tests import authorize
        authorize(model, run, authorization)
        return
    current = policy(root)
    if model in (current['video'], current['tts']):
        return
    require(model in ('elevenlabs/text-to-dialogue-v3', 'elevenlabs/text-to-speech-turbo-2-5', 'google/gemini-3-1-flash-tts', 'google/gemini-3-8-flash-lite-tts')
            and run is not None and authorization,
            f'New remote tasks use {current["video"]} for video or {current["tts"]} for TTS; '
            f'{model} needs an explicit source/request-bound user authorization. No automatic fallback.')
    run = Path(run).resolve()
    path = inside(run, authorization['path'])
    require(file_hash(path) == authorization['sha256'], 'TTS model authorization changed')
    grant = read_json(path)
    source = read_json(run / 'run.json')['source_sha256']
    request = read_json(run / 'inputs/request.json')
    require(grant.get('authority') == 'user' and grant.get('quote') and grant.get('source')
            and grant.get('model') == model and grant.get('source_sha256') == source,
            'TTS model authorization does not match this source/model')
    require(request['target_language'] in grant.get('target_languages', []),
            'TTS model authorization does not cover this language')
    from .budgets import for_source
    require(for_source(source, run.parent.parent)['id'] == grant.get('request_budget'),
            'TTS model authorization does not match this request budget')
