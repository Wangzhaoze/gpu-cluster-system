#!/usr/bin/env bash
set -euo pipefail
HOST_EDITOR_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec python3 "$HOST_EDITOR_ROOT/scripts/host_editor.py" "$@"
