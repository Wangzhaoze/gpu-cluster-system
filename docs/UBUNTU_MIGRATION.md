# Ubuntu / Slurm 迁移边界

1. 保留前端、HTTP API、账号/权限、PostgreSQL 状态机、环境模板、工作区、Debug/Training 生命周期与日志/结果。
2. 将配置中的宿主 runtime 路径改为 Linux 绝对路径。新增 LinuxStorageProvider，可将 pyenv 替换为 `/srv/lab/home/<user>/python-env` bind mount。
3. 构建固定 Python/CUDA/PyTorch 版本的镜像；保持 LAB_USERNAME/LAB_UID/LAB_GID、入口脚本与持久化 venv 契约。
4. 实现 SchedulerBackend 对应的 Slurm 后端。当前 `SlurmScheduler` 仅是显式 stub，不能在 Windows 配置中启用。
5. JobSpec 仍使用 GPU/CPU/RAM/时间/命令/workdir/env 等通用字段，前端不依赖 Docker 设备分配细节。
6. 真实遥测由未来 DCGM/Prometheus 提供，mock cards 目前只表达独占分配，不表达显存或 GPU 利用率。

更换 Python ABI 需要显式备份/重建 venv，并在管理员批准后重新绑定镜像；不要自动升级学生环境。
