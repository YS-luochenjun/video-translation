"""User-adjustable storage budgets and read-only planning, never a deletion API."""
from copy import deepcopy
import math
from pathlib import Path
import shutil

from .common import CODE_ROOT, ROOT, WorkflowError, inside, lock, read_json, require, write_json
from .retention import blockers
from .storage import report


AREAS = ("runs", "outputs", "media")
CONFIG = "config/storage-policy.json"
OVERRIDE = "config/storage-policy.local.json"


def _validate(policy):
    require(policy.get("schema_version") == 1 and policy.get("mode") == "preview_only",
            "Storage policy supports schema 1, preview_only")
    for name in AREAS:
        require(isinstance(policy.get(name), dict), f"Missing storage limits: {name}")
        for key in ("max_count", "max_gib"):
            value = policy[name].get(key)
            require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
                    f"{name}.{key} must be a finite nonnegative number; 0 disables")
            if key == "max_count":
                require(type(value) is int, "max_count must be an integer")
    value = policy.get("minimum_free_gib")
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            "minimum_free_gib must be finite and nonnegative")
    for name in ("pinned_runs", "pinned_sources"):
        require(isinstance(policy.get(name), list) and
                all(isinstance(item, str) and item for item in policy[name]), f"Invalid {name}")
    return policy


def settings(root=None):
    root = Path(root or ROOT)
    source = root / CONFIG
    policy = deepcopy(read_json(source if source.exists() else CODE_ROOT / CONFIG))
    local = root / OVERRIDE
    if local.exists():
        overrides = read_json(local)
        require(set(overrides).issubset({*AREAS, "minimum_free_gib", "pinned_runs", "pinned_sources"}),
                "Unknown storage override key")
        for key, value in overrides.items():
            if key in AREAS:
                require(isinstance(value, dict) and set(value).issubset({"max_count", "max_gib"}),
                        "Unknown area storage limit")
                policy[key].update(value)
            else:
                policy[key] = value
    return _validate(policy)


def configure(root=None, *, area=None, max_count=None, max_gib=None, minimum_free_gib=None):
    root = Path(root or ROOT)
    require(area in (*AREAS, None), "Unknown storage area")
    require(area is not None or (max_count is None and max_gib is None),
            "Specify --area when setting area limits")
    changes = {"max_count": max_count, "max_gib": max_gib}
    require(any(value is not None for value in (*changes.values(), minimum_free_gib)),
            "No storage limits specified")
    with lock(root / "state/storage-policy.lock"):
        policy = settings(root)
        updates = {key: value for key, value in changes.items() if value is not None}
        if area:
            policy[area].update(updates)
        if minimum_free_gib is not None:
            policy["minimum_free_gib"] = minimum_free_gib
        _validate(policy)
        path = root / OVERRIDE
        local = read_json(path) if path.exists() else {}
        if updates:
            local.setdefault(area, {}).update(updates)
        if minimum_free_gib is not None:
            local["minimum_free_gib"] = minimum_free_gib
        write_json(path, local)
    return {"policy": policy, "saved": OVERRIDE, "deleted_files": 0}


def _run_summary(run, root, policy):
    """A completed result is not proof that deletion/financial closure is safe."""
    reasons = []
    try:
        record = read_json(run / "run.json")
        if run.name in policy["pinned_runs"] or record["source_sha256"] in policy["pinned_sources"]:
            reasons.append("pinned")
        if (root / "runs/.locks" / (run.name + ".lock")).exists():
            reasons.append("operation_lock")
        reasons.extend(blockers(run))
        quality = read_json(run / "outputs/quality.json") if (run / "outputs/quality.json").exists() else {}
        if quality.get("decision") not in {"pass", "revise", "fail"}:
            reasons.append("no_final_quality_record")
        # No final quality record is the only automatic indication of unfinished work;
        # a quiet/old directory does NOT establish that a chat has stopped using it.
        return {"run": run.name, "source_sha256": record["source_sha256"],
                "quality": quality.get("decision"), "blockers": reasons,
                "next_step": "retain" if reasons else "confirm_idle_then_run_preserve_and_run_delete_preview"}
    except (WorkflowError, OSError, ValueError, KeyError) as error:
        return {"run": run.name, "blockers": [f"unreadable_or_incomplete: {type(error).__name__}"],
                "next_step": "retain"}


def plan(root=None):
    root = Path(root or ROOT).resolve()
    policy, usage = settings(root), report(root)
    runs = [p for p in (root / "runs").iterdir() if p.is_dir() and not p.name.startswith(".")] if (root / "runs").exists() else []
    safe_runs = [p for p in runs if p.resolve() == root / "runs" / p.name]
    catalog = root / "outputs/index.json"
    entries = read_json(catalog).get("entries", []) if catalog.exists() else []
    packages = set()
    for entry in entries:
        package = inside(root, entry["package"])
        require(package.is_relative_to(root / "outputs"), "Delivery catalog escapes outputs")
        if (package / "manifest.json").is_file():
            packages.add(package)
    source_root = root / "media"
    sources = [p for p in source_root.iterdir() if p.is_dir() and not p.name.startswith(".")] if source_root.exists() else []
    counts = {"runs": len(runs), "outputs": len(packages), "media": len(sources)}
    budgets = {}
    for name in AREAS:
        actual_bytes = usage["areas"][name]["logical_bytes"]
        limits = policy[name]
        budgets[name] = {"count": counts[name], "logical_bytes": actual_bytes, **limits,
                         "over_count": bool(limits["max_count"] and counts[name] > limits["max_count"]),
                         "over_bytes": bool(limits["max_gib"] and actual_bytes > limits["max_gib"] * 1024**3)}
    free = shutil.disk_usage(root).free
    return {"mode": "preview_only", "deleted_files": 0, "policy": policy, "budgets": budgets,
            "free_bytes": free, "low_disk_space": free < policy["minimum_free_gib"] * 1024**3,
            "runs": [_run_summary(p, root, policy) for p in sorted(safe_runs)],
            "scan_warnings": {"skipped_links": usage["skipped_links"],
                              "skipped_unavailable": usage["skipped_unavailable"]},
            "unmanaged_output_entries": sorted(
                p.name for p in (root / "outputs").iterdir()
                if p.name not in {"index.json", "index.html", "README.md", "reports"} and not p.name.startswith(".")
                and not any(package.is_relative_to(p) for package in packages)
            ) if (root / "outputs").exists() else [],
            "protected": ["knowledge", "unsettled accounting", "active or pinned tasks", "referenced reuse assets"],
            "next_steps": [
                "Inspect loose previews, download copies and ZIPs separately; they count toward bytes, not package count.",
                "A run needs confirmed idle status, independent knowledge/delivery/reuse verification and run-delete gates.",
                "Output/media eviction needs explicit expiry or verified external relocation; no automatic package deletion is implemented.",
                "Logical sizes are not guaranteed reclaimable bytes. Concurrent activity may change this snapshot."
            ]}
