#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$ROOT"

if [[ ! -f compose.yaml || ! -x scripts/lab.sh ]]; then
    echo "Run this script from the gpu-cluster-system checkout." >&2
    exit 1
fi

docker_cmd() {
    if docker info >/dev/null 2>&1; then
        docker "$@"
    elif [[ " $(id -nG "$(id -un)") " == *" docker "* ]] && sg docker -c 'docker info' >/dev/null 2>&1; then
        local command
        printf -v command '%q ' docker "$@"
        sg docker -c "$command"
    else
        echo "Docker access is unavailable for $(id -un)." >&2
        exit 1
    fi
}

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    echo "Tracked files have local changes. Commit/stash them before applying an update." >&2
    git status --short
    exit 1
fi

echo "==> Updating repository to origin/main"
git fetch origin main
current_branch=$(git branch --show-current)
if [[ "$current_branch" != "main" ]]; then
    git switch main
fi
git pull --ff-only origin main

remote=false
if [[ -n "$(docker_cmd compose --profile remote ps -q cloudflared 2>/dev/null || true)" ]]; then
    remote=true
fi

echo "==> Rebuilding the PyTorch student image"
./scripts/lab.sh torch-image

echo "==> Rebuilding and updating portal/backend images"
if [[ "$remote" == true ]]; then
    ./scripts/lab.sh up --remote
else
    ./scripts/lab.sh up
fi

echo "==> Pausing scheduler while runtime containers are refreshed"
docker_cmd compose stop scheduler-worker >/dev/null

restore_worker() {
    docker_cmd compose up -d --no-build --pull never scheduler-worker >/dev/null 2>&1 || true
}
trap restore_worker EXIT

echo "==> Recreating running member workspaces/debug sessions"
docker_cmd compose exec -T backend python3 -m app.apply_update

echo "==> Restarting scheduler"
docker_cmd compose up -d --no-build --pull never scheduler-worker --wait --wait-timeout 180
trap - EXIT

echo "==> Verifying services"
docker_cmd compose exec -T backend python3 -c \
    'import urllib.request; print(urllib.request.urlopen("http://localhost:8000/api/health", timeout=5).read().decode())'
docker_cmd compose --profile remote --profile gpu --profile host ps

if [[ "$remote" == true ]]; then
    echo
    ./scripts/lab.sh remote-url || true
fi

cat <<'EOF'

Update applied.

Preserved:
  - workspace/results/scratch files
  - per-user Python environments
  - per-user IDE/Codex state
  - running training containers
  - active debug DB records, GPU assignments and deadlines
  - existing Cloudflare Quick Tunnel when it was already running

Recreated:
  - application services whose images changed
  - running member workspace containers
  - running debug containers

Future updates can be applied with this same command:
  ./apply-latest.sh
EOF
