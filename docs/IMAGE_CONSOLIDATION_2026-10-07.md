# 学生镜像迁移与实际清理结果（2026-10-07）

## 当前结果

chenlinlang 已使用与 yinshengwang、yuanxinli 一致的 `3216ed3c5fa8…` 基础镜像。迁移保留原项目/results/scratch 路径、个人 Python/state 卷、UID 和账号信息，并同步应用旧镜像所需的启动权限修复。

随后用户自行删除重复 PyTorch 模板、已停用 Python 3.10 模板及部分镜像，并将清理范围限定为不影响学生使用的旧镜像和容器。本次清理未删除任何持久卷、代码目录、历史任务、备份或数据集。

## 本次实际删除

已删除下列5个停止的容器：

- `lab-workspace-chenlinlang-before-consolidation-20261007`。
- `lab-recovery-editor-511385bd18-2`。
- `lab-recovery-editor-511385bd18-1`。
- `xenodochial_kowalevski`。
- `festive_darwin`。

已删除旧 chenlinlang 镜像：

```text
sha256:1dbddb125c0be849c75bd41cfc09a3c5f81a4530ff5b21d2f82be6dfbdabd7b1
```

移除了3个冗余镜像别名；其有效镜像内容保留。三位学生实际使用的镜像现在有清晰标签 `lab-torch-dev:2.7.1-cu128-students`。

## 当前保留的两份 PyTorch 镜像

| 镜像/标签 | 用途 |
| --- | --- |
| `3216ed3c5fa8…` / `lab-torch-dev:2.7.1-cu128-students` | 三位学生正在运行的工作区共用。清理期间未重启这些工作区。 |
| `0d4305b85d12…` / `lab-torch-dev:2.7.1-cu128` | 已修复的新建环境，仍由唯一有效默认模板及历史任务引用，供后续创建工作区/调试/训练。 |

只删除旧的无用途对象，不自动迁移或重启三位学生的当前容器。因此保留这两份有用途的镜像；最终只保留新版需要另行完成工作区迁移。镜像显示大小包含共享层，不能将两份25GB直接相加。

## 系统部署镜像恢复

盘点发现 `lab-postgres:14-poc`、`lab-traefik:3.7.13-poc` 标签被手动删除，现有服务仍在运行。本次使用仓库的受控 Dockerfile 与现有 `lab-base-dev:2026.10-poc` 重新构建这两个必要部署镜像，共享基础层；未从运行容器复制状态或密钥，未重启生产服务。

```bash
docker build --build-arg LOCAL_CUDA_IMAGE=lab-base-dev:2026.10-poc -f infra/postgres/Dockerfile -t lab-postgres:14-poc .
docker build --build-arg LOCAL_CUDA_IMAGE=lab-base-dev:2026.10-poc -f infra/traefik/Dockerfile -t lab-traefik:3.7.13-poc .
```

两个 Dockerfile 明确设置 `CMD []`，避免本地基础镜像继承的 `bash` 参数传给服务入口。独立测试已验证：无生产挂载的 PostgreSQL 可初始化合成数据库并执行 SELECT 1；Traefik 可加载仓库配置并代理现有后端健康接口。测试容器随后移除。

## 数据与运行状态验证

- 清理前后，所有正在运行的容器 ID/镜像/挂载完全相同。
- 全部数据卷名称、真实用户/任务/模板数量，以及三位成员宿主机工作区目录 inode 保留。
- 三位成员各自的公网 Web 启动和 VS Code 工作台访问通过，仍使用原容器 ID。
- 三位成员 PyTorch 2.7.1+cu128、正确的项目权限和只读 `$DATASET=$HOME/dataset` 验证通过。
- chenlinlang 原 Python 卷已在空闲 RTX 5060 Ti 上完成真实 CUDA 矩阵运算。

最新私有迁移安全副本与验证报告：`runtime/logs/image-consolidation-20261007/`，目录700、文件600；所有旧备份也保留。旧 HOME 中尚未进入常用配置目录的 Claude/Codex 历史和 shell 文件已按对应成员保存至 `/opt/user-state/home-preserved/dataset-migration/`，逐文件 SHA256 验证，不覆盖当前配置。

## 本次未删除的其他对象

- 3个合成测试卷、39个空历史目录及旧 HOME/state/数据库备份：用户收窄删除范围后均保留。
- 五个现有账号的数据、workspace/results/scratch、个人 Python/state 卷及历史任务日志。
- 有效默认镜像、运行中的系统服务及其必要部署镜像。
- `/home/local/Desktop/code/Datasets`。
- `runtime/tandt_db.1.zip`、`runtime/tandt_db.zip`：用途未确认，保留。

机器报告：`safe-image-container-cleanup.json`、`image-alias-cleanup.json`、`core-image-tag-recovery.json`、`verification.json`，均位于上述私有报告目录。
