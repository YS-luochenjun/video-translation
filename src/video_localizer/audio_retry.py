"""One explicitly requested retry; unknown original charges remain reserved."""
from .common import file_hash, inside, object_hash, read_json, require


def authorized_retry(run, descriptor, binding):
    from .budgets import _index
    path = inside(run, binding['path'])
    require(file_hash(path) == binding['sha256'], 'Audio retry authorization changed')
    grant = read_json(path)
    original_id = object_hash(descriptor)
    original_path = run / 'jobs' / (original_id + '.json')
    require(grant.get('authority') == 'user' and grant.get('authorization_ref')
            and grant.get('source_quote') and grant.get('retry_of') == original_id,
            'An explicit user grant for this exact original audio request is required')
    require(original_path.is_file() and file_hash(original_path) == grant.get('original_job_sha256'),
            'Original audio journal changed; inspect it before retrying')
    original = read_json(original_path)
    require(original.get('state') == 'ambiguous'
            and original.get('failure_stage') == 'model_request'
            and not any(original.get(k) for k in ('task_id', 'response_id', 'response_path', 'result')),
            'Recover an existing task/response instead of resubmitting it')
    require(all(original.get(k) == v for k, v in descriptor.items()),
            'Original audio request does not match the selected media and purpose')
    require(all(grant.get(k) == descriptor.get(k) for k in
                ('source_sha256', 'video_sha256', 'candidate_audio_sha256', 'model')),
            'Audio retry grant belongs to different media or model')
    scope = _index(run.parent.parent).get('runs', {}).get(run.name, {}).get('scope')
    require(scope and grant.get('request_budget') == scope
            and original.get('batch_budget', {}).get('request_budget') == scope,
            'Audio retry grant belongs to another request budget')
    require(grant.get('target_language') == read_json(run / 'inputs/request.json')['target_language'],
            'Audio retry grant belongs to another target language')
    require(grant.get('maximum_additional_attempts') == 1,
            'Audio retry authorization must allow exactly one additional attempt')
    attempt = grant.get('retry_attempt', 1)
    require(type(attempt) is int and 1 <= attempt <= 2, 'Audio model retry limit reached')
    if attempt == 2:
        prior_id = object_hash({**descriptor, 'retry_of': original_id, 'retry_attempt': 1})
        prior_path = run / 'jobs' / (prior_id + '.json')
        require(grant.get('previous_retry') == prior_id and prior_path.is_file()
                and file_hash(prior_path) == grant.get('previous_retry_sha256'),
                'Second audio retry must bind the unchanged previous attempt')
        prior = read_json(prior_path)
        require(prior.get('state') == 'ambiguous' and prior.get('failure_stage') == 'model_request'
                and not any(prior.get(k) for k in ('task_id', 'response_id', 'response_path', 'result')),
                'Recover the previous audio response instead of submitting another attempt')
        prior_grant = read_json(inside(run, prior['retry_authorization']['path']))
        require(file_hash(inside(run, prior['retry_authorization']['path'])) == prior['retry_authorization']['sha256']
                and grant['authorization_ref'] != prior_grant['authorization_ref'],
                'Second audio retry needs a new explicit user instruction')
    # Stable identity prevents a second grant/path from producing another retry.
    identity = {'retry_of': original_id, 'retry_attempt': attempt}
    retry_id = object_hash({**descriptor, **identity})
    existing = run / 'jobs' / (retry_id + '.json')
    if existing.exists():
        require(read_json(existing).get('retry_authorization') == binding,
                'This original audio request already has an authorized retry')
    return identity
