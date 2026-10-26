"""Preserve observations before an explicit, fail-closed run deletion."""
from __future__ import annotations

import re
import shutil
import math
from contextlib import ExitStack
from pathlib import Path

from . import bundles, learning, library, source_state
from .common import ROOT, file_hash, guarded, inside, object_hash, read_json, require, run_operation, utc_now, write_json
from .evidence import EVIDENCE_SUFFIXES

TERMINAL = {"success", "succeeded", "fail", "failed", "cancelled", "canceled"}


def files(run):
    run = Path(run).resolve()
    result = {}
    for path in sorted(run.rglob("*")):
        require(not path.is_symlink() and not getattr(path, "is_junction", lambda: False)(), "Linked run content cannot be deleted")
        require(path.resolve().is_relative_to(run), "Run content escapes its directory")
        if path.is_file():
            result[path.relative_to(run).as_posix()] = file_hash(path)
    return result


def blockers(run):
    problems = []
    for path in Path(run).rglob("*.lock"):
        problems.append("Unresolved operation lock: " + path.relative_to(run).as_posix())
    for path in (Path(run) / "jobs").glob("*.json"):
        job = read_json(path)
        if job.get("state") not in TERMINAL:
            problems.append("Unsettled model task: " + path.name)
        if job.get("billing_status") in {"unknown", "pending", "unsettled"} or job.get("billing") == "unknown":
            problems.append("Unsettled billing: " + path.name)
        actual = job.get('credits_consumed')
        settled = type(actual) in (int,float) and math.isfinite(actual) and actual>=0
        if (job.get("task_id") or 'estimated_credits' in job or job.get('batch_budget')
                or job.get('submitted_at')) and not settled:
            problems.append("Missing settled task cost: " + path.name)
    for path in (Path(run).parent.parent/'state/budgets').glob('*.json'):
        if path.name == 'index.json': continue
        for reservation in read_json(path).get('reservations',{}).values():
            if reservation.get('run') != Path(run).name: continue
            actual = reservation.get('actual_credits')
            if (type(actual) not in (int,float) or not math.isfinite(actual) or actual<0
                    or reservation.get('state') not in TERMINAL | {'response_received','response_invalid'}):
                problems.append('Unsettled request reservation: '+path.name+':'+str(reservation.get('job')))
    costs = Path(run) / "outputs/actual-costs.json"
    if costs.exists():
        data = read_json(costs)
        if data.get("unknown_jobs") or data.get("unknown_billing_items"):
            problems.append("Unsettled entries in outputs/actual-costs.json")
    repairs = Path(run).parent.parent / 'state/repair-trials' / (Path(run).name + '.json')
    if repairs.exists() and any(a.get('state') == 'running' for a in read_json(repairs).get('attempts', [])):
        problems.append('Unreconciled local repair attempt')
    return problems


def _run(root, run):
    root, run = Path(root).resolve(), Path(run).resolve()
    require(run.parent == (root / "runs").resolve() and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", run.name)),
            "Deletion target must be one named run inside this workspace")
    require((run / "run.json").is_file(), "Unknown run")
    return root, run


@guarded
def preserve(run, root=None):
    root, run = _run(root or ROOT, run)
    require(not blockers(run), "Resolve model tasks, billing and operation locks before preserving for deletion")
    learning.audit(root)
    # Publishing neutral observations first makes the preservation fingerprint stable.
    snapshot = source_state.save(run, root) if (run / "analysis/media.json").exists() else None
    record = read_json(run / "run.json")
    request = read_json(run / "inputs/request.json")
    scope = {"workflow": "video-localization", "source_sha256": record["source_sha256"],
             "target_language": request["target_language"]}
    video = None
    candidate = run / "outputs/candidate.json"
    if candidate.exists():
        data = read_json(candidate)
        require(file_hash(inside(run, data["path"])) == data["sha256"], "Candidate changed before preservation")
        video = data["sha256"]
    delivery = run / "outputs/delivery.json"
    if delivery.exists():
        data = read_json(delivery)
        require(file_hash(inside(run, data["video"])) == data["sha256"], "Delivered video changed before preservation")
        video = data["sha256"]
    package = library.export(run, root, video) if video else None
    if package:
        package = {**package, "manifest_sha256": file_hash(root / package["package"] / "manifest.json")}
    content = files(run)
    identity = object_hash(content)
    case_id = "retained-" + run.name[:60] + "-" + identity[:24]
    from .learning_evidence import select
    observations = select(run, video, history=True)
    case = learning.capture_case(case_id, "Run observations preserved before deletion; conclusions still require review.",
        scope, root, run, video, records=observations)
    candidate_record = {"id": case_id, "status": "candidate", "scope": scope,
        "hypothesis": "Preserved source observations, decisions and failure records await distillation.",
        "case": case.relative_to(root).as_posix(), "evidence": {"run": run.name, "video_sha256": video},
        "company_preference": False, "promotion": "No rule or user acceptance is inferred by deleting a run."}
    candidate_path = root / "knowledge/local/candidates" / (case_id + ".json")
    if not candidate_path.exists():
        write_json(candidate_path, candidate_record)
    inbox = learning.enqueue(candidate_record, root)
    # A no-analysis run still needs its original bytes for future analysis.
    recovery = root / "state/run-recovery" / run.name / identity
    source = inside(run, record["source"])
    require(file_hash(source) == record["source_sha256"], "Original video changed")
    bundles.create(recovery, "run-recovery", identity,
                   {record["source"]: source, "run.json": run / "run.json", "inputs/request.json": run / "inputs/request.json"},
                   {"source_sha256": record["source_sha256"], "origin_run_id": run.name})
    receipt = {"schema_version": 1, "run": run.name, "fingerprint": identity, "files": content,
        "case": candidate_record["case"], "case_manifest_sha256": file_hash(case / "manifest.json"),
        "inbox": inbox, "candidate": candidate_path.relative_to(root).as_posix(),
        "candidate_sha256": file_hash(candidate_path), "inbox_sha256": file_hash(root / inbox),
        "source_snapshot": snapshot, "package": package,
        "recovery": recovery.relative_to(root).as_posix(), "recovery_manifest_sha256": file_hash(recovery / "manifest.json"),
        "preserved_at": utc_now(), "status": "preserved"}
    write_json(root / "state/run-retention" / (run.name + ".json"), receipt)
    return {"run": run.name, "fingerprint": identity, "case": receipt["case"], "source_snapshot": snapshot,
            "package": package, "status": "preserved", "knowledge_status": "candidate_not_activated"}


def inspect(run, root=None):
    root, run = _run(root or ROOT, run)
    problems = blockers(run)
    if list((root/'state/resources').glob('*.lock')):
        problems.append('Heavy work is active; retry cleanup when idle')
    _, external_paths = _live_references(root, exclude_run=run)
    if any(path.is_relative_to(run) for path in external_paths):
        problems.append('Another run still references this run\'s files')
    learning.audit(root)
    content = files(run)
    fingerprint = object_hash(content)
    receipt_path = root / "state/run-retention" / (run.name + ".json")
    receipt = read_json(receipt_path) if receipt_path.exists() else None
    if not receipt or receipt["fingerprint"] != fingerprint:
        problems.append("Run is not preserved at its current contents; run run-preserve first")
    else:
        case = inside(root, receipt["case"])
        require(file_hash(case / "manifest.json") == receipt["case_manifest_sha256"], "Preserved knowledge case changed")
        bundles.verify(case)
        for key in ("candidate", "inbox"):
            require(file_hash(inside(root, receipt[key])) == receipt[key + "_sha256"], "Preserved learning queue changed")
        recovery = inside(root, receipt["recovery"])
        require(file_hash(recovery / "manifest.json") == receipt["recovery_manifest_sha256"], "Recovery manifest changed")
        bundles.verify(recovery)
        if receipt["source_snapshot"]:
            source_state.verify(receipt["source_snapshot"], root, read_json(run / "run.json")["source_sha256"])
        if receipt["package"]:
            package = inside(root, receipt["package"]["package"])
            require(file_hash(package / "manifest.json") == receipt["package"]["manifest_sha256"], "Preserved delivery manifest changed")
            bundles.verify(package)
    return {"run": run.name, "fingerprint": fingerprint, "decision": "blocked" if problems else "ready",
            "blockers": problems, "files": len(content), "dry_run": True}


@guarded
def delete(run, root=None, execute=False, expected=None):
    root, run = _run(root or ROOT, run)
    preview = inspect(run, root)
    if not execute:
        return preview
    require(preview["decision"] == "ready", "; ".join(preview["blockers"]))
    require(expected == preview["fingerprint"], "Deletion requires the current preview fingerprint via --expect")
    receipt_path = root / "state/run-retention" / (run.name + ".json")
    receipt = read_json(receipt_path)
    receipt.update(status="deleting", deletion_started_at=utc_now())
    write_json(receipt_path, receipt)
    # Recheck the exact absolute target immediately before recursive deletion.
    require(run.resolve().parent == (root / "runs").resolve() and object_hash(files(run)) == expected,
            "Run changed during deletion preparation")
    shutil.rmtree(run)
    receipt.update(status="deleted", deleted_at=utc_now())
    write_json(receipt_path, receipt)
    return {"run": run.name, "status": "deleted", "knowledge_case": receipt["case"],
            "preserved_source": receipt["recovery"], "dry_run": False}


@guarded
def prune(run, root=None, execute=False, expected=None):
    """Evict superseded generated pictures after the normal preservation gates.

    Current source, candidate, released preparations, all JSON observations and
    recipes remain. A pruned old audit is explicitly incomplete, never approved.
    """
    root, run = _run(root or ROOT, run)
    preview = inspect(run, root)
    require(preview['decision'] == 'ready', '; '.join(preview['blockers']))
    candidate = read_json(run/'outputs/candidate.json') if (run/'outputs/candidate.json').exists() else {}
    inventory = read_json(run/'analysis/inventory.json') if (run/'analysis/inventory.json').exists() else {}
    protected = {candidate.get('sha256')}
    for shot in inventory.get('shots',[]):
        for name in ('prepared_video','surface_typography'):
            if shot.get(name): protected.add(shot[name]['sha256'])
    targets = {}
    manifests = list((run/'inputs/visual-audit').glob('*/text-visual-audit.json'))
    manifests += list((run/'review').glob('*/visual-audit/*/text-visual-audit.json'))
    from .learning_evidence import select
    essential = set(select(run, history=True))
    for manifest in manifests:
        data = read_json(manifest)
        if data['binding']['video_sha256'] in protected: continue
        for path in manifest.parent.rglob('*'):
            if path.is_file() and path not in essential and path.suffix.lower() in {'.png','.jpg','.webp'}:
                relative = path.relative_to(run).as_posix()
                targets[relative] = {'sha256': file_hash(path), 'bytes': path.stat().st_size}
    fingerprint = object_hash({'preserved_run': preview['fingerprint'], 'pictures': targets})
    result = {'run':run.name, 'fingerprint':fingerprint, 'files':len(targets),
              'logical_bytes':sum(p['bytes'] for p in targets.values()), 'dry_run':not execute,
              'protected_video_hashes':sorted(p for p in protected if p),
              'scope':'Superseded generated comparison pictures only; current work, source, scripts, ledgers and all observation text remain.'}
    if not execute: return result
    require(expected == fingerprint, 'Pruning requires the current preview fingerprint via --expect')
    receipt = read_json(root/'state/run-retention'/f'{run.name}.json')
    # inspect verified this independent case, source snapshot and selected package.
    # The case contains explicit failures and representative historical pictures.
    out = root/'state/run-pruning'/run.name/(fingerprint+'.json')
    record = {**result, 'state':'deleting', 'pictures':targets, 'case':receipt['case'],
              'recovery':receipt['recovery'], 'package':receipt['package'], 'started_at':utc_now()}
    write_json(out,record)
    for relative, asset in targets.items():
        path = inside(run,relative)
        require(path.resolve().is_relative_to(run) and not path.is_symlink()
                and file_hash(path) == asset['sha256'], 'Prune target changed')
        path.unlink()
    record.update(state='completed', completed_at=utc_now())
    write_json(out,record)
    return {**result, 'receipt':out.relative_to(root).as_posix(), 'state':'completed'}


def _live_references(root, exclude_run=None):
    """Conservative closure of active manifests; historical versions are not roots."""
    hashes, paths, seen, values = set(), set(), set(), set()
    def visit(value, run, bound=False):
        if isinstance(value, dict):
            for key,item in value.items():
                visit(item, run, key in {'path','record','source','keyframe','video','audio','file','asset'})
        elif isinstance(value, list):
            for item in value: visit(item, run, bound)
        elif isinstance(value, str):
            if re.fullmatch(r'[a-f0-9]{64}', value): hashes.add(value)
            if '\n' not in value and len(value)<512 and value.lower().endswith(
                    ('.json','.mp4','.mkv','.mov','.webm','.wav','.png','.jpg','.webp')):
                key=(run,value,bound)
                if key in values: return
                values.add(key)
                candidate=Path(value)
                # Local images/audio in another run cannot refer to the deletion
                # target. Follow JSON provenance and explicit cross-run paths;
                # avoid resolving every comparison tile on every cleanup pass.
                cross_run=candidate.is_absolute() or '..' in candidate.parts
                if exclude_run is not None and not bound and not cross_run and candidate.suffix.lower()!='.json':
                    return
                if exclude_run is None and candidate.suffix.lower() not in ('.json','.mp4','.mkv','.mov','.webm'):
                    return
                path = (run/value).resolve()
                if path.is_relative_to(root) and path.is_file():
                    paths.add(path)
                    if path.suffix == '.json': load(path,run)
    def load(path, run):
        if path in seen: return
        seen.add(path)
        if path.is_file(): visit(read_json(path), run)
    for run in (root/'runs').iterdir():
        if not run.is_dir() or run.name.startswith('.'): continue
        if run == exclude_run: continue
        for relative in ('run.json','plan.json','analysis/inventory.json',
                         'outputs/candidate.json','outputs/delivery.json'):
            load(run/relative,run)
        for path in (run/'jobs').glob('*.json'): load(path,run)
    return hashes, paths


@guarded
def prune_versions(run, relative, root=None, execute=False, expected=None):
    """Explicitly retire obsolete videos, retaining independent bounded error evidence."""
    root, run = _run(root or ROOT,run)
    others = sorted(p for p in (root/'runs').iterdir() if p.is_dir() and not p.name.startswith('.'))
    with ExitStack() as stack:
        for other in others: stack.enter_context(run_operation(other))
        require(not list((root/'state/resources').glob('*.lock')), 'Heavy work is active; retry cleanup when idle')
        preservation = inspect(run,root)
        require(preservation['decision']=='ready', '; '.join(preservation['blockers']))
        spec_path = inside(run,relative)
        spec = read_json(spec_path)
        require(isinstance(spec.get('versions'),list) and spec['versions'], 'Explicit version selection required')
        hashes, paths = _live_references(root)
        sources = {'selection.json':spec_path}
        selected, evidence_hashes = [], {}
        for version in spec['versions']:
            require(version.get('decision') in ('failed','superseded') and version.get('reason')
                    and version.get('evidence_scope'), 'Explain version decision and retained evidence scope')
            path = inside(run,version['path'])
            require(path.is_relative_to(run/'outputs') and path.suffix.lower() in ('.mp4','.mkv','.mov','.webm'),
                    'Version pruning only removes explicitly selected output videos')
            require(path.is_file() and file_hash(path)==version['sha256'], 'Selected version missing or changed')
            require(path not in paths and version['sha256'] not in hashes, 'Selected version is still referenced')
            require(version.get('evidence') and version.get('records'), 'Failure evidence and repair/decision records required')
            require(any(Path(p).suffix.lower() in {'.png','.jpg','.jpeg','.webp','.wav','.mp4','.mkv'}
                        for p in version['evidence']), 'Actual visual/audio failure evidence required')
            for name in version['evidence'] + version['records']:
                evidence = inside(run,name)
                require(evidence.is_file() and evidence != path, 'Required independent evidence missing')
                require(evidence.suffix.lower() in EVIDENCE_SUFFIXES | {'.py','.mkv','.mp4'},
                        'Unsupported retained evidence type')
                sources['evidence/'+name] = evidence
                evidence_hashes[name] = file_hash(evidence)
            selected.append({'path':version['path'],'sha256':version['sha256'],'bytes':path.stat().st_size})
        require(len({v['path'] for v in selected})==len(selected), 'Duplicate selected version')
        require(not any(inside(run,v['path']) in sources.values() for v in selected),
                'A selected deletion is another version\'s evidence')
        fingerprint = object_hash({'preserved':preservation['fingerprint'],'selection':spec,
                                   'videos':selected,'evidence':evidence_hashes})
        preview = {'run':run.name,'fingerprint':fingerprint,'videos':selected,
                   'logical_bytes':sum(v['bytes'] for v in selected),'dry_run':True,
                   'retained_bytes':sum(p.stat().st_size for p in sources.values()),
                   'scope':'Retained evidence is a bounded error reference, not full-video recovery or quality approval.'}
        if not execute: return preview
        require(expected==fingerprint,'Version pruning requires the current preview fingerprint via --expect')
        directory = root/'knowledge/local/retired-versions'/run.name/fingerprint
        bundles.create(directory,'retired-versions',fingerprint,sources,
                       {'origin_run_id':run.name,'versions':spec['versions'],'automatic_pass':False})
        bundles.verify(directory)
        receipt_path = root/'state/version-pruning'/run.name/(fingerprint+'.json')
        receipt = {**preview,'state':'deleting','evidence_bundle':directory.relative_to(root).as_posix(),
                   'manifest_sha256':file_hash(directory/'manifest.json'),'started_at':utc_now()}
        write_json(receipt_path,receipt)
        require(others==sorted(p for p in (root/'runs').iterdir() if p.is_dir() and not p.name.startswith('.')),
                'Workspace run set changed during cleanup')
        current_hashes,current_paths = _live_references(root)
        for asset in selected:
            path=inside(run,asset['path'])
            require(path.is_relative_to(run/'outputs') and not path.is_symlink()
                    and file_hash(path)==asset['sha256'] and path not in current_paths
                    and asset['sha256'] not in current_hashes, 'Version changed or became referenced before deletion')
        for asset in selected: inside(run,asset['path']).unlink()
        receipt.update(state='pruned',dry_run=False,completed_at=utc_now())
        write_json(receipt_path,receipt)
        return receipt
