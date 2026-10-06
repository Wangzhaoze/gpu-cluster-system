#!/usr/bin/env bash
set -euo pipefail
# Workspace, debug and train may initialize the shared volume concurrently.
exec 9>/opt/user-env/.init.lock
flock 9
expected_abi=$("${LAB_PYTHON:-/usr/bin/python3}" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
if [ -d /opt/user-env/venv ]; then
    current_abi=$(/opt/user-env/venv/bin/python -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)
    if [ "$current_abi" != "$expected_abi" ]; then
        # Explicit template changes can cross Python ABIs: keep the old venv.
        mv /opt/user-env/venv "/opt/user-env/venv-backup-$(date +%s%N)"
        rm -f /opt/user-env/.initialized
    fi
fi
if [ ! -f /opt/user-env/.initialized ] || [ ! -f /opt/user-env/venv/bin/python ]; then
    # uv creates Python before seeding finishes. Recover an interrupted first
    # start without clearing any packages in an existing environment.
    if [ ! -x /opt/user-env/venv/bin/pip ] || ! /opt/user-env/venv/bin/python -m pip --version >/dev/null 2>&1; then
        uv venv --allow-existing --python "${LAB_PYTHON:-/usr/bin/python3}" --system-site-packages --seed /opt/user-env/venv
    fi
    chown -R "$LAB_UID:$LAB_GID" /opt/user-env
    touch /opt/user-env/.initialized
    chown "$LAB_UID:$LAB_GID" /opt/user-env/.initialized
fi
if [[ ${LAB_REQUIRE_TORCH:-false} == true ]]; then
    /opt/user-env/venv/bin/python -c 'import torch; assert torch.version.cuda == "12.8"'
fi
flock -u 9
