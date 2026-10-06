# 实现范围与计划差异

本次交付基本框架和主要本机链路：认证/用户管理、持久化文件与 venv、code-server、训练/调试共享队列、取消/重试/TTL、日志/结果、权限、环境模板/变量、存储展示、审计、重启恢复、mock 与单机真实 GPU 两种模式。

- Ubuntu bootstrap 会下载缺失的 CUDA 和 Node 基础镜像。PostgreSQL/Traefik 服务复用 CUDA 层；前端使用 Node 构建。可选 PyTorch devel 镜像包含 CUDA 12.8、nvcc 与 PyTorch 2.7.1，并派生为支持 code-server 的独立学生环境。构建完成后运行无需下载依赖。
- PostgreSQL 使用 Ubuntu 提供的 14.x，code-server 4.140.0，Traefik 3.7.13；Python/npm 依赖固定版本，前端使用 lockfile。apt 包版本跟随 Ubuntu 安全更新，未做完整 apt 快照。
- 训练与调试合并为 `workloads` 表，kind 区分；全局/每用户变量合并为带 scope 的 `environment_variables` 表。语义与权限保持计划边界，避免重复的状态机。
- React/TypeScript/Vite 使用轻量 state 和轮询，暂不引入 React Router/TanStack Query；单页内部导航不影响 Traefik 的路径路由。
- code-server 使用相对资源 URL，Traefik StripPrefix；`--abs-proxy-base-path` 负责应用端口绝对代理的前缀。这不是 code-server 全局 `--base-path` 参数。ForwardAuth 在去除前缀前校验。
- 初始环境模板保存本地镜像内容 ID，避免 tag 被重建后已有用户静默升级。新版本需添加模板并显式分配；不自动重建用户 venv。
- 工作负载入口初始化 venv 时使用 flock，支持同用户多个容器同时首次启动。代码和扩展持久化；Workspace/Debug 分开 code-server user-data 目录，避免同时写同一个编辑器状态库。
- 轻量实验室模板包含 CUDA/Python/code-server；PyTorch 模板额外包含 torch、cuDNN 与 nvcc。真实 GPU 验收包含 CUDA 显存分配、nvcc 编译内核以及 PyTorch CUDA 张量计算。
- 存储展示统计 workspace/results/scratch 文件，不统计 named venv volume、不设置硬配额。GPU 实时利用率、Docker CPU/RAM 指标、监控 profile 留待后续。
- Secret 环境变量普通响应遮蔽，但数据库当前保存明文值；基础 POC 未增加 KMS。用户自己在程序中打印密钥仍会进入其任务日志。
- 基础框架为可信实验室成员使用，容器内 sudo 会允许修改容器系统。Docker API 仅在基础服务可用。`:ro` socket bind 并不是只读 Docker API，本阶段未引入 socket-proxy。
- Quick Tunnel profile 和 URL 检测已实现。`./scripts/lab.sh remote-test` 自动验证公网 HTTPS、账号权限、编辑器与 WebSocket；临时地址在隧道重启后更换。
- 停用用户会撤销登录、删除其工作区，worker 取消其未完成任务。账号/数据不自动删除，避免误清理结果。
- 默认 GPU 总量限制并发 GPU，CPU/RAM 是单容器限制，尚未实现集群总 CPU/RAM 配额与排队策略。
- PostgreSQL 初始化使用 UTF8/C.UTF-8。Ubuntu 部署保留数据库、用户文件及 Python named volumes，停止服务不删除持久化数据。
- VS Code 首次工作目录保留其默认信任提示，由用户对自己可信的目录选择信任后使用完整终端/调试功能。
- 共享 Docker network 下的 ForwardAuth 保护浏览器入口；容器内部网络不是恶意租户隔离边界。此 POC 适用于可信实验室成员，后续若要抵御成员间的主动网络访问，需要增加网络隔离或后端认证。

官方参考：[code-server 反向代理说明](https://github.com/coder/code-server/blob/main/docs/guide.md)、[Traefik ForwardAuth](https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/forwardauth/)。
