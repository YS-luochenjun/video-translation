"""Install public project knowledge as a fresh Git checkout would contain it."""
import shutil


def observe_visual_fixture(run, stage='final', shot=None):
    """Test-only synthetic annotations, never exposed by the production CLI."""
    from video_localizer import visual_audit
    from video_localizer.common import read_json, write_json
    result = visual_audit.generate(run, stage, shot)
    manifest = run / result['manifest']
    for template in sorted((manifest.parent / 'templates').glob('*.json')):
        record = read_json(template)
        identity = record['instance_id']
        row = next(r for r in read_json(manifest)['instances'] if r['id'] == identity)
        record.update(reviewer='synthetic contract fixture', review_type='same_agent', reviewed_at='2026-10-21T00:00:00Z',
                      reviewed_pages=[p['id'] for p in row['pages']],
                      source_appearance={k: f'Synthetic {identity} expected appearance for {k}' for k in record['source_appearance']},
                      target_requirements=f'Synthetic {identity} target appearance contract',
                      route_limitations='Synthetic nonseparable overlay fixture; source/final comparison only.',
                      playback_observation=f'Synthetic fixture {identity} known static signal; no real-video quality claim.')
        for key, check in record['checks'].items():
            check.update(status='pass', observation=f'Synthetic fixture {identity}: expected {key} at frames {row["required_frames"]}',
                         evidence_pages=record['reviewed_pages'])
        path = manifest.parent / 'test-observation.json'
        write_json(path, record)
        visual_audit.review(run, result['manifest'], path.relative_to(run).as_posix())
    if stage == 'neutral':
        visual_audit.release_neutral(run, shot)
    return result


def isolate_mock_provider(test):
    """Old provider/receipt unit tests use fake HTTP; spending authority has its own integration tests."""
    from unittest.mock import patch
    for target in ('video_localizer.budgets.reserve', 'video_localizer.budgets.authorize_request'):
        mocked = patch(target, return_value=None)
        mocked.start()
        test.addCleanup(mocked.stop)
    # These receipt tests use fake media outside runs/; retain their legacy cap.
    # Duration measurement, ledger inheritance and dispatch limits are tested separately.
    allowance = patch('video_localizer.budgets.run_allowance', return_value={'credit_limit': 60})
    allowance.start()
    test.addCleanup(allowance.stop)


def copy_project_knowledge(project, destination):
    # Integration workspaces copy workspace.json, including its policy selector.
    # Carry the matching config instead of silently falling back on a missing policy.
    for name in ('budget-policy.json', 'content-features.json'):
        source = project / 'config' / name
        if source.exists():
            (destination / 'config').mkdir(exist_ok=True)
            shutil.copyfile(source, destination / 'config' / name)
    target = destination / "knowledge"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(project / "knowledge/index.json", target / "index.json")
    for name in ("rules", "cases", "examples", "history"):
        if (project / "knowledge" / name).is_dir():
            shutil.copytree(project / "knowledge" / name, target / name, dirs_exist_ok=True)
    # Reviewed retrieval metadata is an explicit permanent dependency, too.
    from video_localizer.common import read_json
    for entry in read_json(project / 'knowledge/index.json')['entries']:
        review = entry.get('selection_review')
        if review and entry.get('status') == 'active':
            path = destination / review['path']
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(project / review['path'], path)
