# 架构

```
浏览器 → Traefik :8080 → React 静态 Portal
                     → /api/ → FastAPI → PostgreSQL
                     → /workspace/<user>/ → ForwardAuth → code-server
                     → /debug/<uuid>/ → ForwardAuth → code-server

PostgreSQL ← scheduler-worker → DockerRuntime → 临时 Training / Debug
                     FastAPI → DockerRuntime → CPU Workspace
```

只有 Traefik 绑定宿主机 `127.0.0.1:8080`。动态容器加入 `lab-net`，没有宿主机端口、Docker socket 或 privileged 权限。ForwardAuth 在 StripPrefix 前执行，依据完整原始 URI 校验账号所有权。会话 token 只以 HMAC 哈希存入数据库，密码使用 Argon2；HTTPS 会话自动使用 Secure cookie。写请求拒绝跨站 Origin。

`DockerStorage` 决定 Ubuntu 宿主路径和挂载：宿主文件系统保存 workspace/results/scratch，named volume 保存每用户 `/opt/user-env/venv`，数据集统一只读挂载。入口脚本使用文件锁初始化 `uv venv --system-site-packages --seed`，然后以独立 Linux 用户启动工作负载；容器内 sudo 不影响宿主机。

`SchedulerBackend` 包含提交训练、提交调试、取消、查询状态和资源。API 只提交持久化记录，单独 worker 执行调度。MockDockerScheduler 与 LocalGpuDockerScheduler 使用同一全局 FIFO、独占 GPU 和每用户并发 GPU 上限；自动选择使用 first-fit，手动选择必须等指定显卡全部空闲。真实模式依赖 3 秒采样的 NVIDIA 监控，避开有外部计算进程的空闲卡；监控过期则等待恢复。严格 FIFO 不做回填，队首资源不足会等待。

超过 10 小时的 Debug 进入 `AWAITING_APPROVAL`，不预留显卡、不创建容器、不阻塞队列。管理员批准后进入 `PENDING`，按审批时间进入 FIFO；拒绝为 `REJECTED`，用户可撤回为 `CANCELLED`。每次申请独立审批，启动前再次检查审批状态。新增字段由 Alembic `0002` 增量迁移保存显卡选择、申请理由、审批意见、审批人及时间；原有任务保留。

worker 使用 PostgreSQL session advisory lock 防止多实例重复调度，GPU 预留和 STARTING 状态先提交，再创建确定名称的容器。重启会检查数据库及 Docker 标签，恢复 STARTING/RUNNING、修正空闲槽位并清理终态容器。训练和调试共享 workload 表，使用 kind 区分，方便实现同一个 FIFO。取消由 worker 收尾，以避免 API 与调度器同时释放资源。

运行日志每秒保存到 `runtime/logs/jobs/<id>.log`，完整结束日志保存成功后才提交终态并删除容器。API 最多返回最后 256 KiB。结果保存到 `/results/<output_name>/<job_id>`，由 `$LAB_RESULT_DIR` 提供，程序需主动写入此目录。

镜像模板保存 Docker immutable image ID；用户名映射到固定模板。全局/用户/任务环境变量按优先级合并，系统生命周期相关变量不可覆盖；secret 值在普通接口中遮蔽。环境变量变化只作用于新建容器。

SlurmScheduler 当前明确报 NotImplementedError，未安装任何 Slurm/Kubernetes 组件。
