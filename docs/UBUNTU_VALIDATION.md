# Ubuntu deployment verification — 2026-10-06

Host: Ubuntu 24.04.4 LTS, x86_64, Docker Engine 29.8.2, Docker Compose 5.6.0. Four NVIDIA RTX 5060 Ti devices are visible to the host driver.

Deployment: `http://localhost:8080`, bound to `127.0.0.1`. PostgreSQL, backend, scheduler-worker, frontend and Traefik run under the `gpu-lab-poc` Compose project with `unless-stopped` restart policies. The Cloudflare Quick Tunnel is running; public HTTPS and editor access passed the checks below.

Configuration: generated `.env` has permissions `0600`; random administrator/database/session secrets were preserved across bootstrap calls. Runtime and dataset paths are absolute Linux paths. `LOCAL_GPU_COUNT=4`; the active scheduler is `local-gpu-docker` with four physical GPU slots. Credentials are not included in this report.

Validation completed:

- CUDA/code-server base and all four service images built successfully; the frontend TypeScript/Vite production build succeeded.
- Bash syntax and Python compilation checks passed; `docker compose config --quiet` passed.
- Configuration checks passed for private secrets, Linux paths, repeated bootstrap, four-GPU detection and dataset paths containing spaces, dollars and quotes.
- All 29 backend tests passed.
- Full HTTP/PostgreSQL/Docker acceptance passed all 11 checks: authentication/provisioning, editor access controls, container boundaries, persistent files/packages, user environment isolation, logs/results, job retry, shared queue/GPU allocation, restart recovery, cancellation/failure/expiry, storage and audit.
- An incomplete Python environment reproduced the original initialization failure. The fixed initializer recovered pip, preserved an existing file and set user ownership correctly; repeated initialization succeeded.
- The acceptance script now waits for the editor to become available before installing packages, so it cannot mistake the early Python symlink for completed environment initialization.

Acceptance report: `runtime/logs/acceptance.json`. Test accounts were disabled after execution; their results and Python volumes are retained. The administrator retains its pinned Ubuntu Python 3.10 template. A separate PyTorch/Python 3.11 template is registered for fresh students; previous templates and data are preserved.

## Ubuntu-only public and PyTorch update

- Removed obsolete platform scripts, configuration, documentation and interface labels; the repository now documents and supports Ubuntu only.
- Public portal and `/api/health` returned HTTP 200 over `https://basement-solomon-prefer-lat.trycloudflare.com`. Run `./scripts/lab.sh remote-url` for the current address after any tunnel restart.
- All 29 backend tests and 11 local acceptance checks passed after the Ubuntu-only changes.
- All seven remote acceptance checks passed using the new PyTorch template, including HTTPS login, cookies, permissions, editor routing, authenticated WebSocket upgrade/ping/pong, password/session changes and training results.
- Official image available locally: `pytorch/pytorch:2.7.1-cuda12.8-cudnn9-devel`, digest `sha256:3d614dfd422b7e43647491cbf07d6acc516c032fc49c594a94afdebd52552fb9`.
- Lab image available locally: `lab-torch-dev:2.7.1-cu128`, digest `sha256:d5834407a6b440993f87b8f0f54a5aa0845da3eaae85a91eb4efa7d3948fc8c4`.
- Verified Python 3.11.13, PyTorch 2.7.1+cu128, CUDA 12.8, nvcc 12.8 and compiled `sm_120` support. A fresh user venv inherited torch successfully, performed CPU tensor operations and compiled the CUDA smoke kernel for `sm_120`; CUDA execution was not claimed.
- Registered template **CUDA 12.8 · nvcc · PyTorch 2.7.1**, ID `dc3aea2c-1f9d-4228-9426-e079fb3d7f6f`.
- A disposable student with `max_gpus=1` and `max_debug_hours=4` opened a PyTorch editor with a 14400-second session expiry in mock mode. Requests exceeding four hours or the one-GPU limit returned 422. The session was stopped and the test account disabled.
- Host driver is 595.84; all four GPUs report 16311 MiB. NVIDIA Container Toolkit is installed and Docker GPU passthrough succeeds.

## Physical GPU deployment and restart

After the administrator installed NVIDIA Container Toolkit:

- `./scripts/lab.sh gpu-test` exposed all four RTX 5060 Ti devices inside Docker.
- `./scripts/lab.sh torch-test` compiled and executed the `sm_120` CUDA kernel (result 42), then passed PyTorch CUDA matrix multiplication on each of the four GPUs.
- Switched the idle cluster to `local-gpu-docker`, stopped and restarted all six Compose services including Cloudflare, retaining the database and persistent data.
- Removed the exited, unmounted `hello-world` smoke-test container `optimistic_easley`. No other unused containers remain; only the six application services are present.
- `./scripts/lab.sh test --gpu` passed all 29 backend tests and both real-GPU acceptance checks, including a scheduled one-GPU CUDA allocation.
- A disposable student with the PyTorch template opened a real one-GPU debug editor with a 14400-second expiry. Its student venv saw exactly one RTX 5060 Ti, `torch.cuda.is_available()` returned true, and CUDA matrix multiplication passed. Requests above four hours or one GPU returned 422. The debug session was stopped and the account disabled.
- `./scripts/lab.sh remote-test` passed all seven public HTTPS/editor/WebSocket checks after restart.
- Verified the existing administrator password through public HTTPS login and confirmed the ADMIN account can access user management. Credentials were given directly to the requesting administrator, not recorded in repository documentation.
- Final checks found all four real GPU slots free, no active test workloads, all services running, and healthy backend/PostgreSQL containers.

Current GPU acceptance report: `runtime/logs/acceptance-gpu.json`. Public acceptance report: `runtime/logs/acceptance-remote.json`. Earlier mock results above document the initial deployment; the current deployment uses physical GPUs. Slurm remains an unimplemented stub.

## Admin deletion and editor defaults refinement

- Added admin-only deletion APIs/UI for accounts, workspace data, Docker images, environment templates, debug records and training records. Member requests return 403, anonymous requests return 401. Members retain stop/cancel actions.
- Active debug/training records and workspace data used by active workloads return 409. User deletion requires a disabled, idle account; deleting the signed-in administrator returns 422. Referenced/default images and referenced templates return 409.
- Workspace deletion removes code, Python volume and cache while retaining results/history/shared datasets. User deletion removes its private resources while retaining audit events. Record deletion retains workspace/result files. Docker image removal never forces or prunes other images.
- All 42 backend tests passed, including deletion permission coverage and symlink/shared-data protection.
- All seven disposable admin deletion acceptance checks passed, including successful admin deletion, member denial, active/reference protection, result retention, workspace recreation, revoked deleted-user sessions and retained audit history. Report: `runtime/logs/acceptance-admin-deletion.json`.
- Refreshed lab images include `ms-python.python` 2026.4.0, debugpy and Python Environments extensions. Editor settings select `/opt/user-env/venv/bin/python`; Bash terminals activate the persistent venv. JSONC preferences were preserved across editor restart while resetting the interpreter default.
- Refreshed PyTorch image: `sha256:543e69cff7bf19bad597a1c5441eaa7789cb09e8098b80ac5149d1e5f64d3c3c`. Recommended template ID: `7adccbf2-634b-4f53-b65d-792c0eb72bd7`, version `2.7.1-cu128-editor`. New accounts default to this available template.
- A fresh workspace imported PyTorch 2.7.1+cu128 through its default shell Python. A one-GPU, 14400-second debug session used the same interpreter and passed physical RTX 5060 Ti CUDA matrix multiplication.
- All enabled accounts (`admin`, `chenlin`, `changxu`) now use the refreshed PyTorch template and successfully import torch through their default shell Python. Previous Python 3.10 venvs are retained in their existing Python volumes under `venv-backup-1791276882967573167`, `venv-backup-1791277089101502641` and `venv-backup-1791277097247966514`, respectively. Student workspace states were restored after verification. Disabled historical test accounts retain their previous pinned templates.
- After deployment, both real GPU scheduler acceptance checks and all seven public HTTPS/editor/WebSocket checks passed. The tunnel hostname was retained through the application update.
- Browser plugin setup failed in this environment; direct visual UI inspection was unavailable. Frontend TypeScript/Vite production build, API integration, authenticated editor HTTP and WSS checks passed.

## Live GPUs, selected cards and long-debug approvals

- Applied additive Alembic revision `0002`; existing task data was retained and account debug limits raised to ten hours. Database backup: `runtime/logs/db-before-gpu-features-20261006T125548Z.sql` (mode 0600).
- Deployed a healthy NVIDIA utility monitor sampling every three seconds. The overview exposes physical model/UUID/PCI/driver, utilization, memory, temperature, power limits, fan and clocks with a sample timestamp. Stale/unavailable readings are explicitly marked; real GPU allocation waits for valid monitoring.
- NVML process queries require host PID visibility. The initial isolated PID namespace returned no host compute processes despite valid hardware counters. A host-PID query reproduced and resolved this difference. After dropping capabilities, root could no longer write the host-user-owned logs directory; running the monitor as host UID/GID resolved it. The final service drops all capabilities, uses no-new-privileges and a read-only root filesystem, has no Docker socket, and is healthy.
- GPU 0 and GPU 3 are used by external processes (host PIDs 2152417 and 3898446 at verification). The monitor detects them and the scheduler waits rather than using those cards. Their original processes remained running throughout deployment/verification.
- Debug and training store optional selected card indices and honor those physical UUIDs. A selected occupied card waits for that exact card. Retry preserves the selection; auto allocation uses eligible free cards.
- Ten hours can start directly. Longer debug requests, up to seven days, require a reason and durable admin approval. Waiting requests have no allocation/container and no FIFO position. Approval enters FIFO at approval time; rejection and withdrawal retain history. Current GPU quota, enabled account and template permissions are revalidated.
- All 54 backend tests passed. Frontend TypeScript/Vite production builds passed.
- All seven selected-GPU/approval acceptance checks passed, including selected-card CUDA computation, training waiting/release, ten-hour and eleven-hour expiry calculations, approval/403/duplicate decision boundaries, rejection/withdrawal and audit. Disposable accounts/jobs were removed. Report: `runtime/logs/acceptance-gpu-features.json`.
- Real GPU scheduler acceptance passed both checks; admin deletion acceptance passed all seven; public HTTPS/editor/WebSocket acceptance passed all seven. Public `/api/resources/gpus` was verified to refresh its sample timestamp and expose hardware values for all four cards. Both currently enabled accounts (`admin`, `yinshengwang`) have ten-hour limits. No test workloads remain, and the monitor runs healthy as UID/GID 1000. The Cloudflare hostname remained `https://basement-solomon-prefer-lat.trycloudflare.com`.
