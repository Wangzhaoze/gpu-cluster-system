# 实现范围与计划差异

本次交付基本框架和主要本机链路：认证/用户管理、持久化文件与 venv、code-server、训练/调试共享队列、取消/重试/TTL、日志/结果、权限、环境模板/变量、存储展示、审计、重启恢复、mock 与单机真实 GPU 两种模式。

- 不下载新的 Docker 基础镜像。所需 PostgreSQL/Traefik 服务基于用户指定的本地 CUDA image 构建；前端 Node 工具来自已有本地 web image。这样基础层较大，但共享同一个 CUDA 层。本机软件包下载仍需网络，构建完成后运行无需下载依赖。
- PostgreSQL 使用 Ubuntu 提供的 14.x，code-server 4.140.0，Traefik 3.7.13；Python/npm 依赖固定版本，前端使用 lockfile。apt 包版本跟随 Ubuntu 安全更新，未做完整 apt 快照。
- 训练与调试合并为 `workloads` 表，kind 区分；全局/每用户变量合并为带 scope 的 `environment_variables` 表。语义与权限保持计划边界，避免重复的状态机。
- React/TypeScript/Vite 使用轻量 state 和轮询，暂不引入 React Router/TanStack Query；单页内部导航不影响 Traefik 的路径路由。
- code-server 使用相对资源 URL，Traefik StripPrefix；`--abs-proxy-base-path` 负责应用端口绝对代理的前缀。这不是 code-server 全局 `--base-path` 参数。ForwardAuth 在去除前缀前校验。
- 初始环境模板保存本地镜像内容 ID，避免 tag 被重建后已有用户静默升级。新版本需添加模板并显式分配；不自动重建用户 venv。
- 工作负载入口初始化 venv 时使用 flock，支持同用户多个容器同时首次启动。代码和扩展持久化；Workspace/Debug 分开 code-server user-data 目录，避免同时写同一个编辑器状态库。
- 基础镜像包含 CUDA/Python/code-server，不包含 PyTorch。真实 GPU 验收用 libcudart 分配/释放显存，不需要下载大型 torch 包。
- 存储展示统计 workspace/results/scratch 文件，不统计 named venv volume、不设置硬配额。GPU 实时利用率、Docker CPU/RAM 指标、监控 profile 留待后续。
- Secret 环境变量普通响应遮蔽，但数据库当前保存明文值；基础 POC 未增加 KMS。用户自己在程序中打印密钥仍会进入其任务日志。
- 基础框架为可信实验室成员使用，容器内 sudo 会允许修改容器系统。Docker API 仅在基础服务可用。`:ro` socket bind 并不是只读 Docker API，本阶段未引入 socket-proxy。
- Quick Tunnel profile 和 URL 检测已实现，本机基础验收不自动启动公网入口；外网及远程 WebSocket 需要单独人工验收，不能据此宣称计划中的全部 21 项最终验收完成。
- 停用用户会撤销登录、删除其工作区，worker 取消其未完成任务。账号/数据不自动删除，避免误清理结果。
- 默认 GPU 总量限制并发 GPU，CPU/RAM 是单容器限制，尚未实现集群总 CPU/RAM 配额与排队策略。
- 本机首轮初始化的空数据库使用了 SQL_ASCII，初始化脚本已修正为 UTF8/C.UTF-8。为保留原卷，本机 `.env` 使用同卷中新增的 `gpu_lab_utf8`；新安装使用 `.env.example` 的 `gpu_lab`，会直接初始化成 UTF-8。
- VS Code 首次工作目录保留其默认信任提示，由用户对自己可信的目录选择信任后使用完整终端/调试功能。
- 共享 Docker network 下的 ForwardAuth 保护浏览器入口；容器内部网络不是恶意租户隔离边界。此 POC 适用于可信实验室成员，后续若要抵御成员间的主动网络访问，需要增加网络隔离或后端认证。

官方参考：[code-server 反向代理说明](https://github.com/coder/code-server/blob/main/docs/guide.md)、[Traefik ForwardAuth](https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/forwardauth/)。
