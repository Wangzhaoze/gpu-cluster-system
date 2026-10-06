# Ubuntu deployment and Slurm migration boundary

## Ubuntu with Docker

The existing Docker application now has a native Linux management command:

```bash
./scripts/lab.sh bootstrap [--dataset-path /absolute/dataset/directory]
./scripts/lab.sh up
```

`scripts/lab_env.py` prepares absolute Linux paths and generates secrets in `.env` with permissions `0600`. `scripts/lab.sh` downloads missing CUDA/Node base images and builds the Dockerfiles. The original lab template uses CUDA 12.8.1 and Python 3.10 on Ubuntu 22.04 inside containers; the host runs Ubuntu 24.04. The separate PyTorch development template uses the official image's interpreter via `LAB_PYTHON`, and fresh user venvs inherit its torch packages.

The same storage provider works with Linux absolute host paths. Workspaces/results/scratch remain bind mounts under `LAB_HOST_ROOT`; Python environments remain named Linux Docker volumes. No storage-provider migration or Python ABI change is needed for this deployment.

The default is `mock-docker`, with five simulated slots for acceptance. To enable the host's NVIDIA GPUs:

1. Install and configure the [NVIDIA Container Toolkit for Docker](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) on the host using `sudo ./scripts/setup-nvidia.sh`. GPU drivers alone do not enable Docker GPU passthrough. The script installs toolkit 1.20.1, backs up an existing Docker daemon configuration, configures the NVIDIA runtime and restarts Docker. Run it when host containers can be interrupted; existing NVIDIA drivers are retained.
2. Check `LOCAL_GPU_COUNT` in `.env` against `nvidia-smi -L`.
3. Run `./scripts/lab.sh gpu-test`.
4. Finish/cancel any active jobs, then run `./scripts/lab.sh set-scheduler local-gpu-docker`.
5. Run `./scripts/lab.sh test --gpu` to verify a scheduled job can allocate and free CUDA device memory.

The CPU workspace does not request physical GPUs. Run `./scripts/lab.sh torch-image` to build the preinstalled PyTorch template and `./scripts/lab.sh torch-test` to check CUDA compilation and tensor operations. Backend startup registers the built image as a separate template and recommends it for new students. Existing accounts keep their pinned environment. An explicit administrator reassignment across Python ABIs backs up the previous venv inside the Python volume and initializes a compatible environment. The Python extension and default interpreter settings are supplied by the lab images.

`./scripts/lab.sh test` runs backend contracts plus HTTP/PostgreSQL/Docker acceptance, including persistence, routing, ownership checks, queue allocation, cancellation, debug expiry and restart recovery. It creates its own test accounts, disables them afterward and records its report in `runtime/logs/acceptance.json`. It requires an idle mock-mode deployment with five slots.

`./scripts/lab.sh down` stops only this project's dynamic workloads and Compose services. It retains user directories, Python volumes and database storage. `./scripts/lab.sh up --no-build` starts services again. Public access is optional through `./scripts/lab.sh up --remote --no-build`; otherwise the portal is available only at `http://localhost:8080` on the host.

## Future Slurm migration

1. 保留前端、HTTP API、账号/权限、PostgreSQL 状态机、环境模板、工作区、Debug/Training 生命周期与日志/结果。
2. 将配置中的宿主 runtime 路径改为 Linux 绝对路径。新增 LinuxStorageProvider，可将 pyenv 替换为 `/srv/lab/home/<user>/python-env` bind mount。
3. 构建固定 Python/CUDA/PyTorch 版本的镜像；保持 LAB_USERNAME/LAB_UID/LAB_GID、入口脚本与持久化 venv 契约。
4. 实现 SchedulerBackend 对应的 Slurm 后端。当前 `SlurmScheduler` 仅是显式 stub，不能启用。
5. JobSpec 仍使用 GPU/CPU/RAM/时间/命令/workdir/env 等通用字段，前端不依赖 Docker 设备分配细节。
6. 真实遥测由未来 DCGM/Prometheus 提供，mock cards 目前只表达独占分配，不表达显存或 GPU 利用率。

更换 Python ABI 需要显式备份/重建 venv，并在管理员批准后重新绑定镜像；不要自动升级学生环境。
