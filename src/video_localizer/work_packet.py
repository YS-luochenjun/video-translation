"""Compact stage guidance from existing state and knowledge; no invented reviews."""
from .common import WorkflowError, file_hash, inside, read_json, require
from .knowledge import context_for, retrieve, source_references, related_source_references
from .knowledge_advisories import retrieve as advisory_retrieve
from .knowledge_usage import followup as knowledge_followup
from .improvement import agenda as improvement_agenda
from . import resources, workflow

STAGES = {
    'source': {'read': ['agent/contracts/workflow.md', 'agent/workflows/ocr.md', 'agent/contracts/audio.md', 'docs/source-typography.md'],
               'ai': ['Codex reads every source text instance from actual images', 'Use specialist audio evidence; resolve inventory coverage'],
               'commands': ['analyze', 'context', 'codex-packet --stage recognize', 'codex-result', 'style-capture', 'style-reuse', 'font-bind']},
    'translation': {'read': ['agent/contracts/captions.md', 'agent/contracts/audio.md'],
                    'ai': ['Finalize translation and speech copy', 'Select voice/style and source speech windows'],
                    'commands': ['tts-packet', 'audio-mix', 'asr', 'captions']},
    'neutral': {'read': ['agent/workflows/visual-review.md', 'agent/contracts/quality.md'],
                'ai': ['Codex directly edits images using project knowledge and host image tools; use Wan 2.7 for video-model work', 'Inspect native continuous frames and animation boundaries'],
                'commands': ['codex-packet --stage image', 'codex-result', 'visual-evidence --stage neutral', 'visual-notes', 'visual-release-neutral']},
    'render': {'read': ['agent/workflows/batch-production.md', 'agent/contracts/captions.md'],
               'ai': ['Review layout and actual mixed-audio alignment', 'Approve the representative language before expansion'],
               'commands': ['plan', 'packet', 'style-layer', 'production', 'batch-approve', 'batch-run']},
    'review': {'read': ['agent/workflows/visual-review.md', 'agent/contracts/quality.md', 'agent/contracts/captions.md'],
               'ai': ['Judge actual encoded picture, speech, music, sync and translation', 'Record observed failures and bounded revisions'],
               'commands': ['visual-evidence', 'visual-pages', 'visual-notes', 'capture', 'quality']},
    'delivery': {'read': ['agent/contracts/knowledge.md', '.agents/skills/knowledge-curation/SKILL.md'],
                 'ai': ['Explain causal lessons, limits and counterexamples', 'Review candidate generalization; never auto-promote'],
                 'commands': ['deliver', 'delivery-index', 'reflect', 'close-failure', 'knowledge-use', 'knowledge-queue', 'knowledge-review']},
}


def _next_action(run, state, jobs):
    actions = {
        'created': ('analyze', ['analyze'], 'Inspect the source and establish instance coverage.'),
        'awaiting_agent_inventory': ('complete_inventory', ['context', 'codex-packet'], 'Codex inspects images directly and resolves missing inventory observations.'),
        'awaiting_source_styles': ('capture_source_styles', ['style-capture', 'style-reuse', 'font-bind'],
                                  'Inspect original frames, freeze source typography and choose real target fonts/assets before erasure.'),
        'needs_neutral_review': ('review_neutral', ['visual-evidence', 'visual-notes', 'visual-release-neutral'],
                                'Review the actual neutral master, then release it before planning.'),
        'needs_planning': ('plan', ['plan'], 'Bind inspected inputs to a formal plan; diagnostic previews remain unapproved.'),
        'needs_replanning': ('replan', ['plan'], 'Rebuild the plan from changed inputs and establish new review bindings.'),
        'planned': ('execute_plan', ['packet', 'production'], 'Inspect required packets and reuse completed assets before execution.'),
        'needs_review': ('review_actual_candidate', ['visual-pages', 'visual-notes', 'capture', 'quality'],
                         'Complete actual candidate observations, audio and caption sync; render again only after an observed defect requires changed inputs.'),
        'needs_revision': ('resolve_quality_failures', ['visual-pages', 'quality'],
                           'Read current failures first. Missing evidence requires review; observed defects require a bounded repair.'),
        'ready_to_deliver': ('deliver', ['deliver'], 'Current quality record passes. Deliver revalidates the gates without generating another preview.'),
        'delivered': ('delivery_complete', ['delivery-index'], 'Formal delivery exists; use the package and retain unresolved billing records.'),
        'needs_reconciliation': ('reconcile_existing', [], 'Recover the recorded provider task/receipt before repeating an uncertain paid submission.'),
        'awaiting_model': ('poll_existing', [], 'Poll recorded task IDs; continue independent local review while waiting.'),
    }
    kind, commands, reason = actions.get(state, ('inspect_state', ['status'], 'Inspect the recorded state before execution.'))
    pending = [job for job in jobs if job['state'] in ('submitted', 'waiting', 'queuing', 'generating') and job.get('task_id')]
    invocations = [f'bin/va.ps1 poll {run.name} {job["id"]} --wait 0' for job in pending] if kind == 'poll_existing' else []
    return {'kind': kind, 'command_entries': commands, 'invocations': invocations, 'reason': reason,
            'new_paid_submission': False, 'scope': 'Navigation only. Execution and any paid submission retain existing gates.'}


def build(run, stage=None):
    root = run.parent.parent
    from .ledger import tracking_packet
    ledger_tracking = tracking_packet(run)
    source_sha = file_hash(workflow.source_path(run))
    inventory_path = run / 'analysis/inventory.json'
    inventory = read_json(inventory_path) if inventory_path.exists() else {'source_sha256': source_sha}
    request = read_json(run / 'inputs/request.json')
    from .library import find as find_packages
    reusable_packages = find_packages(source_sha, root=root)
    from .maintenance import status as maintenance_status
    maintenance = maintenance_status(run)
    completion_path = run / 'outputs/completion.json'
    if (completion_path.exists() and (run / 'outputs/delivery.json').exists()
            and read_json(run / 'outputs/delivery.json').get('scope') == 'best_available'):
        completion = read_json(completion_path)
        require(file_hash(run / 'outputs/final.mp4') == completion['video_sha256'], 'Finalized output changed')
        selected = {}
        if completion.get('knowledge_selection'):
            asset = completion['knowledge_selection']
            path = inside(run, asset['path'])
            require(file_hash(path) == asset['sha256'], 'Finalization knowledge selection changed')
            selected = read_json(path)
        return {'run': run.name, 'ledger_tracking': ledger_tracking, 'state_hint': 'delivered_with_issues', 'completion': completion,
                'improvement_loop': improvement_agenda(run),
                'knowledge': selected.get('knowledge', []), 'source_references': selected.get('source_references', []),
                'knowledge_advisories': selected.get('knowledge_advisories', []),
                'routing_assessment': selected.get('routing_assessment'),
                'knowledge_record_state': 'finalization_selection_only' if selected else 'legacy_not_recorded',
                'reusable_packages': reusable_packages, 'maintenance': maintenance, 'automatic_pass': False,
                'next_action': 'Show the actual final video and disclosed limitations; do not repeat paid work.'}
    if (run / 'plan.json').exists() and read_json(run / 'plan.json').get('mode') == 'fast':
        from . import budgets, fast_delivery
        plan = fast_delivery.validate_plan(run, read_json(run / 'plan.json'))
        budget = budgets.status(budgets.bind(run)['id'], root)
        return {'run': run.name, 'ledger_tracking': ledger_tracking, 'mode': 'fast', 'plan_id': plan['id'],
                'improvement_loop': improvement_agenda(run),
                'knowledge': plan.get('knowledge', []), 'source_references': plan.get('source_references', []),
                'knowledge_advisories': plan.get('knowledge_advisories', []),
                'knowledge_context': plan.get('knowledge_context'),
                'related_source_references': related_source_references(plan.get('knowledge_context') or context_for(request, inventory, root), root=root),
                'routing_assessment': plan.get('routing_assessment'),
                'knowledge_record_state': 'frozen' if plan.get('knowledge_snapshot_version') == 1 else 'legacy_missing_re_register',
                'knowledge_followup': knowledge_followup(run, root),
                'reusable_packages': reusable_packages, 'maintenance': maintenance,
                'model_control': 'agent/contracts/model-routing.md',
                'output_policy': 'agent/workflows/always-output.md',
                'workflow': 'agent/workflows/fast-delivery.md',
                'review': 'review/fast-review.json', 'checks': fast_delivery.policy(root)['review_checks'],
                'budget': {k: budget[k] for k in ('id', 'credit_limit', 'reserved_or_billed_credits', 'remaining_credits', 'unknown_billing_jobs')},
                'next_action': 'Complete actual basic review, then quality/deliver; reuse unchanged evidence'}
    from .cli import status
    current = status(run)
    auto = {'created': 'source', 'awaiting_agent_inventory': 'source', 'awaiting_source_styles': 'source', 'needs_replanning': 'render',
            'needs_planning': 'render', 'needs_neutral_review': 'neutral',
            'awaiting_model': 'render', 'needs_reconciliation': 'render',
            'planned': 'render', 'needs_review': 'review', 'needs_revision': 'review',
            'ready_to_deliver': 'delivery', 'delivered': 'delivery'}.get(current['state'], 'translation')
    stage = stage or auto
    require(stage in STAGES, 'Unknown production stage')
    jobs = [{'id': j['id'], 'state': j['state'], 'task_id': j.get('task_id'),
             'packet': j.get('packet'), 'result': j.get('result'), 'credits_consumed': j.get('credits_consumed'),
             'estimated_credits': j.get('estimated_credits'), 'error': j.get('error')}
            for j in current['jobs']]
    blockers = []
    blockers.extend((current.get('source_styles') or {}).get('blockers', []))
    blockers.extend(f"Shot {item['shot']}: {item['reason']}" for item in current.get('preparation_blockers', []))
    if current['state'] == 'needs_replanning':
        blockers.append('Plan inputs changed: regenerate plan; do not reuse old approvals')
    if any(j['state'] in ('preparing', 'submitting', 'ambiguous') for j in jobs):
        blockers.append('Reconcile recorded provider tasks before any resubmission')
    billing_pending = [j for j in jobs if j['state'] in ('failed', 'ambiguous', 'response_invalid')
                       and j['credits_consumed'] is None and j.get('estimated_credits')]
    if billing_pending:
        blockers.append('Provider charges remain unknown: reconcile before repeating these calls; local review can continue')
    diagnostics = []
    draft_paths = set((run / 'outputs').glob('*/diagnostic-candidate.json')) | set((run / 'outputs').glob('*/candidate-record.json'))
    for path in sorted(draft_paths):
        draft = read_json(path)
        try:
            movie = inside(run, draft['path'])
            intact = movie.is_file() and file_hash(movie) == draft.get('sha256')
        except (WorkflowError, KeyError, OSError, ValueError):
            intact = False
        diagnostics.append({'record': path.relative_to(run).as_posix(), 'path': draft.get('path'),
                            'sha256': draft.get('sha256'), 'integrity_ok': intact,
                            'status': 'diagnostic_only_not_approved'})
    candidate_path = run / 'outputs/candidate.json'
    candidate = read_json(candidate_path) if candidate_path.exists() else None
    if candidate:
        require(file_hash(inside(run, candidate['path'])) == candidate['sha256'], 'Work packet candidate changed')
        from .quality_holds import require_clear
        require_clear(source_sha, candidate['sha256'], root)
    coverage = inventory.get('coverage', {})
    pending = [key for key in ('visual', 'speech', 'timeline') if coverage.get(key, {}).get('status') != 'reviewed']
    from .batches import binding
    pointer = binding(run)
    batch = read_json(pointer) if pointer else None
    if batch and run.name != batch['pilot'] and not batch.get('pilot_release'):
        blockers.append('Representative language has not been released: work on the pilot first')
    context = context_for(request, inventory, root)
    delivery_path = run / 'outputs/delivery.json'
    delivery = read_json(delivery_path) if delivery_path.exists() else None
    progress = []
    for path in sorted((root/'state/review-progress'/run.name).glob('*.json')):
        progress.append({'manifest_prefix':path.stem, 'instances':read_json(path)})
    trial_path = root/'state/repair-trials'/f'{run.name}.json'
    trials = read_json(trial_path) if trial_path.exists() else None
    observations = []
    paths = set((run/'review').glob('*notes.json')) | set((run/'review').glob('*issue*.json'))
    for path in sorted(paths):
        packet = read_json(path)
        issues = [{'instance':n.get('instance_id'), 'issue':n['issue']} for n in packet.get('instances',[]) if n.get('issue')]
        if issues: observations.append({'path':path.relative_to(run).as_posix(),'issues':issues})
    from .model_routing import policy
    return {'run': run.name, 'ledger_tracking': ledger_tracking, 'stage': stage, 'state_hint': current['state'], 'model_routing': policy(root),
            'improvement_loop': improvement_agenda(run),
            'reusable_packages': reusable_packages, 'maintenance': maintenance,
            'output_policy': 'agent/workflows/always-output.md',
            'reuse_action': 'Prefer verified outputs packages before recreating assets. References and held results are not approved masters.',
            'next_action': _next_action(run, current['state'], jobs),
            'completion': {'status': 'delivered' if current['state'] == 'delivered' else 'internal_work_remaining',
                           'user_acceptance_claimed': False,
                           'scope': 'Incomplete production/review is work for the Agent; user acceptance requires separate attributed feedback.'},
            'source_sha256': source_sha, 'candidate': candidate, 'inventory': 'analysis/inventory.json',
            'source_style_preservation': current.get('source_styles'),
            'diagnostic_candidates': diagnostics, 'billing_pending': billing_pending,
            'pending_source_coverage': pending, 'blockers': blockers, 'jobs': jobs, 'delivery_record': delivery,
            'batch': None if not batch else {'id': batch['id'], 'pilot': batch['pilot'],
                                            'release_recorded': bool(batch.get('pilot_release'))},
            'knowledge': retrieve(context, root=root), 'source_references': source_references(context, root=root),
            'knowledge_context': context, 'routing_assessment': inventory.get('routing_assessment'),
            'related_source_references': related_source_references(context, root=root),
            'knowledge_advisories': advisory_retrieve(context, root), 'knowledge_followup': knowledge_followup(run, root),
            'guidance': STAGES[stage], 'resources': resources.status(root),
            'review_cursor': progress, 'repair_trials': trials, 'recorded_issues': observations,
            'preproduction_failures': [read_json(p) for p in sorted((run/'review/failures').glob('*/closure.json'))],
            'quality_failures': (current.get('quality') or {}).get('failures',[]),
            'resume_warning': 'Presented images are not reviewed. Verify the manifest hash, actual observations and pending checks before resuming.',
            'automatic_pass': False,
            'scope': 'Read-only navigation, not authorization or acceptance. Execution revalidates all gates. '
                     'Commands are entry names; inspect --help for required arguments. Read selected knowledge bodies.'}
