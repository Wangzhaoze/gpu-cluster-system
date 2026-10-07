# GPU Lab on Ubuntu

A single-host Ubuntu Docker service for student workspaces, queued training and GPU debug sessions, with persistent files, Python environments and results.

## Deploy

Requirements: Ubuntu x86_64, Docker Engine with Compose, Bash, Python 3 and network access for the first build. Reserve at least 30 GB of disk space, plus space for the optional PyTorch development image.

```bash
./scripts/lab.sh bootstrap
./scripts/lab.sh up --remote
```

Open the printed public `https://….trycloudflare.com` link, or `http://localhost:8080` on this PC. Log in as `admin` with `INITIAL_ADMIN_PASSWORD` from the private `.env` file. Bootstrap preserves existing passwords and data. The public link changes when the tunnel restarts; this PC and Docker must remain running.

```bash
./scripts/lab.sh remote-url          # Current public URL
./scripts/lab.sh remote-test         # Public HTTPS/editor/WebSocket acceptance
./scripts/lab.sh status
./scripts/lab.sh logs backend
./scripts/lab.sh down                # Stop services/workloads; preserve data
./scripts/lab.sh up --remote --no-build
```

Supply datasets with `./scripts/lab.sh bootstrap --dataset-path /absolute/datasets` before startup. Containers see them read-only at `/datasets`. User files/results live under `runtime/`; Python environments and PostgreSQL use persistent Docker volumes.

## Enable real RTX 5060 Ti GPUs

The host has four RTX 5060 Ti GPUs. NVIDIA drivers and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) are required. The setup script installs the toolkit and restarts Docker; run it when workloads can be interrupted.

```bash
sudo ./scripts/setup-nvidia.sh
./scripts/lab.sh gpu-test
./scripts/lab.sh set-scheduler local-gpu-docker
./scripts/lab.sh test --gpu
```

Set `LOCAL_GPU_COUNT=4` in `.env` for this PC. Finish/cancel active workloads before switching. `LOCAL GPU MODE` in the portal means real GPU scheduling; `MOCK GPU MODE` means simulated slots. CPU workspaces do not receive GPUs. Slurm is not implemented.

## CUDA, nvcc and PyTorch image

```bash
./scripts/lab.sh torch-image
./scripts/lab.sh torch-test
```

`torch-image` pulls the official `pytorch/pytorch:2.7.1-cuda12.8-cudnn9-devel` and builds `lab-torch-dev:2.7.1-cu128` with code-server and persistent student venv support. `torch-test` compiles/runs a CUDA kernel and executes PyTorch matrix multiplication on all visible GPUs. [PyTorch 2.7 supports Blackwell with CUDA 12.8](https://pytorch.org/blog/pytorch-2-7/).

After building the PyTorch image, restart the backend to register its immutable template automatically. The available template matching `LAB_TORCH_IMAGE` is marked **新用户默认 · PyTorch** and selected for new accounts. On this deployed PC, use **CUDA 12.8 · nvcc · PyTorch 2.7.1**, version `2.7.1-cu128-editor`. Existing accounts keep their assigned template unless an administrator changes it while idle. A Python ABI change keeps the previous venv under `/opt/user-env/venv-backup-*` and creates a fresh compatible venv; old packages are not automatically reinstalled.

VS Code includes the Python extension. Its default interpreter is `/opt/user-env/venv/bin/python`, and new terminals activate that environment. The PyTorch template inherits PyTorch 2.7.1+cu128 from the image. Workspace sessions use CPU; CUDA becomes available when a GPU is allocated to debug or training. Interpreter setup follows the [VS Code Python settings](https://code.visualstudio.com/docs/python/settings-reference) and [code-server extension installation](https://coder.com/docs/code-server/FAQ).

## Administrator deletion

Only administrators see deletion controls, and the API enforces the same permission. Members may stop their workspace/debug session or cancel training while retaining their files and history.

- **用户管理 → 删除用户:** first disable the account and finish/cancel its workloads. Deletes its account, private workspace/results/cache, Python volume and workload records; retains the audit trail. The signed-in administrator cannot delete their own account.
- **删除工作区:** clears workspace files, Python volume and cache; retains the account, training results and task history. Stop all debug/training workloads first. The workspace can be started again with a fresh environment.
- **训练任务 / 在线调试 → 删除记录:** only finished/stopped records can be deleted. Removes the record and log, retaining workspace and result files.
- **环境模板 → 删除模板 / Docker 镜像 → 删除镜像:** templates still referenced by users or task records are protected. Images used by any container/template, or configured as cluster defaults, cannot be deleted. Image deletion removes all its tags without forcing removal or pruning other images.

Deletion prompts describe the affected data and require confirmation. Acceptance: `sg docker -c 'docker compose exec -T backend python3 integration/admin_deletion.py'` creates and deletes only disposable test resources; report is saved in `runtime/logs/acceptance-admin-deletion.json`.

## GPU monitoring, card selection and ten-hour debug

The overview shows all four GPU models, utilization, memory, temperature, power, fan speed, clocks, driver version, PCI address and UUID. `gpu-monitor` samples NVIDIA utility counters every three seconds. The page distinguishes platform allocation from external compute processes; unavailable/stale measurements display a message and dashes. Automatic allocation skips cards with external compute processes. A selected busy card waits until it is free. If real telemetry is unavailable, GPU jobs wait for monitoring to recover.

The monitor starts automatically with `./scripts/lab.sh up --remote --no-build` in real GPU mode. It uses the `gpu` Compose profile, host PID visibility for NVML process enumeration, the host user's UID/GID for writing snapshots, dropped capabilities and a read-only root filesystem. It has no Docker socket. To check it: `sg docker -c 'docker compose --profile gpu logs --tail 30 gpu-monitor'`.

1. Log in as administrator and open **用户管理**.
2. Enter a username such as `student01`, display name and a generated password. Select role **成员**.
3. Select the **CUDA 12.8 · nvcc · PyTorch 2.7.1** fixed environment, set **GPU 上限** to **1** for single-card use or **2/3** for multiple cards, and **Debug 免审批上限** to **10 小时**.
4. Click **创建用户**, then **复制登录信息** and give the login details to the student.
5. The student logs in through the public link, opens **在线调试**, chooses automatic allocation or **指定显卡**, checks one or more free GPUs within the account quota, and enters the duration in hours. For ten hours or less, click **开启调试**. Wait for **运行中**, then open **VS Code ↗**.

Both debug and training support automatic allocation, selecting one or multiple cards up to the user's quota and the cluster size, or CPU-only mode. Platform-occupied and externally occupied cards are grey and disabled in the selector. Polling removes a selected card if it becomes occupied; submitting an empty manual selection is rejected. Administrator workload edits use the owner's quota. If a card becomes busy after submission, the scheduler retains the request and waits without substituting a card. Selections are persisted and reused by retries. API requests use `gpu_indices`, e.g. `requested_gpus=1, gpu_indices=[2]`; omit or send `null` for automatic allocation. A requested card is never silently substituted. Physical GPU indices correspond to the dashboard; assigned GPUs appear inside a container as consecutive CUDA devices starting at 0.

For debug beyond ten hours (up to seven days), enter a reason and click **提交审批申请**. The session stays **等待管理员审批**, occupies no GPU/container and does not block the running queue. An administrator opens **在线调试**, reviews the duration/card/reason and clicks **批准** or **拒绝**, optionally recording a note. Only approval enters the FIFO, ordered by approval time. Students can **撤回申请** before launch. Each request needs its own approval; approval is not a reusable account entitlement. The duration starts when the container starts. Expiry or **停止** releases the GPU; closing the browser does not cancel the session. For PyTorch work, choose at least 4096 MB of RAM.

The migration raises current account limits to ten hours. Administrators may set a smaller per-account limit for short sessions; requesting more than ten hours still requires explicit approval.

In the debug VS Code terminal:

```bash
nvcc --version
nvidia-smi
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available()); print(torch.cuda.get_device_name(0)); print((torch.ones(2, device='cuda') + 1).cpu())"
```

See [public access and student instructions](docs/REMOTE_ACCESS.md), [Ubuntu deployment details](docs/UBUNTU_MIGRATION.md), and [verification results](docs/UBUNTU_VALIDATION.md).

## Administrator workspace host addresses

Members see their container workspace controls without Ubuntu host paths. Administrators find each member's absolute workspace path in **存储 → workspace 宿主机地址**, with copy and remote VS Code actions. The admin storage API exposes `workspace_host_path`; admin `/api/workspace?user_id=…` additionally exposes bind paths, UID/GID and an ownership-preserving import command. Member workspace responses omit those host details.

These directories are live Docker bind mounts: host edits and member Web VS Code edits affect the same files. When importing a project on the host, use the administrator workspace API's `sudo rsync -a --chown=UID:GID` command, substitute the source directory, and preserve the member's ownership. Open `/workspace/project` inside the member editor to continue developing with `/opt/user-env/venv/bin/python`. `/results` and `/scratch` persist too, and `/datasets` is shared read-only. The in-app Help menu explains the container directories and persistent environments.

The deployed checkout is `/home/local/gpu-cluster-system`; its private `.env` points to `/home/local/gpu-cluster-system/runtime`. Both are ignored by Git. Manage the deployment from this checkout with `./scripts/lab.sh up --remote`, `status` and `remote-url`. Retain the `gpu-lab-poc` Compose project, `gpu-lab-poc_postgres-data` database volume and `lab_pyenv_*` Python volumes. A runtime migration must pause workspace writers and backend/worker before copying data with numeric ownership, then recreate running workspaces with the new bind paths. Keep an existing Quick Tunnel running during application migration to retain its public link; restarting the Quick Tunnel creates a new link.

Run `./scripts/lab.sh workspace-test --public` from the deployed checkout to verify the host paths, file ownership, public editor access, PyTorch, project-folder training and stop/start persistence. The test uses two disposable members and a short-lived local maintenance session, then removes them; it retains existing account passwords and files. Docker access is required.

## Native administrator host VS Code

Administrators open **宿主机 → 远程 vscode** to manage the Ubuntu PC directly. The editor runs natively as the existing Linux user `local` (UID 1000), opens `/home/local`, and can access host files and Docker. Open `/home/local/gpu-cluster-system` using the editor folder menu when needed. All ADMIN portal accounts share this Linux identity and editor environment; assigning ADMIN grants access to the host. Students continue using their own container workspaces.

Install from the deployed checkout as `local` after bootstrap has prepared the base image:

```bash
./scripts/lab.sh host-editor install
./scripts/lab.sh up --remote --no-build
./scripts/lab.sh host-editor status
./scripts/lab.sh host-editor restart
./scripts/lab.sh host-test
```

The installer extracts code-server and the Python extensions from the existing base image, enables `gpu-cluster-host-editor.service` under `systemctl --user`, and records the host identity in private `.env`. On this PC, user lingering is enabled so the editor starts without an interactive login. Host settings and extensions persist under `runtime/host-editor`. The editor listens only on a private mode-600 Unix socket. The `host` Compose profile supplies an HTTP/WebSocket gateway which mounts that socket and checks the backend ADMIN session; Traefik also checks the administrator before routing `/host/`. Neither the native editor nor the gateway publishes an additional host TCP port.

Choose **Terminal → New Terminal** in VS Code. The terminal starts the host Conda `dl` environment when available; its Python interpreter on this PC is `/home/local/miniconda3/envs/dl/bin/python`, with PyTorch **2.11.0+cu128**, working CUDA and four visible GPUs. The persistent student Python environment remains `/opt/user-env/venv/bin/python` with its assigned template. Host terminal initialization uses an editor-specific Bash rc file and leaves the personal `.bashrc` intact.

```bash
pwd
id
docker ps
nvidia-smi
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.device_count())"
sudo systemctl status docker
```

System administration uses ordinary `sudo` and the Linux `local` account password, which is separate from the portal login password. The installer grants no passwordless sudo. Student workspace deletion/stop/restart actions cannot affect the native editor or `/home/local`; manage the editor using the lifecycle command above. Removing a portal administrator account revokes its portal access and deletes only its old private cluster resources, retaining the shared Linux identity and home directory.

`host-test` verifies public HTTPS/editor/WebSocket access, native host files and operating-system identity, student/anonymous denial, direct gateway authorization and host deletion protection. It uses temporary sessions for existing accounts, removes them afterward and saves `runtime/logs/acceptance-host-editor.json`, without replacing passwords or creating workloads. Run proxy tests using the Node runtime bundled in the base image:

```bash
sg docker -c 'docker run --rm --pull never --network none --mount type=bind,src=/home/local/gpu-cluster-system/infra,dst=/app/infra,readonly --mount type=bind,src=/home/local/gpu-cluster-system/tests/proxy,dst=/app/tests/proxy,readonly --workdir /app --entrypoint /usr/lib/code-server/lib/node lab-base-dev:2026.10-poc --test tests/proxy/host-editor.test.mjs'
```

## Administrator/member portal roles

Administrators use a blue theme and manage existing training/debug records: monitor, edit, cancel/stop, approve and delete. They cannot submit or retry workloads through the portal API; members use the green theme and submit experiments from their own accounts. The native host page retains its introduction, state and a single **远程 vscode** entry.

Members see all members' workload summaries and shared queue information. Their own records retain commands, logs and editor controls; other members' summaries include identity, status, GPU selection/allocation, duration and timestamps, without private commands, paths, logs, errors, environment details, approval reasons or editor URLs. Every detail/control route continues to check ownership; list visibility never grants control of another account.

Admin **编辑** accepts command/work directory/output name (training), GPU selection, CPU, RAM and total duration for pending records; waiting debug applications remain waiting for approval after editing. Running records accept total duration only, calculating the new deadline from the original start time and retaining the container. Starting, cancelling or finished records reject edits. Extending an already queued/running debug above ten hours records the administrator's authorization. Owner GPU limits and pinned templates are retained.

**环境 → 环境变量** provides name/value add, edit and delete. Administrators select global or individual member scope. Members can edit/delete their own values and read shared global values. Changes refresh across role interfaces every three seconds and apply to the next created container. Precedence remains task override, personal, global, default; deleting a personal value restores a same-name global value for future containers. The unused **密钥/启用** controls are removed; stored compatibility flags remain intact for older API clients. Variable audit events contain keys/scopes, never values.

**远程访问** contains the current link/status/copy action. The training navigation badge counts only pending training records, hides at zero, and excludes running/debug records. The last navigation item, **帮助**, collects account, editor, GPU/queue/approval, variables, storage and deletion instructions, with a compact architecture diagram. Operational pages keep controls and current state information.

Validation commands:

```bash
./scripts/lab.sh portal-test       # Disposable public API/container acceptance
./scripts/lab.sh host-test         # Native host HTTPS/WSS permissions
sg docker -c 'docker compose exec -T backend python3 -m pytest -q'
```

`portal-test` creates and removes two test members, temporary variables/workloads and a short-lived administrator session; it preserves production credentials and saves `runtime/logs/acceptance-role-portals.json`. Rendered UI checks in `tests/frontend/role_portals.py` use synthetic role data against the built frontend, including desktop/mobile layouts, theme differences, variable CRUD and polling. They require the optional Python Playwright package and its Chromium runtime; report/screenshots are saved to the selected `--output` directory.
