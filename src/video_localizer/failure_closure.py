"""Close a preproduction failure without inventing a candidate or a passing review."""
from . import bundles, learning
from .common import file_hash, guarded, inside, object_hash, read_json, require, utc_now, write_json
from .evidence import EVIDENCE_SUFFIXES
from .knowledge_records import placeholder_lesson


@guarded
def close(run, relative):
    root = run.parent.parent
    require(not (run / 'outputs/candidate.json').exists(), 'Existing candidate must use quality and reflect')
    spec_path = inside(run, relative)
    spec = read_json(spec_path)
    source = read_json(run / 'run.json')
    require(spec.get('source_sha256') == source['source_sha256'] == file_hash(inside(run, source['source'])),
            'Failure source binding changed')
    require(spec.get('stage') in {'source', 'translation', 'neutral', 'audio', 'render'}, 'Invalid failure stage')
    require(spec.get('review_type') in {'same_agent', 'independent', 'user'}, 'Explicit review attribution required')
    for field in ('reviewer', 'reason'):
        require(isinstance(spec.get(field), str) and len(spec[field].strip()) >= 3, 'Failure needs '+field)
    lesson = spec.get('lesson')
    require(lesson is None or isinstance(lesson, str), 'Failure lesson must be text')
    require(isinstance(spec.get('unreviewed_scope'), list) and spec['unreviewed_scope']
            and all(isinstance(v, str) and v.strip() for v in spec['unreviewed_scope']), 'Declare unreviewed scope')
    observations = spec.get('observations')
    require(isinstance(observations, list) and observations, 'Actual failure observations required')
    records = [spec_path]
    for observation in observations:
        require(isinstance(observation.get('observation'), str) and len(observation['observation'].strip()) >= 8,
                'Meaningful failure observation required')
        require(observation.get('evidence'), 'Failure needs bound evidence')
        for asset in observation['evidence']:
            path = inside(run, asset['path'])
            require(path.suffix.lower() in EVIDENCE_SUFFIXES and path.is_file()
                    and file_hash(path) == asset.get('sha256'), 'Failure evidence missing or changed')
            records.append(path)
    identity = object_hash({'run': run.name, 'spec': spec})[:20]
    case_id = 'failed-'+run.name[:40]+'-'+identity
    directory = run / 'review/failures' / identity
    report_path = directory / 'observations.json'
    if not report_path.exists():
        write_json(report_path, {'schema_version': 1, 'spec': spec, 'decision': 'failed_preproduction',
                   'created_at': utc_now(), 'source_sha256': source['source_sha256'],
                   'approved_for_reuse': False, 'video_quality_approval': False,
                   'accounting': 'No budget edits or inferred zero costs. Existing request reservations remain authoritative.'})
    else:
        require(read_json(report_path)['spec'] == spec, 'Failure report changed')
    records.append(report_path)
    scope = {'source_sha256': source['source_sha256'], 'target_language': read_json(run / 'inputs/request.json')['target_language'],
             'stage': spec['stage'], 'workflow': 'video-localization'}
    candidate_path = root / 'knowledge/local/candidates' / (case_id+'.json')
    case_path = root / 'knowledge/local/examples' / case_id
    candidate = None
    if candidate_path.exists():
        candidate = read_json(candidate_path)
        require(candidate.get('id') == case_id and candidate.get('scope') == scope
                and candidate.get('case') == case_path.relative_to(root).as_posix()
                and candidate.get('hypothesis') == (lesson or spec.get('hypothesis'))
                and candidate.get('limitations') == spec['unreviewed_scope']
                and candidate.get('status') == 'candidate'
                and candidate.get('outcome') == 'failed_preproduction'
                and candidate.get('company_preference') is False, 'Failure candidate changed')
        bundles.verify(case_path)
    elif not placeholder_lesson(lesson):
        case_path = learning.capture_case(case_id, lesson, scope, root=root, run=run,
                                          records=list(dict.fromkeys(records)), status='candidate')
        bundles.verify(case_path)
        candidate = {'id': case_id, 'status': 'candidate', 'scope': scope,
                     'case': case_path.relative_to(root).as_posix(), 'outcome': 'failed_preproduction',
                     'hypothesis': lesson, 'company_preference': False,
                     'limitations': spec['unreviewed_scope']}
        write_json(candidate_path, candidate)
    receipt = {'state': 'failed_preproduction', 'case': candidate['case'] if candidate else None,
               'candidate': candidate_path.relative_to(root).as_posix() if candidate else None,
               'inbox': learning.enqueue(candidate, root) if candidate else None,
               'report': report_path.relative_to(run).as_posix(), 'package': None,
               'automatic_pass': False, 'budget_changed': False}
    write_json(directory / 'closure.json', receipt)
    return receipt
