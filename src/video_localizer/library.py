"""Local delivery catalog. Packages survive loss of runs; they are not knowledge."""
from __future__ import annotations

import re
from pathlib import Path

from . import bundles
from .common import ROOT, file_hash, inside, lock, read_json, require, utc_now, write_json


def source_folder(root, source_sha256):
    """Use an explicitly registered demand name; hashes remain source identity."""
    path = Path(root) / 'state/delivery-folders.json'
    names = read_json(path).get('sources', {}) if path.exists() else {}
    for name in names.values():
        require(isinstance(name, str) and name not in ('', '.', '..', 'reports')
                and not re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
                and name == name.strip().rstrip('.'), 'Invalid delivery demand folder name')
    require(len({name.casefold() for name in names.values()}) == len(names),
            'Different sources cannot share a delivery demand folder')
    return names.get(source_sha256, source_sha256[:16])


def _bound_assets(value):
    if isinstance(value, dict):
        for key, digest_key in (("path", "sha256"), ("record", "record_sha256")):
            if isinstance(value.get(key), str) and re.fullmatch(r"[a-f0-9]{64}", str(value.get(digest_key, ""))):
                yield value[key], value[digest_key]
        for child in value.values():
            yield from _bound_assets(child)
    elif isinstance(value, list):
        for child in value:
            yield from _bound_assets(child)


def _asset_closure(run, roots):
    """Follow preparation's bound inputs; preserve their exact run-relative paths."""
    # Preparation verifies its direct inputs. A copied ancestor JSON is a frozen
    # provenance snapshot; its old output paths are not executable dependencies.
    sources, expanded = {}, set()
    pending = [(path, sha, True) for path, sha in roots]
    while pending:
        path, expected, expand = pending.pop()
        path = Path(path)
        require(path.resolve().is_relative_to(run.resolve()), "Reusable dependency escapes its run")
        require(path.is_file(), f"Reusable dependency missing: {path.relative_to(run).as_posix()}")
        digest = file_hash(path)
        require(not expected or digest == expected, f"Reusable dependency changed: {path.name}")
        relative = path.relative_to(run).as_posix()
        sources[relative] = path
        if expand and relative not in expanded and path.suffix.lower() == ".json":
            expanded.add(relative)
            for asset, sha in _bound_assets(read_json(path)):
                pending.append((inside(run, asset), sha, False))
    return sources


def _collect_reusable(run, root, video_sha256, language, candidate_path, reuse_manifests, sources, roots, reusable):
    """Validate and freeze the full dependency closure only for reusable packages."""
    record = read_json(run / 'run.json')
    candidate = read_json(candidate_path) if candidate_path.exists() else {}
    if candidate.get('sha256') == video_sha256:
        from .typography import verify_receipt
        for asset in candidate.get('typography_assets', []):
            verify_receipt(run, asset)
            roots.append((inside(run, asset['path']), asset['sha256']))
    inventory = read_json(run / 'analysis/inventory.json') if (run / 'analysis/inventory.json').exists() else {}
    if inventory.get('source_style_snapshot'):
        asset = inventory['source_style_snapshot']
        roots.append((inside(run, asset['path']), asset['sha256']))
        for item in inventory.get('text_instances', []):
            asset = item.get('display', {}).get('font_asset')
            if asset:
                roots.append((inside(run, asset['path']), asset['sha256']))
    for shot in inventory.get('shots', []):
        for key in ('prepared_video', 'surface_typography', 'codex_image_result'):
            if shot.get(key):
                roots.extend((inside(run, path), sha) for path, sha in _bound_assets(shot[key]))
                reusable.append({'kind': key, 'asset': shot[key], 'target_language': None if key == 'prepared_video' else language})
    if inventory.get('codex_source_result'):
        roots.extend((inside(run, path), sha) for path, sha in _bound_assets(inventory['codex_source_result']))
    plan = read_json(run / 'plan.json') if (run / 'plan.json').exists() else {}
    for asset in (plan.get('source_style_contract') or {}).get('assets', []):
        roots.append((inside(run, asset['path']), asset['sha256']))
    for asset in (plan.get('typography_contract') or {}).get('fonts', []):
        roots.append((inside(run, asset['path']), asset['sha256']))
    if plan.get('knowledge_snapshot_version') == 1 and candidate.get('sha256') == video_sha256:
        from .fast_delivery import validate_plan
        validate_plan(run, plan)
        for path in (run / 'plans' / plan['id']).rglob('*'):
            if path.is_file():
                sources[path.relative_to(run).as_posix()] = path
    for asset in plan.get('audio_assets', []) + plan.get('caption_assets', []):
        roots.extend((inside(run, path), sha) for path, sha in _bound_assets(asset))
    manifests = list(reuse_manifests)
    if (run / 'outputs/reuse-assets.json').exists():
        manifests.append(run / 'outputs/reuse-assets.json')
    for path in manifests:
        data = read_json(Path(path))
        require(data.get('source_sha256') == record['source_sha256'], 'Reuse manifest belongs to another source')
        for asset in data.get('assets', []):
            asset_path = inside(root, asset['path']) if asset['path'].startswith('runs/') else inside(run, asset['path'])
            require(asset_path.is_relative_to(run), "Select the asset's originating run for archive")
            roots.append((asset_path, asset['sha256']))
            reusable.append({'kind': asset.get('role', asset.get('usage', 'reuse asset')),
                             'path': asset_path.relative_to(run).as_posix(), 'sha256': asset['sha256'],
                             'target_language': asset.get('target_language', None if asset.get('role', '').startswith('source-') else language)})
    for asset in plan.get('audio_assets', []):
        if asset.get('path'):
            recipe = inside(run, asset['path']).parent / 'provenance.json'
            if recipe.is_file():
                roots.append((recipe, file_hash(recipe)))
    sources.update(_asset_closure(run, roots))
    for path in (run / 'outputs').glob('*/provenance.json'):
        sources[path.relative_to(run).as_posix()] = path


def _reusable_mode(request, policy):
    """Explicit contract mode takes precedence over legacy opt-in and defaults."""
    if 'delivery_package_mode' in request:
        mode = request['delivery_package_mode']
        require(isinstance(mode, str) and mode in ('lean', 'reusable'),
                'request.delivery_package_mode must be lean or reusable')
        return mode == 'reusable'
    return (request.get('keep_reusable_assets') is True or
            policy.get('package_mode', 'lean' if policy.get('enabled') else 'reusable') == 'reusable')


def _reject_expired_replay(root, video_sha256, delivery_identity, managed):
    from . import delivery_layout
    path = delivery_layout.catalog(root)
    legacy = root / 'outputs/index.json'
    if not path.exists() and managed and legacy.exists():
        path = legacy
    entries = read_json(path)['entries'] if path.exists() else []
    for entry in entries:
        matches = entry['video_sha256'] == video_sha256 and (not managed or all(
            entry.get(key) == delivery_identity[key]
            for key in ('requirement_name', 'task_name', 'target_language')))
        require(not (matches and entry.get('expired_at')),
                'Expired delivery package cannot be replayed; create a new result')


def export(run, root=None, video_sha256=None, reuse_manifests=()):
    """Keep source reads, package creation and catalog registration outside sweeps."""
    from .common import run_operation
    root, run = Path(root or ROOT).resolve(), Path(run).resolve()
    require(run.parent == root / 'runs', 'Archive source must belong to the selected workspace runs')
    with run_operation(run, resume=False):
        return _export(run, root, video_sha256, reuse_manifests)


def _export(run, root, video_sha256=None, reuse_manifests=()):
    """Archive a delivered result or an explicitly selected historical reference.

    A reference with a revise decision remains a reference, never a passed delivery.
    """
    root, run = Path(root or ROOT), Path(run)
    record = read_json(run / "run.json")
    source = inside(run, record["source"])
    require(file_hash(source) == record["source_sha256"], "Source changed before archive")
    request = read_json(run / "inputs/request.json")
    language = request["target_language"]
    require(re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", language), "Invalid target locale")
    delivery = read_json(run / "outputs/delivery.json") if (run / "outputs/delivery.json").exists() else {}
    video_sha256 = video_sha256 or delivery.get("sha256")
    require(re.fullmatch(r"[a-f0-9]{64}", video_sha256 or ""), "Select a bound actual video")
    videos = [p for p in (run / "outputs").glob("*.mp4") if file_hash(p) == video_sha256]
    require(bool(videos), "Selected video not found in run outputs")
    video = sorted(videos, key=lambda p: (p.name != "final.mp4", p.name))[0]
    version = video_sha256[:16]
    if delivery.get('scope') == 'best_available':
        version += '-best-' + delivery['completion_sha256'][:8]
    from . import delivery_layout
    policy = delivery_layout.settings(root)
    managed = policy.get('enabled')
    reusable_mode = _reusable_mode(request, policy)
    delivery_identity = delivery_layout.identity(run) if managed else {}
    _reject_expired_replay(root, video_sha256, delivery_identity, managed)
    folder = (inside(root, f"outputs/.packages/{delivery_identity['requirement_name']}/{language}/{delivery_identity['task_name']}/{version}")
              if managed else inside(root / "outputs", f"{source_folder(root, record['source_sha256'])}/{language}/{version}"))
    existed = (folder / "manifest.json").exists()
    if existed:
        previous = bundles.verify(folder)
        require(previous["metadata"]["source_sha256"] == record["source_sha256"], "Source bundle collision")
        require(not (reusable_mode and previous['metadata'].get('package_mode') == 'lean'),
                'Immutable lean package cannot be upgraded to a reusable package on replay')
        return _register(root, run, folder, previous, delivery_identity, managed, existed=True)
    sources = {"run.json": run / "run.json", "inputs/request.json": run / "inputs/request.json"}
    if reusable_mode:
        sources.update({record["source"]: source, video.relative_to(run).as_posix(): video})
    for relative in ("analysis/media.json", "analysis/inventory.json", "plan.json",
                     "outputs/actual-costs.json", "outputs/revision-summary.json", "inputs/narration-plan.json",
                     "inputs/budget.json"):
        if (run / relative).is_file():
            sources[relative] = run / relative
    candidate_path = run / "outputs/candidate.json"
    if candidate_path.exists():
        candidate = read_json(candidate_path)
        if candidate.get("sha256") == video_sha256:
            actual = inside(run, candidate["path"])
            require(file_hash(actual) == video_sha256, "Current candidate changed before archive")
            sources["outputs/candidate.json"] = candidate_path
            if reusable_mode:
                sources[candidate["path"]] = actual
    # Only actual-video-matched reviews; retain historical revise decisions unchanged.
    quality_records = []
    for path in [run / "outputs/quality.json", *sorted((run / "outputs/quality-history").glob("*.json"))]:
        if path.is_file() and read_json(path).get("video_sha256") == video_sha256:
            sources[path.relative_to(run).as_posix()] = path
            quality_records.append(read_json(path))
    for path in (run / "review").glob("*.json"):
        data = read_json(path)
        if data.get("video_sha256") == video_sha256:
            sources[path.relative_to(run).as_posix()] = path
    review_folder = run / "review" / video_sha256[:12]
    for path in review_folder.rglob("*") if review_folder.exists() else ():
        if path.is_file() and (reusable_mode or path.suffix.lower() == '.json'):
            sources[path.relative_to(run).as_posix()] = path
    if delivery.get("sha256") == video_sha256:
        sources["outputs/delivery.json"] = run / "outputs/delivery.json"
    roots, reusable = [], []
    if reusable_mode:
        _collect_reusable(run, root, video_sha256, language, candidate_path, reuse_manifests, sources, roots, reusable)
    completion_path = run / 'outputs/completion.json'
    if completion_path.exists():
        completion = read_json(completion_path)
        selection = completion.get('knowledge_selection')
        if selection and completion.get('video_sha256') == video_sha256:
            path = inside(run, selection['path'])
            require(path.is_relative_to(run / 'plans') and file_hash(path) == selection['sha256'], 'Finalization knowledge selection changed')
            require(read_json(path).get('video_sha256') == video_sha256, 'Finalization knowledge belongs to another video')
            for frozen in path.parent.rglob('*'):
                if frozen.is_file() and (reusable_mode or frozen.suffix.lower() == '.json'):
                    sources[frozen.relative_to(run).as_posix()] = frozen
    files = {f"payload/{relative}": path for relative, path in sources.items()}
    best_available = False
    if delivery.get('scope') == 'best_available' and delivery.get('sha256') == video_sha256:
        require(file_hash(completion_path) == delivery['completion_sha256'], 'Completion record changed')
        completion = read_json(completion_path)
        require(completion['video_sha256'] == video_sha256 and completion.get('quality_passed') is False,
                'Best-available output must not claim quality approval')
        best_available = True
        files['payload/outputs/completion.json'] = completion_path
    files["final.mp4"] = video
    quality_decision = quality_records[0].get("decision") if quality_records else "not_bound"
    completed = delivery.get("sha256") == video_sha256 and quality_decision == "pass"
    from .resources import preflight
    if not (folder / 'manifest.json').exists():
        missing_bytes = sum(path.stat().st_size for relative, path in files.items()
                            if not inside(folder, relative).exists())
        preflight(root, folder, missing_bytes)
    manifest = bundles.create(folder, "delivery", video_sha256, files, {
        "source_sha256": record["source_sha256"], "target_language": language, "origin_run_id": run.name,
        "video_sha256": video_sha256, "status": "delivered_with_issues" if best_available else "delivered" if completed else "historical_reference",
        "quality_scope": quality_records[0].get('scope', 'strict') if quality_records else 'unreviewed',
        "technical_decision": quality_decision, "reusable": reusable,
        "package_mode": 'reusable' if reusable_mode else 'lean',
        "restoration_eligible": reusable_mode, "source_reuse_eligible": reusable_mode,
        "restoration": ("payload paths retain the original run-relative layout; restore before rebinding a new locale"
                        if reusable_mode else "Standalone final video and audit JSON only; cannot restore a production run or reuse source assets."),
        "expiry_boundary": "Deleting this package loses its deliverable/reuse assets; independent knowledge cases remain usable."
    })
    return _register(root, run, folder, manifest, delivery_identity, managed, existed=False)


def _register(root, run, folder, manifest, delivery_identity, managed, existed):
    """Keep first archive identity/order; only the newest entry owns the final view."""
    from . import delivery_layout
    metadata = manifest['metadata']
    video_sha256 = manifest['identity']
    catalog_path = delivery_layout.catalog(root)
    with lock(root / "outputs/.catalog.lock"):
        legacy_catalog = root / 'outputs/index.json'
        catalog = (read_json(catalog_path) if catalog_path.exists() else read_json(legacy_catalog)
                   if managed and legacy_catalog.exists() else {"schema_version": 1, "entries": []})
        entries = catalog['entries']
        position = next((i for i, e in enumerate(entries) if e['video_sha256'] == video_sha256 and
                         (not managed or all(e.get(k) == delivery_identity[k] for k in
                                             ('requirement_name', 'task_name', 'target_language')))), None)
        previous = entries[position] if position is not None else {}
        entry = {**previous, 'source_sha256': metadata['source_sha256'],
                 'target_language': metadata['target_language'], 'video_sha256': video_sha256,
                 'package': folder.relative_to(root).as_posix(),
                 'manifest_sha256': file_hash(folder / 'manifest.json'),
                 'status': metadata['status'], 'origin_run_id': metadata['origin_run_id'],
                 'archived_at': previous.get('archived_at') or manifest.get('created_at') or utc_now(),
                 **delivery_identity}
        if position is None:
            entries.append(entry)
        else:
            entries[position] = entry
        presented = False
        if managed and not entry.get('expired_at'):
            newest = next(e for e in delivery_layout.latest(entries, root) if all(
                e.get(k) == entry.get(k) for k in ('requirement_name', 'task_name', 'target_language')))
            if entry.get('keep_multiple_versions') or newest is entry:
                entry['presentation'] = delivery_layout.present(root, entry, folder / 'final.mp4')
                presented = True
        write_json(catalog_path, catalog)
    return {'package': folder.relative_to(root).as_posix(), 'files': len(manifest['files']),
            **({'final_file': entry['presentation']} if presented else {}),
            'presentation_current': presented, 'status': metadata['status'], 'reused': existed}


def find(source_sha256, target_language=None, root=None):
    root = Path(root or ROOT)
    from .delivery_layout import catalog
    path = catalog(root)
    if not path.exists() and (root / 'outputs/index.json').exists():
        path = root / 'outputs/index.json'
    entries = read_json(path)["entries"] if path.exists() else []
    result = []
    for entry in entries:
        if entry["source_sha256"] != source_sha256 or (target_language and entry["target_language"] != target_language):
            continue
        folder = inside(root, entry["package"])
        state = "expired"
        accepted, visual_holds = False, []
        reusable_mode, source_reuse = False, False
        if not entry.get('expired_at') and (folder / "manifest.json").exists():
            from .common import WorkflowError
            try:
                verified = bundles.verify(folder)
                require(verified["metadata"]["source_sha256"] == entry["source_sha256"], "Package source mismatch")
                require(verified["metadata"]["target_language"] == entry["target_language"], "Package locale mismatch")
                require(verified["identity"] == entry["video_sha256"], "Package video mismatch")
                require(verified["metadata"]["status"] == entry["status"], "Package status mismatch")
                require(not entry.get("manifest_sha256") or file_hash(folder / "manifest.json") == entry["manifest_sha256"], "Package manifest changed")
                state = "available"
                reusable_mode = verified['metadata'].get('package_mode') != 'lean'
                reusable_mode = reusable_mode and verified['metadata'].get('restoration_eligible', True) is not False
                source_reuse = reusable_mode and verified['metadata'].get('source_reuse_eligible', True) is not False
                accepted = verified["metadata"]["status"] == "delivered" and verified["metadata"].get("technical_decision") == "pass"
            except WorkflowError:
                state = "invalid"
        from .quality_holds import active
        if state == "available":
            for item in verified["metadata"].get("reusable", []):
                if item.get("kind") == "prepared_video":
                    visual_holds.extend(active(entry["source_sha256"], item["asset"]["sha256"], root))
        holds = active(entry["source_sha256"], entry["video_sha256"], root)
        result.append({**entry, "availability": state, "quality_holds": holds,
                       "visual_reuse_holds": visual_holds,
                       "effective_status": "revise" if holds else entry["status"],
                       "delivery_eligible": state == "available" and accepted and not holds,
                       "restoration_eligible": state == "available" and reusable_mode,
                       "source_reuse_eligible": state == "available" and source_reuse and not holds and not visual_holds,
                       "production_eligible": state == "available" and reusable_mode and accepted and not holds and not visual_holds})
    return result
