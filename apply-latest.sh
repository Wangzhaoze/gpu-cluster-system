#!/usr/bin/env bash
set -euo pipefail

UPDATE_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$UPDATE_ROOT"

usage() {
    cat <<'EOF'
Usage: ./apply-latest.sh [--remote] [--restart] [--no-build] [--pull]
  Default: apply this checkout, including your local code changes.
  --remote    Also create/start the Cloudflare public tunnel.
  --restart   Recreate backend/frontend even when their images are unchanged.
  --no-build  Start/update using existing application images only.
  --pull      Fast-forward the current branch first; requires clean tracked files.

Student workspaces, debug/training containers, volumes and datasets are retained.
Only changed application images are built. CUDA/PyTorch images are never rebuilt.
EOF
}

docker_cmd() {
    if [[ "$docker_group" == true ]]; then
        local command
        printf -v command '%q ' docker "$@"
        sg docker -c "$command"
    else
        docker "$@"
    fi
}

env_value() { python3 scripts/lab_env.py get "$1"; }
compose() { docker_cmd "${compose_args[@]}" "$@"; }
image_id() { docker_cmd image inspect --format '{{.Id}}' "$1" 2>/dev/null || true; }
service_id() { compose ps -a -q "$1"; }
old_service_image() {
    local container
    container=$(service_id "$1")
    if [[ -n "$container" ]]; then docker_cmd inspect --format '{{.Image}}' "$container"; else image_id "$2"; fi
}


remote_url() {
    local container started logs
    container=$(service_id cloudflared)
    [[ -n "$container" ]] || return 1
    started=$(docker_cmd inspect --format '{{.State.StartedAt}}' "$container")
    logs=$(docker_cmd logs --since "$started" "$container" 2>&1)
    [[ "$logs" == *'Registered tunnel connection'* ]] || return 1
    printf '%s\n' "$logs" | sed -nE 's/.*(https:\/\/[a-z0-9-]+\.trycloudflare\.com).*/\1/p' | tail -n 1
}

record_candidates() {
    local backend_id frontend_id
    backend_id=$(image_id "$backend_tag")
    frontend_id=$(image_id "$frontend_tag")
    python3 - "$image_ledger" "$old_backend" "$old_frontend" "$backend_id" "$frontend_id" <<'PY'
import json, pathlib, re, sys
path = pathlib.Path(sys.argv[1])
old = json.loads(path.read_text()) if path.exists() else []
values = sorted(set(old + [v for v in sys.argv[2:] if re.fullmatch(r'sha256:[0-9a-f]{64}', v)]))
temporary = path.with_suffix('.tmp')
temporary.write_text(json.dumps(values))
temporary.chmod(0o600)
temporary.replace(path)
PY
}

ensure_infrastructure() {
    local service=$1
    if [[ -n "$(service_id "$service")" ]]; then
        # Start existing infrastructure without changing its container or image.
        compose start --wait --wait-timeout 180 "$service"
    else
        compose up -d --no-deps --no-build --pull never --wait --wait-timeout 180 "$service"
    fi
}

on_exit() {
    local status=$?
    trap - EXIT INT TERM
    if [[ "$status" != 0 ]]; then
        set +e
        record_candidates
        [[ -z "$old_backend" ]] || docker_cmd image tag "$old_backend" "$backend_tag"
        [[ -z "$old_frontend" ]] || docker_cmd image tag "$old_frontend" "$frontend_tag"
        if [[ "$update_started" == true && -n "$old_backend" && -n "$old_frontend" ]]; then
            echo "Update failed; restoring previous application images." >&2
            # Keep additive DB migrations: old images cannot resolve a newer
            # Alembic revision, so skip their migration/seed startup command.
            local override
            override=$(mktemp)
            cat > "$override" <<'YAML'
services:
  backend:
    command: [uvicorn, 'app.server:app', --host, '0.0.0.0', --port, '8000', --proxy-headers, '--forwarded-allow-ips=*']
YAML
            docker_cmd "${compose_args[@]}" -f compose.yaml -f "$override" up -d --no-deps --no-build --pull never --wait --wait-timeout 180 backend frontend
            local recovered=$?
            rm -f "$override"
            if [[ "$recovered" == 0 && "$worker_was_running" == true ]]; then
                compose up -d --no-deps --no-build --pull never scheduler-worker
            fi
        elif [[ "$worker_paused" == true && "$worker_was_running" == true ]]; then
            compose start scheduler-worker
        fi
        echo "No student containers, volumes or datasets were removed. Fix the error and rerun this script." >&2
    fi
    exit "$status"
}

main() {
    local remote=false restart=false build=true pull=false
    for option in "$@"; do
        case "$option" in
            --remote) remote=true ;;
            --restart) restart=true ;;
            --no-build) build=false ;;
            --pull) pull=true ;;
            --help|-h) usage; return ;;
            *) usage >&2; return 2 ;;
        esac
    done
    [[ -f compose.yaml && -f .env ]] || { echo "Existing compose.yaml and .env are required." >&2; return 1; }
    exec 9> .apply-latest.lock
    flock -n 9 || { echo "Another update is already running." >&2; return 1; }
    if [[ "$pull" == true ]]; then
        [[ -z "$(git status --porcelain --untracked-files=no)" ]] || {
            echo "--pull requires clean tracked files. Default mode applies your local changes." >&2; return 1;
        }
        local branch
        branch=$(git branch --show-current)
        [[ -n "$branch" ]] || { echo "Detached HEAD: select a branch before --pull." >&2; return 1; }
        git pull --ff-only origin "$branch"
    fi
    docker_group=false
    if ! docker info >/dev/null 2>&1; then
        if [[ " $(id -nG "$(id -un)") " == *" docker "* ]] && sg docker -c 'docker info' >/dev/null 2>&1; then docker_group=true;
        else echo "Docker access is unavailable." >&2; return 1; fi
    fi
    compose_args=(compose)
    [[ $(env_value SCHEDULER_BACKEND) != local-gpu-docker ]] || compose_args+=(--profile gpu)
    local host_enabled
    host_enabled=$(env_value LAB_HOST_EDITOR_ENABLED 2>/dev/null || echo false)
    if [[ "$host_enabled" == true && $(id -u) != "$(env_value LAB_HOST_EDITOR_UID)" ]]; then
        echo "Run this script as the configured native host editor user: $(env_value LAB_HOST_EDITOR_USER)." >&2
        return 1
    fi
    [[ "$host_enabled" != true ]] || compose_args+=(--profile host)
    if [[ -n "$(docker_cmd compose --profile remote ps -a -q cloudflared)" ]]; then remote=true; fi
    [[ "$remote" != true ]] || compose_args+=(--profile remote)
    compose config --quiet

    backend_tag=lab-backend:2026.10-poc
    frontend_tag=lab-frontend:2026.10-poc
    old_backend=$(old_service_image backend "$backend_tag")
    old_frontend=$(old_service_image frontend "$frontend_tag")
    for old in "$old_backend" "$old_frontend"; do
        [[ -z "$old" || -n "$(image_id "$old")" ]] || { echo "An application image needed for rollback is missing; restore it first." >&2; return 1; }
    done
    local runtime_root worker
    runtime_root=$(env_value LAB_HOST_ROOT)
    mkdir -p "$runtime_root/logs"
    image_ledger="$runtime_root/logs/apply-latest-images.json"
    update_started=false worker_paused=false worker_was_running=false
    worker=$(service_id scheduler-worker)
    if [[ -n "$worker" && $(docker_cmd inspect --format '{{.State.Running}}' "$worker") == true ]]; then worker_was_running=true; fi
    trap on_exit EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    record_candidates

    local temporary_builder=""
    if [[ "$build" == true ]]; then
        local base_id node_ref current_label
        base_id=$(image_id "$(env_value LAB_BASE_IMAGE)")
        [[ -n "$base_id" ]] || { echo "Configured lab base image is missing; restore it before updating." >&2; return 1; }
        node_ref=$(env_value LOCAL_NODE_IMAGE)
        export LAB_BACKEND_BUILD_FINGERPRINT LAB_FRONTEND_BUILD_FINGERPRINT
        LAB_BACKEND_BUILD_FINGERPRINT=$(python3 scripts/image_fingerprint.py backend "$base_id")
        LAB_FRONTEND_BUILD_FINGERPRINT=$(python3 scripts/image_fingerprint.py frontend "$base_id" --node-ref "$node_ref")
        current_label=$(docker_cmd image inspect --format '{{index .Config.Labels "lab.build.fingerprint"}}' "$backend_tag" 2>/dev/null || true)
        if [[ "$current_label" != "$LAB_BACKEND_BUILD_FINGERPRINT" ]]; then compose build --pull=false backend; fi
        current_label=$(docker_cmd image inspect --format '{{index .Config.Labels "lab.build.fingerprint"}}' "$frontend_tag" 2>/dev/null || true)
        if [[ "$current_label" != "$LAB_FRONTEND_BUILD_FINGERPRINT" ]]; then
            if [[ -z "$(image_id "$node_ref")" ]]; then
                docker_cmd pull "$node_ref"
                temporary_builder=$node_ref
                python3 - "$runtime_root/logs/apply-latest-builders.json" "$node_ref" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
values = json.loads(path.read_text()) if path.exists() else []
temporary = path.with_suffix('.tmp')
temporary.write_text(json.dumps(sorted(set(values + [sys.argv[2]]))))
temporary.chmod(0o600)
temporary.replace(path)
PY
            fi
            compose build --pull=false frontend
        fi
    fi
    [[ -n "$(image_id "$backend_tag")" && -n "$(image_id "$frontend_tag")" ]] || { echo "Application images are missing." >&2; return 1; }
    record_candidates
    ensure_infrastructure postgres
    [[ "$host_enabled" != true ]] || ./scripts/host-editor.sh start
    update_started=true
    local heartbeat_before
    heartbeat_before=$(cat "$runtime_root/logs/scheduler-heartbeat" 2>/dev/null || true)
    if [[ -n "$worker" ]]; then worker_paused=true; compose stop scheduler-worker; fi
    local up_args=(up -d --no-deps --no-build --pull never --wait --wait-timeout 180)
    [[ "$restart" != true ]] || up_args+=(--force-recreate)
    compose "${up_args[@]}" backend frontend
    ensure_infrastructure traefik
    if [[ $(env_value SCHEDULER_BACKEND) == local-gpu-docker ]]; then ensure_infrastructure gpu-monitor; fi
    [[ "$host_enabled" != true ]] || ensure_infrastructure host-editor-proxy
    [[ "$remote" != true ]] || ensure_infrastructure cloudflared
    compose exec -T backend python3 -c 'import urllib.request; urls=["http://traefik/api/health", "http://traefik/"]; [urllib.request.urlopen(url, timeout=5).read() for url in urls]; print("Portal and API healthy through Traefik")'
    compose up -d --no-deps --no-build --pull never --wait --wait-timeout 180 scheduler-worker
    python3 - "$runtime_root/logs/scheduler-heartbeat" "$heartbeat_before" <<'PY'
import pathlib, sys, time
path = pathlib.Path(sys.argv[1])
for attempt in range(60):
    if path.exists() and path.read_text().strip() != sys.argv[2].strip() and time.time() - path.stat().st_mtime < 30:
        break
    time.sleep(1)
else:
    raise SystemExit('Scheduler did not produce a fresh heartbeat; update failed.')
PY
    worker_paused=false

    local tunnel_url=""
    if [[ "$remote" == true ]]; then
        for attempt in {1..15}; do
            if tunnel_url=$(remote_url 2>/dev/null) && [[ -n "$tunnel_url" ]]; then break; fi
            sleep 2
        done
        [[ -n "$tunnel_url" ]] || { echo "Public tunnel did not register a connection; inspect cloudflared logs." >&2; return 1; }
    fi

    local cleanup=(exec -T backend python3 -m app.update_images --ledger /runtime/logs/apply-latest-images.json --builder-ledger /runtime/logs/apply-latest-builders.json)
    [[ -z "$temporary_builder" ]] || cleanup+=(--builder-tag "$temporary_builder")
    if ! compose "${cleanup[@]}"; then echo "Services updated; application image cleanup is deferred and will retry next run." >&2; fi
    trap - EXIT INT TERM
    compose ps
    echo "Current checkout applied. Student containers, persistent data and existing public tunnel retained."
    [[ -z "$tunnel_url" ]] || echo "Public portal: $tunnel_url"
}

main "$@"
