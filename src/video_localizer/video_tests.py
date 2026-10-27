"""Explicit, source/request/run-bound video comparisons; never a production fallback."""
from pathlib import Path

from .common import file_hash, inside, read_json, require, require_number

MODELS = ('wan/2-7-videoedit', 'wan/2-6-flash-video-to-video', 'bytedance/seedance-2-mini')


def authorize(model, run, authorization):
    require(run is not None and authorization, 'Video test requires explicit source/request-bound user authorization')
    run = Path(run).resolve()
    path = inside(run, authorization['path'])
    require(file_hash(path) == authorization['sha256'], 'Video test authorization changed')
    grant = read_json(path)
    source = read_json(run / 'run.json')['source_sha256']
    request = read_json(run / 'inputs/request.json')
    require(grant.get('authority') == 'user' and grant.get('quote') and grant.get('source')
            and grant.get('capability') == 'video_erasure_comparison'
            and grant.get('run_id') == run.name and grant.get('source_sha256') == source,
            'Video test authorization does not cover this source/run/capability')
    models = grant.get('models', [])
    require(isinstance(models, list) and models and set(models).issubset(MODELS) and model in models,
            'Video test model is outside the explicit comparison scope')
    require(request['target_language'] in grant.get('target_languages', []), 'Video test language binding changed')
    from .budgets import for_source
    require(for_source(source, run.parent.parent)['id'] == grant.get('request_budget'),
            'Video test authorization does not match this request budget')
    require_number(grant.get('max_estimated_credits'), 'comparison credit limit', minimum=.01)
    require(grant.get('max_submissions_per_model') == 1, 'Comparison authorizes one initial submission per model')
    return grant


def check_packet(run, data):
    model = data['payload']['model']
    grant = authorize(model, run, data.get('model_authorization'))
    require(data.get('source_interval') == grant.get('source_interval'), 'Comparison source interval changed')
    asset = data.get('assets', {}).get('video', {})
    require(asset.get('sha256') == grant.get('clip_sha256'), 'Comparison must use the frozen common clip')
    inputs = data['payload']['input']
    require(inputs.get('resolution') == '720p', 'Comparison outputs must all use 720p')
    require(inputs.get('prompt') == grant.get('prompt'), 'Comparison must use the frozen common erasure prompt')
    estimates = grant.get('estimated_credits_by_model', {})
    require(data['estimated_credits'] == estimates.get(model), 'Comparison estimate differs from the frozen price quote')
    seconds = data['source_interval'][1] - data['source_interval'][0]
    require(abs(seconds - 5) <= .001, 'This diagnostic comparison uses exactly five source seconds')
    if model == 'bytedance/seedance-2-mini':
        require(set(inputs) == {'prompt', 'reference_video_urls', 'generate_audio', 'resolution',
                               'aspect_ratio', 'duration', 'web_search'}, 'Unsupported Seedance Mini comparison field')
        require(inputs.get('duration') == 5 and inputs.get('aspect_ratio') == grant.get('aspect_ratio')
                and inputs.get('generate_audio') is False and inputs.get('web_search') is False,
                'Mini comparison requires fixed duration/aspect and no generated audio/search')
        require(data['estimated_credits'] >= (seconds + 5) * 5, 'Reserve Mini input plus output duration at 720p')
    return grant


def check_new_submission(model, estimate, run, authorization):
    grant = authorize(model, run, authorization)
    require(estimate == grant.get('estimated_credits_by_model', {}).get(model), 'Comparison estimate changed')
    jobs = [read_json(path) for path in (Path(run) / 'jobs').glob('*.json')]
    require(not any(job.get('model') == model for job in jobs), 'Comparison model submission already consumed; recover its original task')
    from .workflow import reserved_credits
    used = sum(reserved_credits(job, grant['max_estimated_credits']) for job in jobs)
    require(used + estimate <= grant['max_estimated_credits'], 'Comparison credit limit reached')
    return grant
