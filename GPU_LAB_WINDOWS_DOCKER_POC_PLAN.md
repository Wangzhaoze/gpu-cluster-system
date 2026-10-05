# GPU Lab — Windows Docker POC Implementation Plan

**Goal:** build everything that can be completed on the home Windows PC with Docker first, while keeping the architecture ready for later migration to the Ubuntu lab workstation and Slurm.

**Current phase:** Windows + Docker Desktop only. **Do not install or integrate Slurm yet.**

---

## 1. Architecture decision

```text
Browser
  |
  v
Cloudflare Quick Tunnel        # optional remote profile
  |
  v
Traefik
  |
  +-------------------+
  |                   |
  v                   v
Frontend            Backend API
React               FastAPI
  |                   |
  |                   +--> PostgreSQL
  |                   |
  |                   +--> Docker API
  |                        |
  |                        +--> Workspace containers
  |                        +--> Debug containers
  |                        +--> Training containers
  |
  +--> /workspace/<user> --> code-server
  +--> /debug/<session>  --> code-server
```

Scheduler boundary:

```text
SchedulerBackend
├── MockDockerScheduler       # implement now
├── LocalGpuDockerScheduler   # optional if Windows Docker GPU works
└── SlurmScheduler            # stub only; implement later on Ubuntu
```

Core rule:

> User files and Python environments persist. Containers are disposable. GPU allocation belongs to Debug/Training sessions, not to a permanent user container.

---

## 2. What must be implemented on Windows

- Docker Compose project
- Portal login/auth
- Admin/member roles
- User management
- Persistent per-user workspace
- Persistent per-user Python environment
- Persistent results
- Shared read-only dataset
- CPU-only Workspace container
- Browser VS Code via code-server
- Temporary Debug containers
- Temporary Training containers
- Mock 5-GPU scheduler
- Queue / job lifecycle / cancellation / retry
- Debug TTL
- Job logs
- Environment templates
- Global/per-user environment variables
- Storage usage display
- Traefik dynamic routing
- Cloudflare Quick Tunnel profile
- Current Quick Tunnel URL display
- Admin dashboard
- User dashboard
- Basic audit log
- PowerShell bootstrap/start/stop/test scripts
- Acceptance tests

Optional now:

- real local Windows GPU passthrough if Docker Desktop supports it
- basic Docker CPU/RAM metrics
- Prometheus/Grafana profile

Do **not** implement now:

- Slurm / Munge / Pyxis / Enroot
- Kubernetes / K3s / Kueue
- ClearML as scheduler
- JupyterHub
- Open OnDemand / Slurm-web
- Conda
- Harbor / Keycloak / Ceph
- production custom domain
- public SSH
- hard disk quotas

---

## 3. Improvements borrowed from the alternative proposal

Adopt these ideas:

1. Persistent Python venv with `uv venv --system-site-packages`.
2. Base image provides Python/PyTorch/common packages; users only add project Python packages.
3. `apt install` persistence is explicitly **not guaranteed**.
4. Each user is pinned to an environment image version; no silent upgrades.
5. Shared dataset exists once and is mounted `:ro` everywhere.
6. Shared memory size is configurable (`2g` Windows POC, later `16g` on Ubuntu if useful).
7. Global + per-user env vars are injected on new container creation only.
8. Delivery is phase-based with concrete acceptance tests.

Do **not** adopt:

- fixed Debug/Training GPU pools
- ClearML as GPU scheduler
- separate JupyterHub login/user system

---

## 4. Windows host requirements

Expected host:

```text
Windows 10/11
Docker Desktop
Docker Compose v2
Linux containers
WSL2 backend recommended
Git
```

No host Python, Node, PostgreSQL, Redis, etc. should be required.

Recommended Docker Desktop resources for the POC:

```text
CPU >= 4 cores
RAM >= 8 GB
Disk >= 30 GB free
```

---

## 5. Repository layout

```text
gpu-lab/
├── compose.yaml
├── compose.override.windows.yaml
├── .env.example
├── .gitignore
├── .gitattributes
├── README.md
│
├── frontend/
│   ├── Dockerfile
│   └── src/
│
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/
│   └── app/
│       ├── main.py
│       ├── config.py
│       ├── db.py
│       ├── models/
│       ├── schemas/
│       ├── api/
│       ├── auth/
│       ├── docker/
│       ├── scheduler/
│       │   ├── base.py
│       │   ├── mock_docker.py
│       │   ├── local_gpu_docker.py
│       │   └── slurm.py
│       ├── services/
│       └── workers/
│
├── images/
│   └── lab-base-dev/
│       ├── Dockerfile
│       ├── entrypoint.sh
│       └── ensure-user-env.sh
│
├── infra/
│   └── traefik/
│       └── traefik.yml
│
├── scripts/
│   ├── bootstrap.ps1
│   ├── up.ps1
│   ├── down.ps1
│   ├── reset-dev.ps1
│   ├── logs.ps1
│   └── acceptance-test.ps1
│
├── runtime/
│   ├── users/
│   ├── datasets/
│   ├── results/
│   ├── scratch/
│   └── logs/
│
├── tests/
│   ├── backend/
│   └── integration/
│
└── docs/
    ├── ARCHITECTURE.md
    ├── WINDOWS_POC.md
    ├── UBUNTU_MIGRATION.md
    └── IMPLEMENTATION_NOTES.md
```

---

## 6. Static Compose services

Static services:

```text
traefik
frontend
backend
scheduler-worker
postgres
cloudflared          # profile: remote
```

Optional profile:

```text
prometheus
grafana
```

All services join one Docker network:

```text
lab-net
```

Dynamic Workspace/Debug/Training containers also join `lab-net`.

Dynamic workload containers must **not** be hard-coded in Compose.

---

## 7. Networking

### Local

Expose only Traefik to Windows:

```text
http://localhost:8080
```

Do not expose direct host ports for:

- backend
- PostgreSQL
- workspaces
- debug containers
- training containers

### Remote

Cloudflared points to:

```text
http://traefik:80
```

Start with:

```powershell
docker compose --profile remote up -d
```

Expected:

```text
https://random-name.trycloudflare.com
```

### Path routing

Quick Tunnel hostname is random, so use **path-based** routes:

```text
/                       -> frontend
/api/*                  -> backend
/workspace/<username>/* -> user's code-server
/debug/<session_id>/*   -> debug code-server
```

Do not rely on custom subdomains in this POC.

---

## 8. Authentication

Use only our Lab Portal account system.

Suggested stack:

```text
FastAPI
SQLAlchemy
Alembic
PostgreSQL
Argon2 password hashing
HTTP-only session cookie
```

Roles:

```text
ADMIN
MEMBER
```

Portal session cookie:

```text
lab_session
HttpOnly
SameSite=Lax
Secure under HTTPS
```

---

## 9. Traefik ForwardAuth

Workspace/Debug code-server runs with:

```text
--auth none
```

but the container is not directly exposed.

Traefik applies ForwardAuth to Workspace/Debug routes.

Backend endpoint:

```text
GET /api/auth/traefik
```

Backend checks:

```text
lab_session cookie
X-Forwarded-Uri
```

Rules:

```text
ADMIN:
  can access all workspaces/debug sessions

MEMBER:
  can access only own workspace
  can access only own debug sessions
```

This gives one login for the complete platform.

---

## 10. PostgreSQL tables

Minimum schema:

### users

```text
id
username
display_name
password_hash
role
enabled
uid_hint
default_environment_id
max_gpus
max_debug_hours
created_at
updated_at
```

### environment_templates

```text
id
name
image
image_version
description
enabled
created_at
```

### global_env_vars / user_env_vars

```text
key
value
is_secret
enabled
```

User table also includes `user_id`.

### workspaces

```text
user_id
container_id
state
route_path
last_started_at
last_stopped_at
```

### jobs

```text
id
user_id
status
requested_gpus
assigned_gpus_json
requested_cpus
requested_ram_mb
time_limit_seconds
environment_id
command
workdir
created_at
started_at
finished_at
exit_code
container_id
log_path
error_message
```

### debug_sessions

```text
id
user_id
status
requested_gpus
assigned_gpus_json
environment_id
route_path
container_id
created_at
started_at
expires_at
finished_at
```

### gpu_slots

Seed 5 rows:

```text
GPU0 FREE
GPU1 FREE
GPU2 FREE
GPU3 FREE
GPU4 FREE
```

Columns:

```text
gpu_index
state
owner_type
owner_id
updated_at
```

### audit_events

```text
id
user_id
action
target_type
target_id
metadata_json
created_at
```

---

## 11. Windows storage model

Use a hybrid storage model.

### Bind mounts for ordinary files

Host:

```text
./runtime/users/<username>/workspace
./runtime/results/<username>
./runtime/scratch/<username>
./runtime/datasets
```

Container:

```text
/workspace
/results
/scratch
/datasets
```

Dataset must always be mounted read-only.

### Named volume for Python venv

Per user:

```text
lab_pyenv_<username>
```

Mount:

```text
/opt/user-env
```

Reason:

- Linux filesystem semantics
- better than putting a venv directly on NTFS
- survives container deletion
- same venv is reused by Workspace/Debug/Train

Create a `StorageProvider` abstraction so the Ubuntu version can later replace this with:

```text
/srv/lab/home/<username>/python-env
```

without changing application logic.

---

## 12. Persistent Python environment

Critical design requirement.

Every user has:

```text
/opt/user-env/venv
```

Initialize once:

```bash
uv venv --system-site-packages /opt/user-env/venv
```

Every user workload container sets:

```text
VIRTUAL_ENV=/opt/user-env/venv
PATH=/opt/user-env/venv/bin:$PATH
```

If student runs:

```bash
pip install transformers
uv pip install timm
```

those packages persist in the named volume.

They must remain available in:

```text
Workspace
Debug
Training
```

Deleting any container must not delete the venv.

`sudo apt install` changes do **not** need to persist.

---

## 13. Base development image

Build:

```text
lab-base-dev:2026.10-poc
```

Requirements:

- Debian/Ubuntu-based
- Python
- uv
- pip
- code-server
- sudo
- git
- curl
- tmux
- htop
- procps
- build-essential
- common debugging tools

Optional:

- CPU PyTorch
- torchvision

If CPU PyTorch is installed in base/system Python, the persistent venv inherits it using `--system-site-packages`.

Do not use Conda.

After first successful build, pin relevant package/image versions; avoid indefinite `latest` use.

---

## 14. Dynamic Linux user inside user containers

Support:

```text
LAB_USERNAME
LAB_UID
LAB_GID
```

Entrypoint:

1. create user if missing
2. grant NOPASSWD sudo inside container
3. ensure writable mount ownership where applicable
4. ensure persistent venv exists
5. launch requested process as the user

User workload containers:

```text
NOT privileged
NO Docker socket
NO host sudo
```

---

## 15. Workspace container

One logical Workspace per user.

Container name:

```text
lab-workspace-<username>
```

Default:

- CPU only
- start/stop from Portal
- code-server
- long-lived but recreatable

Mounts:

```text
workspace -> /workspace
pyenv     -> /opt/user-env
datasets  -> /datasets:ro
results   -> /results
scratch   -> /scratch
```

Environment defaults:

```text
VIRTUAL_ENV=/opt/user-env/venv
HF_HOME=/scratch/hf
TORCH_HOME=/scratch/torch
PIP_CACHE_DIR=/scratch/pip
```

Route:

```text
/workspace/<username>/
```

code-server must use the same base path.

Workspace itself does not consume a GPU.

---

## 16. Debug container

Debug is temporary.

Flow:

```text
User -> Start Debug
     -> scheduler requests GPU slots
     -> create debug container
     -> same workspace + same venv
     -> code-server
     -> TTL expires / user stops
     -> delete container
     -> release GPU slots
```

V1 form:

```text
Environment
GPU count: 0 or 1
Duration: 30m / 1h / 2h / 4h
CPU
RAM
```

Route:

```text
/debug/<session_id>/
```

Mount exactly the same persistent workspace/venv/dataset/results/scratch locations as Workspace.

---

## 17. Training container

Training is disposable.

Form:

```text
Environment
Working directory
Command
GPU count: 0-5
CPU count
RAM
Maximum runtime
Environment variable overrides
Output name
```

Example:

```text
workdir: /workspace/radar-project
command: python train.py --config configs/a.yaml
```

Mounts:

```text
/workspace
/opt/user-env
/datasets:ro
/results
/scratch
```

Shared memory is configurable:

```text
LAB_SHM_SIZE=2g       # Windows POC
```

Later Ubuntu default may become:

```text
16g
```

No public route is needed for training containers.

---

## 18. Scheduler interface

Create the abstraction immediately.

Conceptual interface:

```python
class SchedulerBackend(Protocol):
    def submit_train(self, spec): ...
    def start_debug(self, spec): ...
    def cancel(self, resource_id): ...
    def get_status(self, resource_id): ...
    def list_resources(self): ...
```

Frontend and API must not know whether scheduler is mock Docker or Slurm.

---

## 19. MockDockerScheduler

Implement now.

Configuration:

```text
SCHEDULER_BACKEND=mock-docker
MOCK_GPU_COUNT=5
```

Behavior:

- 5 virtual GPUs
- exclusive allocation
- FIFO
- first-fit allocation
- no preemption
- no sharing
- single scheduler worker for POC

Example:

```text
Job A requests 2 -> GPU0,1
Job B requests 2 -> GPU2,3
Debug C requests 1 -> GPU4
Job D requests 1 -> PENDING
```

When capacity releases, pending work starts automatically.

Mock mode still launches real Docker task containers.

Inject informational variables:

```text
LAB_ASSIGNED_GPUS=0,1
CUDA_VISIBLE_DEVICES=0,1
```

UI must show a clear:

```text
MOCK GPU MODE
```

badge.

---

## 20. Optional LocalGpuDockerScheduler

Only after the POC works.

If:

```powershell
docker run --rm --gpus all <cuda-image> nvidia-smi
```

works on the Windows PC, add:

```text
SCHEDULER_BACKEND=local-gpu-docker
LOCAL_GPU_COUNT=<detected/explicit>
```

Use Docker DeviceRequest for real GPU visibility.

This is optional and must not block the POC.

---

## 21. SlurmScheduler stub

Create the class/file now but no Slurm code.

Future flow:

```text
Portal/API
-> SchedulerBackend
-> SlurmScheduler
-> Slurm allocation
-> controlled DockerRunner
```

The frontend must not require redesign later.

---

## 22. Scheduler worker

Run dedicated service:

```text
scheduler-worker
```

Responsibilities:

- poll PENDING jobs
- allocate mock GPU slots
- start workload containers
- monitor state
- enforce time limits
- collect logs
- release slots
- expire debug sessions
- reconcile after restart

Scheduler state must be recoverable from:

```text
PostgreSQL + Docker state
```

Do not depend only on in-memory state.

---

## 23. Docker API access

Only infrastructure components may access Docker API.

Allowed:

- scheduler-worker
- backend if needed for workspace/status actions
- Traefik read-only discovery

Forbidden:

- Workspace containers
- Debug containers
- Training containers

Keep all Docker-control logic behind a `DockerRuntime` service class.

A docker-socket-proxy can be added later if needed; do not let it block the POC.

---

## 24. Container labels

Every managed dynamic container gets labels:

```text
lab.managed=true
lab.kind=workspace|debug|train
lab.user=student01
lab.job_id=<id if applicable>
```

Workspace/Debug containers also get Traefik routing labels.

Labels are used for:

- discovery
- cleanup
- restart reconciliation
- admin UI
- audit

---

## 25. Job lifecycle

Use only these statuses:

```text
PENDING
STARTING
RUNNING
COMPLETED
FAILED
CANCELLED
TIMED_OUT
```

After scheduler-worker restart:

1. inspect `lab.managed=true` containers
2. reconcile with DB
3. recover running work
4. free stale mock GPU slots
5. continue queue

No duplicate containers may be created during recovery.

---

## 26. Logs

Training/debug stdout/stderr must remain after container exit.

Flow:

1. stream Docker logs while running
2. before cleanup save full log to:
   ```text
   ./runtime/logs/jobs/<job_id>.log
   ```
3. DB stores path
4. UI reads saved log after completion

Do not auto-delete a container until logs are captured.

Optional cleanup:

```text
remove stopped workload containers after 24h
```

but keep logs/results.

---

## 27. Results

Host:

```text
./runtime/results/<username>
```

Container:

```text
/results
```

Recommend training output:

```text
/results/<job-name>/
```

Results survive all container deletions.

---

## 28. Dataset

Host:

```text
./runtime/datasets
```

All user containers:

```text
/datasets:ro
```

Acceptance:

```bash
touch /datasets/should-fail.txt
```

must fail.

Bootstrap creates:

```text
runtime/datasets/demo/hello.txt
```

---

## 29. Environment variables

Support precedence:

```text
per-job > per-user > global > base defaults
```

Examples:

```text
HF_HOME=/scratch/hf
TORCH_HOME=/scratch/torch
PIP_CACHE_DIR=/scratch/pip
HTTP_PROXY=
HTTPS_PROXY=
PIP_INDEX_URL=
```

Secrets:

- mark secret
- mask in UI
- do not return plaintext from normal endpoints

UI warning:

> Environment changes apply only to newly started Workspace/Debug/Training containers.

Do not attempt live mutation of an existing container environment.

---

## 30. Environment image pinning

Every user is pinned to an image version.

Example:

```text
student01 -> lab-base-dev:2026.10-poc
```

Do not silently auto-upgrade users.

Later migration flow should explicitly rebuild a venv if Python/base-image ABI changes.

---

## 31. Frontend recommendation

Suggested:

```text
React
TypeScript
Vite
React Router
TanStack Query
Tailwind or equivalent lightweight UI
```

Modern and clean, but no large custom design system.

---

## 32. Member pages

### Dashboard

Show:

- five mock GPU cards
- queue summary
- running jobs
- active debug sessions
- Workspace state
- storage usage
- remote access state

GPU card:

```text
GPU 0
FREE / RUNNING
Owner
Train / Debug
Duration
MOCK badge
```

### Workspace

Actions:

```text
Start
Stop
Restart
Open VS Code
```

Show:

- image version
- persistent venv path
- workspace state

### New Training

Fields:

- environment
- workdir
- command
- GPU count
- CPU
- RAM
- time limit
- env overrides

### Jobs

Show:

- ID
- state
- command
- GPUs
- created time
- runtime
- exit code

Actions:

- logs
- cancel
- retry

### Debug

Start form:

- environment
- 0/1 GPU
- TTL
- CPU
- RAM

Active session:

- Open VS Code
- stop
- remaining time

### Environment

Show:

- pinned image
- persistent venv
- explanation of persistence
- optional package list through workspace exec

### Storage

Show workspace/results/scratch size.

---

## 33. Admin pages

### Overview

Show:

- all mock GPUs
- queue
- running jobs
- active workspaces
- active debug sessions
- users
- current Cloudflare URL

### Users

Actions:

- create
- enable/disable
- reset password
- role
- max GPUs
- max debug time
- default environment
- stop workspace
- cancel jobs

### Environments

- list image templates
- add/disable template
- set default
- assign to user

### Environment Variables

- global
- per-user
- secret mask
- next-start warning

### Storage

- usage by user
- results
- scratch

No hard quota in POC.

### Remote Access

Show:

```text
Mode: Cloudflare Quick Tunnel
Status: Online / Offline
Current URL
Copy URL
Last detected
```

### Audit

Show key actions.

---

## 34. User provisioning

Admin Add User form:

```text
username
display name
initial password
role
default environment
max GPUs
max debug hours
```

Backend automatically:

1. creates DB account
2. creates:
   ```text
   runtime/users/<user>/workspace
   runtime/results/<user>
   runtime/scratch/<user>
   ```
3. creates Docker volume:
   ```text
   lab_pyenv_<user>
   ```
4. initializes venv lazily or immediately
5. creates workspace DB record
6. writes audit event

No Windows host account is created.

---

## 35. Cloudflare Quick Tunnel integration

Compose profile:

```text
remote
```

Cloudflared target:

```text
http://traefik:80
```

Backend endpoint:

```text
GET /api/system/remote-access
```

Expected payload:

```json
{
  "mode": "cloudflare-quick",
  "status": "online",
  "url": "https://random.trycloudflare.com"
}
```

Backend may parse the URL from cloudflared Docker logs.

If unavailable, return offline; the rest of the platform must still work.

Do not build a random-URL forwarding service yet.

---

## 36. PowerShell developer UX

### `bootstrap.ps1`

- verify Docker
- verify Compose
- copy `.env.example` -> `.env` if missing
- create runtime dirs
- create demo dataset
- print next command

### `up.ps1`

Local:

```powershell
.\scripts\up.ps1
```

Remote:

```powershell
.\scripts\up.ps1 -Remote
```

### `down.ps1`

Stops services without deleting persistent data.

### `reset-dev.ps1`

Explicit destructive reset; confirmation required unless `-Force`.

### `logs.ps1`

Tail key services.

### `acceptance-test.ps1`

Run automated checks where possible.

---

## 37. `.env.example`

At minimum:

```text
APP_ENV=development

POSTGRES_DB=gpu_lab
POSTGRES_USER=gpu_lab
POSTGRES_PASSWORD=change-me

INITIAL_ADMIN_USERNAME=admin
INITIAL_ADMIN_PASSWORD=change-me-now

SCHEDULER_BACKEND=mock-docker
MOCK_GPU_COUNT=5

LAB_BASE_IMAGE=lab-base-dev:2026.10-poc
LAB_SHM_SIZE=2g

SESSION_SECRET=change-me
REMOTE_ACCESS_MODE=cloudflare-quick
```

Do not commit real `.env`.

---

## 38. Minimum API

### Auth

```text
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
GET  /api/auth/traefik
```

### Users

```text
GET    /api/users
POST   /api/users
GET    /api/users/{id}
PATCH  /api/users/{id}
POST   /api/users/{id}/reset-password
POST   /api/users/{id}/enable
POST   /api/users/{id}/disable
```

### Workspace

```text
GET  /api/workspace
POST /api/workspace/start
POST /api/workspace/stop
POST /api/workspace/restart
```

### Jobs

```text
GET  /api/jobs
POST /api/jobs
GET  /api/jobs/{id}
POST /api/jobs/{id}/cancel
POST /api/jobs/{id}/retry
GET  /api/jobs/{id}/logs
```

### Debug

```text
GET  /api/debug
POST /api/debug
POST /api/debug/{id}/stop
```

### Resources

```text
GET /api/resources/gpus
GET /api/resources/queue
```

### Environments/settings

```text
GET   /api/environments
POST  /api/environments
PATCH /api/environments/{id}
GET   /api/settings/env
PUT   /api/settings/env
GET   /api/settings/remote
```

### Admin

```text
GET /api/admin/overview
GET /api/admin/storage
GET /api/admin/audit
```

---

## 39. Security boundaries

Even with trusted students:

- no Docker socket in user containers
- no privileged user containers
- no public PostgreSQL
- no direct backend host port
- no direct code-server host port
- all Workspace/Debug access through Traefik + ForwardAuth
- datasets read-only
- members cannot access another member's Workspace/Debug route
- password hashes only
- secret env values masked
- validate workdir stays under `/workspace`
- validate resource limits
- never accept arbitrary host bind-mount paths from users

The goal is mainly preventing accidental conflicts and cross-user mistakes.

---

## 40. Windows-specific rules

1. Linux containers only.
2. Prefer WSL2 backend.
3. Python venv stays in Docker named volume, not NTFS bind mount.
4. Workspace/results/datasets may use bind mounts.
5. Do not depend heavily on Linux host UID semantics in the Windows POC.
6. Use PowerShell for host actions.
7. Keep `.sh` files LF; add `.gitattributes`.
8. No hard-coded Windows drive letters in application code.
9. Host path differences belong in StorageProvider/configuration.

---

## 41. Optional monitoring

Do not block the POC on GPU telemetry.

Optional profile:

```text
Prometheus
Grafana
```

Main dashboard in Windows mock mode uses:

- scheduler DB
- Docker status
- optional Docker stats

Later Ubuntu adds:

- DCGM Exporter
- Prometheus
- real utilization/VRAM/temp

---

# 42. Implementation phases and gates

## Phase A — Skeleton

Implement:

- repo
- Compose
- Traefik
- frontend
- backend
- postgres
- Alembic
- login
- initial admin

Acceptance:

- `docker compose up -d --build`
- portal opens
- admin login works
- DB survives restart

---

## Phase B — Users + storage

Implement:

- CRUD
- runtime directories
- per-user pyenv volume
- StorageProvider
- audit

Acceptance:

- create `student01`
- runtime dirs exist
- `lab_pyenv_student01` exists
- student can login

---

## Phase C — Persistent Python venv

Acceptance sequence:

1. start a temporary user container
2. run:
   ```bash
   pip install rich
   ```
3. delete container
4. start a new container with same pyenv volume
5. run:
   ```bash
   python -c "import rich; print('PERSIST_OK')"
   ```
6. must succeed

Do not continue if this fails.

---

## Phase D — Workspace

Implement code-server + ForwardAuth.

Acceptance:

- student opens Workspace
- terminal works
- workspace files persist
- `rich` still imports
- `/datasets` readable
- writing `/datasets` fails
- admin can open it
- another member cannot

---

## Phase E — Mock 5-GPU scheduler

Acceptance:

```text
2-GPU job -> GPU0,1
2-GPU job -> GPU2,3
1-GPU debug -> GPU4
next 1-GPU job -> PENDING
```

Release capacity and verify queued job starts automatically.

---

## Phase F — Training

Submit:

```bash
python -c "import rich; print('TRAIN_OK')"
```

Acceptance:

- starts through queue
- uses same persistent venv
- logs show TRAIN_OK
- logs persist
- result path persists

---

## Phase G — Debug

Acceptance:

- temporary code-server route opens
- same persistent venv
- 0/1 GPU mock allocation works
- stop releases GPU
- TTL auto-stop works

---

## Phase H — Dashboard/admin

Implement full pages.

Acceptance:

- UI agrees with DB/Docker state
- user/admin permissions correct

---

## Phase I — Cloudflare integration

Acceptance:

```powershell
.\scripts\up.ps1 -Remote
```

Then:

- Admin page displays current `trycloudflare.com` URL
- remote browser can login
- Workspace opens remotely
- code-server WebSocket works remotely

The company network has already been shown to permit Quick Tunnel, but integrated routing still needs this test.

---

## Phase J — Recovery

Test:

1. running/pending jobs exist
2. restart backend + scheduler-worker
3. reconcile state
4. no duplicate containers
5. stale GPU slots corrected
6. queue continues
7. venv/files/results remain

---

# 43. Final end-to-end acceptance

Create:

```text
student01
student02
```

Pass all of these:

1. student01 starts Workspace.
2. installs `rich`.
3. stop/delete Workspace container.
4. recreate Workspace.
5. `import rich` succeeds.
6. start Debug.
7. `import rich` succeeds there.
8. stop Debug.
9. submit Training.
10. `import rich` succeeds there.
11. logs/results persist.
12. dataset is read-only everywhere.
13. student02 has separate venv.
14. student02 cannot access student01 Workspace URL.
15. five mock GPUs allocate correctly.
16. pending job auto-starts after capacity is released.
17. restart static Compose services.
18. users/jobs/files/venvs/results still exist.
19. start remote profile.
20. Quick Tunnel URL appears in Admin UI.
21. remote browser can login and open Workspace.

If all 21 pass, the Windows Docker phase is done.

---

# 44. Ubuntu migration contract

These parts should remain essentially unchanged:

```text
frontend
backend
PostgreSQL schema
authentication
user model
environment templates
persistent venv concept
workspace lifecycle
debug lifecycle
training lifecycle
Traefik
Cloudflare Quick Tunnel
job/debug/admin UI
logs
results
dataset RO model
SchedulerBackend interface
```

Changes on Ubuntu:

### Storage

Windows:

```text
Docker named volume for pyenv
```

Ubuntu:

```text
/srv/lab/home/<user>/python-env
```

through StorageProvider config.

### Base image

Windows:

```text
lab-base-dev
```

Ubuntu:

```text
lab-pytorch:<version>
CUDA + PyTorch
```

### Scheduler

Windows:

```text
MockDockerScheduler
```

Ubuntu:

```text
SlurmScheduler
```

### Monitoring

Windows:

```text
mock / Docker-only
```

Ubuntu:

```text
DCGM Exporter + Prometheus + real GPU metrics
```

No frontend redesign should be needed.

---

# 45. Future Slurm integration contract

Do not implement now, but use a stable `JobSpec` now.

Example:

```json
{
  "user": "student01",
  "environment": "lab-pytorch:2026.10",
  "gpu_count": 2,
  "cpu_count": 8,
  "ram_mb": 32768,
  "time_limit_seconds": 86400,
  "workdir": "/workspace/project",
  "command": "python train.py",
  "env": {}
}
```

Current:

```text
JobSpec
-> MockDockerScheduler
-> mock allocation
-> DockerRuntime
```

Future:

```text
JobSpec
-> SlurmScheduler
-> real Slurm allocation
-> controlled DockerRuntime
```

Do not leak mock-specific assumptions into API/frontend.

---

# 46. Codex implementation rules

Codex should:

- prefer simple maintainable code
- avoid unnecessary microservices
- use typed Python
- use DB migrations
- keep scheduler state recoverable
- add tests for critical flows
- keep secrets out of git
- use explicit container/image versions after initial success
- make README commands PowerShell-friendly
- create clear errors rather than silently failing
- avoid manual setup that cannot be reproduced
- document every deviation in `docs/IMPLEMENTATION_NOTES.md`

Codex must **not** silently replace this architecture with Kubernetes, JupyterHub, ClearML or other platforms.

When a design choice is ambiguous, prefer the smallest implementation that preserves the future SchedulerBackend/StorageProvider boundaries.

---

# 47. Definition of done for the Windows phase

The phase is complete when one command sequence can bring up the platform and a browser can:

- login
- create users
- start/stop a Workspace
- edit code through browser VS Code
- persist pip-installed packages across container replacement
- start Debug
- submit Training
- see a 5-GPU mock queue
- see logs
- cancel/retry jobs
- persist results
- share one read-only dataset
- view storage usage
- view current Quick Tunnel URL
- work remotely through Cloudflare Quick Tunnel
- survive service restarts

At that point, stop adding Docker-only features and move the project to the Ubuntu lab machine for Slurm integration.
