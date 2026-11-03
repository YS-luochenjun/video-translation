"""New-request contract for natural text repair, never a pixel-quality classifier.

Internal alpha/selection mattes remain valid. Visible cover blocks do not.
Legacy records stay readable; new production requests opt in to structured review at init.
"""
from .common import WorkflowError, file_hash, inside, read_json, require, require_number

METHODS = ('natural_rebuild', 'same_source_donor', 'imagegen_repair', 'wan_repair',
           'already_clean', 'feathered_blur')


def contract_version(run):
    from pathlib import Path
    p = Path(run) / 'inputs/request.json'
    return read_json(p).get('text_restoration_contract_version', 0) if p.is_file() else 0


def required(run):
    return contract_version(run) >= 1


def items(inventory):
    return [i for i in inventory.get('text_instances', []) if i.get('action') != 'preserve']


def _evidence(run, assets):
    if not isinstance(assets, list) or not assets:
        return False
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get('path'), str):
            return False
        p = inside(run, asset['path'])
        if not p.is_file() or file_hash(p) != asset.get('sha256'):
            return False
    return True


def forbid_covers(run, instances):
    if run is None:
        return
    from pathlib import Path
    p = Path(run) / 'inputs/request.json'
    request = read_json(p) if p.is_file() else {}
    if (request.get('fixture_contract') == 'legacy_solid_overlay_regression_not_production'
            and request.get('text_restoration_contract_version') == 0):
        return
    for item in instances:
        if item.get('action') == 'preserve':
            continue
        require(item.get('action') != 'solid_overlay',
                'Solid cover overlays are forbidden for new requests; repair the background and add transparent lettering')
        require(not item.get('display', {}).get('pill'),
                'Added solid text backings/pills are forbidden; retain the actual source container instead')


def validate(run, inventory):
    if not required(run):
        return
    forbid_covers(run, inventory.get('text_instances', []))
    for item in items(inventory):
        repair = item.get('restoration', {})
        require(isinstance(repair, dict) and repair.get('method') in METHODS,
                'Every edited text instance needs a natural restoration method; no solid covers or hard blur blocks')
        require(isinstance(repair.get('reason'), str) and repair['reason'].strip()
                and _evidence(run, repair.get('evidence')),
                'Text restoration needs actual source/candidate evidence with hashes')
        if repair['method'] != 'feathered_blur':
            continue
        fallback = repair.get('fallback', {})
        require(isinstance(fallback, dict) and fallback.get('difficulty') and fallback.get('wan_assessment'),
                'Exceptional blur needs actual difficulty and a Wan applicability assessment')
        trials = fallback.get('attempts')
        require(isinstance(trials, list) and trials,
                'Blur is an exceptional fallback after evidenced natural repair attempts, not a default route')
        for trial in trials:
            require(isinstance(trial, dict) and trial.get('method') in METHODS[:-1]
                    and trial.get('outcome') in ('failed', 'unsafe') and trial.get('observation')
                    and _evidence(run, trial.get('evidence')),
                    'Blur fallback requires actual failed/unsafe natural repair evidence; budget/time alone is insufficient')
        feather = require_number(fallback.get('feather_px'), 'blur feather', minimum=0)
        opacity = require_number(fallback.get('opacity'), 'blur opacity', minimum=0, maximum=1)
        require(feather > 0 and 0 < opacity < 1 and fallback.get('source_motion_preserved') is True,
                'Exceptional blur must be feathered, partially transparent and preserve source motion; no solid or hard-edged patch')


def natural_removal_prompt():
    # Appended after custom shot prompts so their shorthand cannot drop this constraint.
    return ("Restore the actual background behind every removed glyph, outline and shadow. "
            "Do not hide lettering with opaque/translucent panels, blur bands, smears or rectangular patches. "
            "A feathered edge or lower opacity is not background reconstruction. "
            "The background-only result must contain no source lettering before any translated text is added. "
            "Preserve existing containers, scene texture, lighting and original continuous motion.")


def review_template(inventory):
    return [{'id': i['id'], 'decision': 'pending', 'visible_coverup': None,
             'source_text_removed': None, 'background_continuity': None, 'motion_preserved': None,
             'observation': '', 'evidence': [], 'clean_base_evidence': []} for i in items(inventory)]


def review_failures(run, inventory, review, candidate):
    if not required(run) or not items(inventory):
        return []
    failures = []
    try:
        validate(run, inventory)
    except (WorkflowError, ValueError, OSError, KeyError, TypeError) as exc:
        return ['text_restoration_contract_invalid:' + str(exc)]
    expected = {i['id'] for i in items(inventory)}
    rows = review.get('text_restoration_review', [])
    if (not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows)
            or len(rows) != len(expected) or {r.get('id') for r in rows} != expected):
        return ['text_restoration_review_coverage_missing']
    capture_path = run / 'review/capture.json'
    capture = read_json(capture_path) if capture_path.is_file() else {}
    files = capture.get('files', {}) if capture.get('video_sha256') == candidate['sha256'] else {}
    plan_path = run / 'plan.json'
    plan = read_json(plan_path) if plan_path.exists() else {}
    needs_base = plan.get('restoration_probe_contract') == 1
    coverage = {}
    if needs_base:
        try:
            from .restoration_probes import review_coverage
            require(plan['id'] == candidate['plan_id'] and capture.get('video_sha256') == candidate['sha256'],
                    'Restoration capture/plan changed')
            coverage = review_coverage(run, candidate, capture)
        except (WorkflowError, ValueError, OSError, KeyError, TypeError) as exc:
            failures.append('clean_base_review_missing_or_changed:' + str(exc))
    for row in rows:
        if needs_base:
            assets = row.get('clean_base_evidence', [])
            expected = coverage.get(row['id'], set())
            actual = {(a.get('path'), a.get('sha256')) for a in assets if isinstance(a, dict)} if isinstance(assets, list) else set()
            if not expected or actual != expected:
                failures.append('clean_base_instance_unreviewed:' + row['id'])
        # Transparency is a compositing parameter, not proof that lettering or a patch is gone.
        if contract_version(run) >= 2 and any(row.get(k) is not True for k in
                ('source_text_removed', 'background_continuity', 'motion_preserved')):
            failures.append('background_reconstruction_or_unreviewed:' + row['id'])
        if (row.get('decision') != 'pass' or row.get('visible_coverup') is not False
                or not row.get('observation') or not _evidence(run, row.get('evidence'))
                or any(files.get(a['path']) != a['sha256'] for a in row.get('evidence', []))):
            failures.append('visible_coverup_or_unreviewed:' + row['id'])
    return failures
