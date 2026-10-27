#!/bin/sh
set -eu
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
task_python=${WORKBENCH_PYTHON:-}
if [ -z "$task_python" ]; then
  for candidate in "$task_root/.venv/bin/python3" "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3" "python3"; do
    if "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3,10))' 2>/dev/null; then
      task_python=$candidate
      break
    fi
  done
fi
if [ -z "$task_python" ]; then
  echo 'Python 3.10+ required. Set WORKBENCH_PYTHON to the verified interpreter.' >&2
  exit 1
fi
exec "$task_python" -B "$task_root/workbench/start.py" "$@"
