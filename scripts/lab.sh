#!/usr/bin/env bash
set -euo pipefail
LAB_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$LAB_ROOT"

usage() {
    cat <<'EOF'
Usage: ./scripts/lab.sh COMMAND [OPTIONS]
  bootstrap [--dataset-path DIR]  Generate configuration and prepare base images
  up [--remote] [--no-build]      Build and start the application
  down                           Stop this project's containers, retaining data
  status                         Show Compose service status
  logs [SERVICE]                 Follow service logs
  test [--gpu]                   Run backend and application acceptance tests
  workspace-test [--public]     Verify host paths, editable imports and PyTorch
  gpu-test                       Check NVIDIA GPU passthrough through Docker
  torch-image                    Pull PyTorch/CUDA/nvcc and build its lab image
  torch-test                     Compile a CUDA kernel and test PyTorch on GPUs
  set-scheduler MODE             Switch idle cluster to mock-docker/local-gpu-docker
  remote-url                     Print the running Quick Tunnel URL
  remote-test                    Test public HTTPS, editor access and WebSockets
EOF
}

env_value() { python3 scripts/lab_env.py get "$1"; }

# A desktop login may predate its membership in the Docker group. sg refreshes
# that existing membership without sudo or changes to socket permissions.
lab_docker() {
    if [[ "$LAB_DOCKER_GROUP" == true ]]; then
        local command
        printf -v command '%q ' docker "$@"
        sg docker -c "$command"
    else
        docker "$@"
    fi
}

prepare_docker() {
    LAB_DOCKER_GROUP=false
    if ! docker info >/dev/null 2>&1; then
        if [[ " $(id -nG "$(id -un)") " == *' docker '* ]] && sg docker -c 'docker info' >/dev/null 2>&1; then
            LAB_DOCKER_GROUP=true
        else
            echo 'Docker access is unavailable. Enable Docker group access and refresh your login.' >&2
            return 1
        fi
    fi
    lab_docker compose version
    [[ $(lab_docker info --format '{{.OSType}}') == linux ]]
}

ensure_image() {
    if ! lab_docker image inspect "$1" >/dev/null 2>&1; then
        lab_docker pull "$1"
    fi
}

bootstrap() {
    python3 scripts/lab_env.py bootstrap "$@"
    ensure_image "$(env_value LOCAL_CUDA_IMAGE)"
    ensure_image "$(env_value LOCAL_NODE_IMAGE)"
}

remote_url() {
    local container started logs
    container=$(lab_docker compose --profile remote ps -q cloudflared)
    [[ -n "$container" ]] || { echo 'Remote tunnel is not running.' >&2; return 1; }
    started=$(lab_docker inspect --format '{{.State.StartedAt}}' "$container")
    logs=$(lab_docker logs --since "$started" "$container" 2>&1)
    [[ "$logs" == *'Registered tunnel connection'* ]] || {
        echo 'Remote tunnel is still connecting.' >&2; return 1;
    }
    printf '%s\n' "$logs" | sed -nE 's/.*(https:\/\/[a-z0-9-]+\.trycloudflare\.com).*/\1/p' | tail -n 1
}

command=${1:-help}
shift || true
if [[ "$command" == help || "$command" == --help || "$command" == -h ]]; then
    usage
    exit 0
fi
prepare_docker
case "$command" in
    bootstrap) bootstrap "$@" ;;
    up)
        remote=false
        build=true
        for option in "$@"; do
            case "$option" in
                --remote) remote=true ;;
                --no-build) build=false ;;
                *) usage >&2; exit 2 ;;
            esac
        done
        [[ -f .env ]] || bootstrap
        if [[ "$build" == true ]]; then
            bootstrap
            lab_docker build --pull=false \
                --build-arg "LOCAL_CUDA_IMAGE=$(env_value LOCAL_CUDA_IMAGE)" \
                -t "$(env_value LAB_BASE_IMAGE)" -f images/lab-base-dev/Dockerfile .
            lab_docker compose build --pull=false
        fi
        compose_args=(compose)
        if [[ $(env_value SCHEDULER_BACKEND) == local-gpu-docker ]]; then
            compose_args+=(--profile gpu)
        fi
        if [[ "$remote" == true ]]; then
            ensure_image "$(env_value CLOUDFLARED_IMAGE)"
            compose_args+=(--profile remote)
        fi
        lab_docker "${compose_args[@]}" up -d --no-build --pull never --wait --wait-timeout 180
        echo "Portal: http://localhost:$(env_value PORTAL_PORT)"
        echo "Admin username: $(env_value INITIAL_ADMIN_USERNAME). Password: INITIAL_ADMIN_PASSWORD in .env."
        if [[ "$remote" == true ]]; then
            for attempt in {1..15}; do
                if url=$(remote_url 2>/dev/null) && [[ -n "$url" ]]; then
                    echo "Remote portal: $url"
                    break
                fi
                sleep 2
            done
            [[ -n "${url:-}" ]] || echo 'Tunnel still connecting. Run: ./scripts/lab.sh remote-url'
        fi
        ;;
    down)
        containers=$(lab_docker ps -q --filter label=lab.managed=true --filter label=lab.project=gpu-lab-poc)
        if [[ -n "$containers" ]]; then
            mapfile -t container_ids <<< "$containers"
            lab_docker stop "${container_ids[@]}"
        fi
        lab_docker compose --profile remote --profile gpu down
        echo 'Stopped. Files, Python environments, results and database retained.'
        ;;
    status) lab_docker compose --profile remote --profile gpu ps ;;
    logs) lab_docker compose logs -f --tail 100 "$@" ;;
    test)
        [[ $# == 0 || ( $# == 1 && $1 == --gpu ) ]] || { usage >&2; exit 2; }
        lab_docker compose exec -T backend python3 -m pytest -q
        lab_docker compose run --rm --no-deps -T --entrypoint python3 backend integration/acceptance.py "$@"
        ;;
    workspace-test)
        [[ $# == 0 || ( $# == 1 && $1 == --public ) ]] || { usage >&2; exit 2; }
        workspace_args=()
        if [[ $# == 1 ]]; then
            url=$(remote_url)
            [[ -n "$url" ]] || { echo 'No public tunnel URL is available.' >&2; exit 1; }
            workspace_args+=(--url "$url")
        fi
        lab_docker compose run --rm --no-deps -T --entrypoint python3 backend \
            -m integration.workspace_paths "${workspace_args[@]}"
        ;;
    gpu-test)
        lab_docker run --rm --pull never --gpus all --entrypoint nvidia-smi \
            "$(env_value LAB_BASE_IMAGE)" --query-gpu=index,name,memory.total --format=csv
        ;;
    torch-image)
        python3 scripts/lab_env.py bootstrap
        ensure_image "$(env_value PYTORCH_SOURCE_IMAGE)"
        lab_docker build --pull=false \
            --build-arg "PYTORCH_SOURCE_IMAGE=$(env_value PYTORCH_SOURCE_IMAGE)" \
            -t "$(env_value LAB_TORCH_IMAGE)" -f images/lab-torch-dev/Dockerfile .
        echo "Lab PyTorch image ready: $(env_value LAB_TORCH_IMAGE)"
        ;;
    torch-test)
        lab_docker run --rm --pull never --gpus all --entrypoint bash \
            --mount "type=bind,src=$LAB_ROOT/tests/integration,dst=/checks,readonly" \
            "$(env_value LAB_TORCH_IMAGE)" -c \
            'set -e; nvcc --version; nvcc -arch=sm_120 /checks/cuda_smoke.cu -o /tmp/cuda-smoke; /tmp/cuda-smoke; python /checks/torch_smoke.py'
        ;;
    set-scheduler)
        [[ $# == 1 && ( $1 == mock-docker || $1 == local-gpu-docker ) ]] || { usage >&2; exit 2; }
        # Ask the database directly: this also works after the admin changes their password.
        lab_docker compose exec -T backend python3 -c \
            'from sqlalchemy import select; from app.db import SessionLocal; from app.models import Workload; from app.scheduler.base import ACTIVE; db=SessionLocal(); assert db.scalar(select(Workload.id).where(Workload.status.in_(["AWAITING_APPROVAL", "PENDING", *ACTIVE])).limit(1)) is None, "Finish/cancel active workloads before switching scheduler"'
        if [[ $1 == local-gpu-docker ]]; then
            "$LAB_ROOT/scripts/lab.sh" gpu-test
        fi
        python3 scripts/lab_env.py set SCHEDULER_BACKEND "$1"
        if [[ $1 == local-gpu-docker ]]; then
            lab_docker compose --profile gpu up -d --no-build --pull never gpu-monitor
        else
            lab_docker compose --profile gpu stop gpu-monitor
        fi
        lab_docker compose up -d --no-build --pull never --force-recreate backend scheduler-worker --wait --wait-timeout 180
        echo "Scheduler changed to $1."
        ;;
    remote-url) remote_url ;;
    remote-test)
        url=$(remote_url)
        [[ -n "$url" ]] || { echo 'No public tunnel URL is available.' >&2; exit 1; }
        lab_docker compose exec -T backend python3 integration/remote_acceptance.py --url "$url"
        ;;
    *) usage >&2; exit 2 ;;
esac
