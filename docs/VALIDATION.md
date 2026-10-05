# 本机验证记录 · 2026-10-05

测试主机：Windows Docker Desktop 4.94.0 / Linux engine 29.8.2；NVIDIA RTX 3060 12 GB。

基础镜像：用户指定的 `sha256:17e2934e1fa96152b14f78078bfbafd0f00f391df995dc6c641a720fce1202bb`。没有拉取新的基础镜像。数据集：`D:/Datasets/RaDIaL/Ready_to_use`，只读。

已通过：

- 前端 TypeScript 检查和生产构建；npm 锁文件审计 0 vulnerabilities。
- 18 项 Python 单元测试，包含 workdir 逃逸、保留环境变量、资源限制、存储挂载契约和 GPU first-fit。
- 11 组真实 HTTP + PostgreSQL + Docker 验收：登录/用户创建、ForwardAuth、无 GPU/无 socket/非 privileged 边界、只读数据集、文件与 pip rich 跨容器重建、用户 venv 隔离、环境变量优先级/secret 遮蔽、训练日志/结果、重试、2+2+1 GPU 队列、后端/worker 重启不重复启动、取消/失败/超时/Debug TTL、最终资源释放/存储/审计。
- local-gpu-docker 的真实训练：Docker DeviceRequest，nvidia-smi 能识别 RTX 3060，libcudart 成功分配并释放显存，日志出现 REAL_GPU_OK。
- 浏览器中成功登录成员 Portal，看到 GPU/队列页面，启动 CPU 工作区并加载浏览器 VS Code。首次目录信任提示保留给用户处理。
- 重启 PostgreSQL 后账号与训练记录保留，日常 `up.ps1 -NoBuild` 能正常运行；最终恢复 mock-docker、5 个 FREE GPU、worker 在线。
- 实际 Training 任务从 D 盘数据集文件读取 4096 字节，日志显示 DATASET_READ_OK；未修改数据集。
- 最终验证 HTTP-only/SameSite cookie、HTTPS Origin 下 Secure cookie 和跨站写请求拒绝。

详细机器报告保存于 `runtime/logs/acceptance.json` 与 `runtime/logs/acceptance-gpu.json`，这些包含本机运行数据，不提交到 Git。

追加远程/学生 GPU 验证：

- 按用户请求启用 Cloudflare Quick Tunnel，公网 HTTPS Portal 和健康检查通过。
- 7 组真实公网验收通过：Secure/HttpOnly/SameSite cookie、成员权限、匿名及跨用户工作区拒绝、跨站写拒绝、工作区 HTTP、经过 Cloudflare 的认证 WSS 升级与 ping/pong、匿名 WSS 拒绝、密码修改及旧会话注销、公网训练提交/日志/结果/审计。临时验收成员均已停用。报告：`runtime/logs/acceptance-remote.json`。
- 创建 `student_gpu` MEMBER 账号，绑定新版 CUDA 编译环境，分配 RTX 3060 的 GPU 0、2 CPU、4 GB RAM 和 4 小时 Debug，保持会话运行供用户使用。
- 以学生 Linux 用户运行 nvidia-smi、nvcc 12.8.93、code-server 4.140.0；nvcc 编译实际 CUDA 内核并在 RTX 3060 上执行，输出 `CUDA_KERNEL_OK ... result=42`。源代码及结果位于该用户 `/workspace/gpu_smoke.cu` 和 `GPU_VALIDATION.txt`；报告：`runtime/logs/student-gpu-validation.json`。
- 浏览器从公网 URL 登录 student_gpu，Portal 显示 LOCAL GPU MODE、GPU 0 已分配、调试会话运行中；打开公网 VS Code 并查看 GPU 验证结果。文件目录信任保留给用户自己决定。
- 基础镜像增加 cuda-nvcc-12-8 和开发头文件，下载 NVIDIA 官方软件包，没有拉取新的基础镜像。
- 新模板为镜像添加独立 `lab-env-<id>:pinned` 保留标签，避免重建开发标签后旧 manifest 丢失。界面标识本机缺失镜像，并避免为新账号默认选择缺失环境。初版旧模板的镜像已丢失，已有管理员默认模板没有自动迁移；管理员可在「用户管理」编辑对应账号，选择新版环境后保存（Python ABI 同为 3.10）。

尚未验证：另一台物理设备的网络连通性、未来 Slurm 集成、PyTorch 训练。公网测试已经实际经过 Cloudflare，但无法代替用户手机/远程网络的连通性测试。

登录输入修复：21 项单元测试通过（新增用户名大小写/粘贴空格兼容，密码原样保留）；TypeScript 检查和生产构建通过。原账号密码通过实际公网 HTTP 登录、会话验证与浏览器重新登录，空格及大写用户名也通过；学生 GPU 容器与会话 ID 保持不变。失败设备的实际输入仍待确认，未将输入问题认定为已确认根因。
