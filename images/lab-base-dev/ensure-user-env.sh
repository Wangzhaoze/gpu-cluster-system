#!/usr/bin/env bash
set -euo pipefail
# Workspace, debug and train may initialize the shared volume concurrently.
exec 9>/opt/user-env/.init.lock
flock 9
if [ ! -f /opt/user-env/venv/bin/python ]; then
    uv venv --python /usr/bin/python3 --system-site-packages --seed /opt/user-env/venv
    chown -R "$LAB_UID:$LAB_GID" /opt/user-env
fi
flock -u 9
