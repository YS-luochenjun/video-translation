"""Run contract/integration tests with per-case durations and a saved machine-readable result."""
import json
import statistics
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class TimedResult(unittest.TextTestResult):
    def startTest(self, test):
        self.started = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test):
        elapsed = time.perf_counter()-self.started
        status = "fail" if any(item[0] == test for item in self.failures) else "error" if any(item[0] == test for item in self.errors) else "skip" if any(item[0] == test for item in self.skipped) else "pass"
        CASES.append({"case": test.id(), "duration_seconds": round(elapsed, 6), "status": status})
        super().stopTest(test)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    CASES = []
    started = time.perf_counter()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=2, resultclass=TimedResult).run(suite)
    durations = [case["duration_seconds"] for case in CASES]
    record = {"checked_at": datetime.now(timezone.utc).isoformat(), "cases": CASES,
              "total_seconds": round(time.perf_counter()-started, 4), "sum_case_seconds": round(sum(durations), 4),
              "mean_case_seconds": round(statistics.mean(durations), 6) if durations else None,
              "maximum_case_seconds": max(durations, default=0), "count": len(CASES),
              "failures": len(result.failures), "errors": len(result.errors), "skips": len(result.skipped),
              "proof_boundary": "Execution contracts and synthetic media integration; no automatic business-quality acceptance"}
    directory = ROOT / "work"
    directory.mkdir(exist_ok=True)
    (directory / "test-results.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in record.items() if key != "cases"}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.wasSuccessful() else 1)

