"""Deterministic daily lifecycle sweep; default is a read-only plan.

The Windows timer calls this entry with --execute. Retention, preservation and
fingerprint gates belong to project_storage; this entry never invokes reset or AI.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from video_localizer import project_storage
from video_localizer.common import WorkflowError, utc_now, write_json

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RECEIPT = "state/storage-daily-latest.json"


def gates(root):
    if not project_storage.authorized(root):
        return "workspace_authorization_missing", []
    locks = project_storage._locks(root)
    if (root / "state/project-storage.lock").exists():
        locks.append("state/project-storage.lock")
    return ("active_locks", sorted(set(locks))) if locks else (None, [])


def run(root=PROJECT_ROOT, execute=False):
    """Return a short actual receipt, persisting it only in explicit execute mode."""
    root = Path(root).resolve()
    result = {"schema_version": 1, "workspace": str(root),
              "checked_at": utc_now(), "execute_requested": execute,
              "mode": "lifecycle"}
    try:
        reason, locks = gates(root)
        if reason:
            result.update(state="deferred", reason=reason, locks=locks)
        else:
            plan = project_storage.preview(root)
            selected = plan["selected"]
            unavailable = plan.get("unavailable_entries", [])
            retained = {}
            for row in plan.get('retained', []):
                reason = row['reason']
                retained[reason] = retained.get(reason, 0) + 1
            result.update(retained_reasons=retained)
            result.update(fingerprint=plan["fingerprint"], pressure=plan["pressure"],
                          selected_count=len(selected), unavailable_count=len(unavailable),
                          logical_bytes_selected=sum(row.get("logical_bytes", 0) for row in selected))
            if not execute:
                result.update(state="planned", would_execute=bool(selected or unavailable))
            elif selected or unavailable:
                actual = project_storage.execute(root, plan["fingerprint"])
                result.update(state="executed", deleted_count=len(actual["deleted"]),
                              logical_bytes_removed=actual["logical_bytes_removed"],
                              net_free_bytes_change=actual["net_free_bytes_change"],
                              preserved_records=actual["preserved_records"],
                              accounting_sync_error_count=len(actual.get("accounting_sync_errors", [])))
            else:
                result.update(state="no_eligible_data")
    except (WorkflowError, OSError, ValueError, KeyError, TypeError) as exc:
        # A producer or another sweep may have entered after the first check.
        try:
            reason, locks = gates(root)
        except (OSError, ValueError, KeyError, TypeError):
            reason, locks = None, []
        result.update(state="deferred" if reason else "failed", error=str(exc))
        if reason:
            result.update(reason=reason, locks=locks)
        result["scope"] = "No automatic retry; inspect lifecycle receipts for any partial execution."
    if execute:
        write_json(root / RECEIPT, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Run the authorized lifecycle sweep and save its receipt")
    args = parser.parse_args(argv)
    result = run(execute=args.execute)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["state"] == "failed" else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
