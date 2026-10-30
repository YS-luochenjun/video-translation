"""Evidence-led critique and bounded improvement, independent of delivery approval."""
from .common import (file_hash, guarded, inside, object_hash, read_json,
                     require, write_json)


def agenda(run):
    """Navigation invoked by work-packet; never manufacture a review or a retry."""
    inventory_path = run / 'analysis/inventory.json'
    inventory = read_json(inventory_path) if inventory_path.exists() else {}
    items = inventory.get('text_instances', [])
    questions = [
        {'id': 'whole_scene', 'question': '与原片同一时刻整幅比较：主体、手势、箭头、图标或背景是否被去字一起抹掉？'},
        {'id': 'boundaries', 'question': '开头、结尾、CTA及转场是否漏译，发布者水印与片尾同标是否都按身份处理？'},
        {'id': 'playback', 'question': '正常播放是否有闪烁、漂移、撕裂、动作变速或突兀补丁？静帧看不出的差异是什么？'},
        {'id': 'delivery', 'question': '全部原片×全部目标语种是否有完整正式输出和真实提交回执？局部失败是否阻塞了其他语种？'}]
    if any(i.get('action') not in {'keep', 'remove'} for i in items):
        questions.append({'id': 'lettering', 'question': '为什么用户会觉得像直接打字贴上去？原字形粗细、斜体、字号占比、描边、行距、构图和运动分别保留或适配了什么？'})
    if inventory.get('audio', {}).get('has_speech'):
        questions.append({'id': 'listening', 'question': '完整听完目标人声及首末词了吗？对白、旁白、性别、音乐音效和字幕节奏是否与实际音轨一致？'})
    candidate_path = run / 'outputs/candidate.json'
    candidate = read_json(candidate_path) if candidate_path.exists() else {}
    completion_path = run / 'outputs/completion.json'
    completion = read_json(completion_path) if completion_path.exists() else {}
    # A finalized best-available output may differ from the earlier candidate.
    # Do not present the earlier candidate's probes as a review of that output.
    selected_sha = completion.get('video_sha256') or candidate.get('sha256')
    capture_path = run / 'review/capture.json'
    capture = read_json(capture_path) if capture_path.exists() else {}
    probes = capture.get('review_probes') if capture.get('video_sha256') == selected_sha else None
    quality_path = run / 'outputs/quality.json'
    quality = read_json(quality_path) if quality_path.exists() else {}
    records = [read_json(p) for p in sorted((run / 'review/improvements').glob('*.json'))]
    policy_path = run.parent.parent / 'config/workspace.json'
    policy = read_json(policy_path) if policy_path.exists() else {}
    return {'workflow': 'agent/workflows/continuous-improvement.md', 'questions': questions,
            'candidate_sha256': candidate.get('sha256'), 'whole_scene_probes': probes,
            'formal_output_sha256': completion.get('video_sha256'),
            'recorded_cycles': records, 'quality_record': quality,
            'max_revision_rounds': policy.get('max_revision_rounds'),
            'execution_requires_existing_policy': True,
            'actions': ['Observe actual source/output and record one concrete defect',
                        'Separate observed symptom, suspected cause and why the previous review missed it',
                        'Change one causal variable within the original budget/revision bounds',
                        'Compare before/after plus an unaffected region and actual playback',
                        'Stop when acceptable or at bounds; finalize the best complete output with limitations',
                        'improvement-record -> knowledge-queue/review; verify actual use on a later task'],
            'stop_when': ['acceptable_at_normal_playback', 'retry_limit', 'budget_limit',
                          'capability_limit', 'no_evidence_backed_improvement'],
            'scope': 'Agent actions at production/review/feedback events. No unattended execution, automatic pass, paid retry or rule promotion.'}


@guarded
def record(run, relative):
    """Store an attributable repair/counterexample in the existing knowledge queue."""
    from . import bundles, workflow
    spec_path = inside(run, relative)
    spec = read_json(spec_path)
    source_sha = file_hash(workflow.source_path(run))
    require(spec.get('source_sha256') == source_sha, 'Improvement source changed')
    require(spec.get('reviewed_by') and spec.get('review_type') in
            {'same_agent', 'independent', 'user_feedback'}, 'Attribute the actual improvement review')
    for field in ('symptom', 'hypothesis', 'missed_reason', 'next_review_question',
                  'intervention', 'observation', 'next_action'):
        require(isinstance(spec.get(field), str) and spec[field].strip(), f'Improvement needs {field}')
    require(spec.get('cause_status') in {'hypothesis', 'supported'}, 'Distinguish hypothesis from supported cause')
    require(spec.get('outcome') in {'improved', 'no_improvement', 'regressed', 'inconclusive'},
            'Record the observed result, including failed repairs')
    require(isinstance(spec.get('limitations'), list) and spec['limitations'], 'Keep improvement limits explicit')
    videos = {}
    for label in ('before', 'after'):
        asset = spec[label]
        path = inside(run, asset['path'])
        require(path.is_file() and file_hash(path) == asset['sha256'], f'Improvement {label} changed')
        videos[label] = asset['sha256']
    current = read_json(run / 'outputs/candidate.json')
    require(current['sha256'] == videos['after'] and
            file_hash(inside(run, current['path'])) == videos['after'], 'Review the current actual candidate')
    require(videos['before'] != videos['after'] or spec['outcome'] == 'inconclusive',
            'Unchanged video cannot prove an improvement or regression')
    evidence = spec.get('evidence', [])
    require(evidence and {e.get('role') for e in evidence} >= {'before', 'after', 'unaffected'},
            'Preserve before/after evidence and an unaffected control')
    files = {'review.json': spec_path, 'request.json': run / 'inputs/request.json',
             'inventory.json': run / 'analysis/inventory.json'}
    seen = set()
    for item in evidence:
        role = item['role']
        require(role in {'before', 'after', 'unaffected', 'playback', 'regression'}, 'Unknown improvement evidence role')
        path = inside(run, item['path'])
        require(path.is_file() and file_hash(path) == item['sha256'] and
                path.suffix.lower() in {'.json', '.md', '.png', '.jpg', '.webp', '.wav'},
                'Improvement evidence missing, changed or unsupported')
        expected = videos['before'] if role == 'before' else videos['after']
        require(item.get('video_sha256') == expected, 'Improvement evidence belongs to another video')
        require(item['path'] not in seen, 'Use distinct evidence for the comparison and control')
        seen.add(item['path'])
        files['evidence/' + item['path']] = path
    root = run.parent.parent
    identity = object_hash({'run': run.name, 'spec': spec})
    folder = root / 'knowledge/local/feedback/improvements' / identity
    scope = {'workflow': 'video-localization', 'source_sha256': source_sha,
             'target_language': read_json(run / 'inputs/request.json')['target_language']}
    bundles.create(folder / 'bundle', 'knowledge-case', identity, files, {
        'scope': scope, 'video_sha256': videos['after'], 'review_type': spec['review_type'],
        'proof_boundary': 'Selected attributable observations, not independent acceptance or full video preservation.'})
    value = {**spec, 'id': identity, 'status': 'candidate', 'scope': scope, 'visibility': 'local',
             'company_preference': False,
             'case': (folder / 'bundle').relative_to(root).as_posix(),
             'case_manifest_sha256': file_hash(folder / 'bundle/manifest.json')}
    target = folder / 'feedback.json'
    if target.exists():
        require(read_json(target) == value, 'Immutable improvement feedback changed')
    else:
        write_json(target, value)
    pointer = {'path': target.relative_to(root).as_posix(), 'sha256': file_hash(target)}
    write_json(run / 'review/improvements' / (identity + '.json'), pointer)
    return {**pointer, 'state': 'awaiting_knowledge_review', 'automatic_promotion': False,
            'delivery_approval_changed': False}
