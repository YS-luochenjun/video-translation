#!/bin/sh
set -eu
plugin_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
runtime_python=${SESSION_CONSOLE_PYTHON:-"${HOME}/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"}
if [ ! -x "$runtime_python" ]; then runtime_python=$(command -v python3); fi
exec "$runtime_python" "$plugin_dir/server.py"
