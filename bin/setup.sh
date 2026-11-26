#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$project_root"

for tool in uv ffmpeg ffprobe; do
    if ! command -v "$tool" >/dev/null 2>&1 && [[ ! -x "$project_root/.runtime/ffmpeg/bin/$tool" || "$tool" == uv ]]; then
        printf 'Missing %s. Add it to PATH and rerun bash bin/setup.sh.\n' "$tool" >&2
        exit 1
    fi
done

export UV_PYTHON_INSTALL_DIR="$project_root/.runtime/python"
export UV_PYTHON_BIN_DIR="$project_root/.runtime/bin"
export UV_CACHE_DIR="$project_root/work/cache/uv"
export TMPDIR="$project_root/work/tmp"
mkdir -p "$TMPDIR"

uv venv --managed-python --python 3.12 --allow-existing .venv
.venv/bin/python bin/install_dependencies.py --uv "$(command -v uv)"
.venv/bin/python bin/va.py doctor
