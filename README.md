# GPU Lab · Windows Docker POC

基于本机已有 CUDA 镜像的实验室 cluster 框架：React Portal、FastAPI、PostgreSQL/Alembic、Traefik、独立调度 worker，以及动态 Workspace / Debug / Training 容器。

```powershell
cd D:\Projects\lab-cluster-system
.\scripts\bootstrap.ps1
.\scripts\up.ps1
```

访问 **http://localhost:8080**。管理员用户名 `admin`，首次生成的密码在本地 `.env` 的 `INITIAL_ADMIN_PASSWORD` 中。不会把密码打印到日志或提交到 Git。初始管理员只创建一次；修改 `.env` 不会重置已有账号的密码。

本机无需安装 Python、Node 或数据库。首次构建会下载 apt/pip/npm 软件包及 code-server/Traefik 二进制，**不拉取新的基础镜像**。使用指定的 `sha256:17e2934e1fa96152b14f78078bfbafd0f00f391df995dc6c641a720fce1202bb`，前端构建工具复用本机已有 `radarannotationtoolkit-web` 镜像。

测试外部 D 盘数据集：

```powershell
.\scripts\bootstrap.ps1 -DatasetPath 'D:\Datasets\RaDIaL\Ready_to_use'
.\scripts\up.ps1 -NoBuild
```

所有新建用户容器将它挂载到 `/datasets`，只读共享。更换路径后需重新创建已有 Workspace / Debug / Training 容器。默认不传路径则使用 `runtime/datasets/demo/hello.txt`。

自动验收：

```powershell
.\scripts\acceptance-test.ps1
```

验收要求 mock 模式且没有其他活跃任务，会创建独立测试账号、验证持久化环境/权限/排队/日志/结果/重启恢复/TTL，然后停止测试工作区并停用测试账号。测试数据和报告保留在 `runtime/`，不会修改其他账号的文件。

真实 GPU 测试：

```powershell
.\scripts\gpu-test.ps1
.\scripts\set-scheduler.ps1 -Mode local-gpu-docker
.\scripts\acceptance-test.ps1 -Gpu
.\scripts\set-scheduler.ps1 -Mode mock-docker
```

切换前须结束所有训练和调试任务。本机 RTX 3060 对应 `LOCAL_GPU_COUNT=1`；mock 默认 5 个虚拟 GPU，执行真实 Docker 任务但不透传 GPU。Workspace 永远只使用 CPU。基础镜像包含 nvcc 12.8 编译器，尚未安装 PyTorch；GPU 验收使用 CUDA API 或编译 CUDA 内核，避免额外下载 PyTorch。

日常操作：

```powershell
.\scripts\up.ps1 -NoBuild          # 已构建后快速启动
.\scripts\logs.ps1                 # 查看后端/调度器/路由日志
.\scripts\down.ps1                 # 停服务，保留数据库、文件与 Python volume
.\scripts\remote-access.ps1 -Action Start  # 启动公网 Quick Tunnel，不重复构建
.\scripts\remote-access.ps1                # 查看当前公网地址及健康状态
.\scripts\remote-access.ps1 -Action Stop   # 仅关闭公网入口
```

`down.ps1` 也停止本项目动态容器；运行中的训练在下次启动时按容器退出状态收尾。需要完整清空开发数据时才使用 `reset-dev.ps1`，默认要求输入 `RESET`。该脚本只清除本项目 runtime 和带本项目标签的资源，不删除外部数据集。

详细的浏览器手动测试见 [docs/WINDOWS_POC.md](docs/WINDOWS_POC.md)，架构和差异见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)、[docs/IMPLEMENTATION_NOTES.md](docs/IMPLEMENTATION_NOTES.md)。

本机测试结果见 [docs/VALIDATION.md](docs/VALIDATION.md)。

跨网络登录、分配成员账号、VS Code 点击步骤与真实 GPU 切换见 [docs/REMOTE_ACCESS.md](docs/REMOTE_ACCESS.md)。新账号创建后可以直接复制登录信息；成员可在「我的账号」修改初始密码。
