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
3. Select the **CUDA 12.8 · nvcc · PyTorch 2.7.1** fixed environment, set **GPU 上限** to **1**, and **Debug 免审批上限** to **10 小时**.
4. Click **创建用户**, then **复制登录信息** and give the login details to the student.
5. The student logs in through the public link, opens **在线调试**, chooses automatic allocation or **指定显卡**, checks one GPU, and enters the duration in hours. For ten hours or less, click **开启调试**. Wait for **运行中**, then open **VS Code ↗**.

Training also supports automatic allocation, selecting multiple cards up to the user's quota, or CPU-only mode. Selections are persisted and reused by retries. API requests use `gpu_indices`, e.g. `requested_gpus=1, gpu_indices=[2]`; omit or send `null` for automatic allocation. A requested card is never silently substituted. Physical GPU indices correspond to the dashboard; a one-GPU container sees its assigned GPU as CUDA device 0.

For debug beyond ten hours (up to seven days), enter a reason and click **提交审批申请**. The session stays **等待管理员审批**, occupies no GPU/container and does not block the running queue. An administrator opens **在线调试**, reviews the duration/card/reason and clicks **批准** or **拒绝**, optionally recording a note. Only approval enters the FIFO, ordered by approval time. Students can **撤回申请** before launch. Each request needs its own approval; approval is not a reusable account entitlement. The duration starts when the container starts. Expiry or **停止** releases the GPU; closing the browser does not cancel the session. For PyTorch work, choose at least 4096 MB of RAM.

The migration raises current account limits to ten hours. Administrators may set a smaller per-account limit for short sessions; requesting more than ten hours still requires explicit approval.

In the debug VS Code terminal:

```bash
nvcc --version
nvidia-smi
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available()); print(torch.cuda.get_device_name(0)); print((torch.ones(2, device='cuda') + 1).cpu())"
```

See [public access and student instructions](docs/REMOTE_ACCESS.md), [Ubuntu deployment details](docs/UBUNTU_MIGRATION.md), and [verification results](docs/UBUNTU_VALIDATION.md).
