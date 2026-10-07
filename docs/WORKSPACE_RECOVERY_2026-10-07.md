# 工作区权限修复与待确认清理清单（2026-10-07）
> 后续状态：chenlinlang 已迁移到与另两位成员一致的镜像；旧 chenlinlang 容器/镜像和4个测试容器已清理。所有卷、代码目录和备份仍保留。详见 [镜像迁移与实际清理结果](IMAGE_CONSOLIDATION_2026-10-07.md)。下文记录此前恢复时的状态。


三个真实成员工作区已原地恢复，原容器 ID、项目目录、Python 卷及用户状态卷全部保留。未删除现有成员数据、冗余目录、原镜像或备份。

## 原因与修复

- 镜像里 `/opt/lab` 和 `/opt/lab/extensions` 为 root 的 `700`。新版启动脚本以成员身份复制扩展时无法读取，导致退出码 1。
- 宿主机文件采用私有文件模式时，Dockerfile 原来的 `chmod +x` 会生成 `711` 的 Python 配置脚本；成员可以执行却不能读取脚本内容。这一后续问题也已复现并修复。
- 两种镜像现在明确设置公共启动程序为 `0755`，公共扩展树可读可遍历。启动脚本兼容旧固定镜像的上述权限。仅修改公共程序和扩展，不开放成员私人配置。
- `useradd: home directory already exists` 是 `/home/<用户名>/dataset` 挂载和初始化造成的非致命提示，与工作区归属无关。
- 现有三个失败容器原地替换启动脚本并启动，没有删除或重新分配容器。内置环境模板已指向通过验证的修复镜像，模板 ID、用户默认模板 ID 和 Python/CUDA 版本保留。原镜像增加回滚标签并保留。

## 成员目录核对

| 成员 | UID/GID | 宿主机项目目录 | 补回缺失的个人配置文件 |
| --- | --- | --- | --- |
| chenlinlang | 2006:2006 | `/home/local/gpu-cluster-system/runtime/users/chenlinlang/workspace` | 5802 |
| yuanxinli | 2007:2007 | `/home/local/gpu-cluster-system/runtime/users/yuanxinli/workspace` | 5499 |
| yinshengwang | 2001:2001 | `/home/local/gpu-cluster-system/runtime/users/yinshengwang/workspace` | 4 |

这些项目目录本来就与成员账号匹配，因此保留当前项目文件，没有用旧副本覆盖它们。旧 HOME 备份中的个人配置按备份用户名及 UID 核验后，只补回对应 `lab_userstate_<用户名>` 中缺失的文件；现有文件保留。也核对了旧成员工作区内的私人 Codex 目录。

恢复前的状态卷、容器信息、启动程序及数据库副本保存在私有目录：

`/home/local/gpu-cluster-system/runtime/logs/workspace-recovery-20261007/`

该目录权限为 `700`，备份文件为 `600`；原来的 `dataset-home-migration-20261007` 备份也保留。

## 验证结果

- 三个真实成员通过自己的临时会话调用 Web 工作区启动接口，原容器 ID 均相同；公网编辑器返回 VS Code 工作台。临时会话随后撤销，用户密码未重置。
- 三位成员实际 Python 均为 `/opt/user-env/venv/bin/python`，PyTorch `2.7.1+cu128`；项目目录可写、状态归对应 UID，`$DATASET=$HOME/dataset` 且只读。
- 119 项后端测试、Shell 语法、Compose 配置检查通过。真实镜像验收通过三个检查：无特权读取公共扩展/配置脚本、全新成员编辑器启动、再次创建编辑器后保留 Python 设置及合成的 Codex 状态。
- 全部原账号/密码/角色/UID/配额、训练与调试记录和环境变量通过恢复前后核对。数据库、调度器、门户、公网隧道及管理员宿主机编辑器保留运行。

## 待确认删除清单

以下只是候选清单，本次未执行删除。确认功能无误后，还需要在实际清理时重新检查是否被使用。

### 1. 39 个空的历史成员目录

已确认不在当前用户表、不含文件或子目录、没有工作区直接挂载。合计仅约 156 KiB，清理收益很小。

```text
/home/local/gpu-cluster-system/runtime/users/changxu
/home/local/gpu-cluster-system/runtime/users/chenlin
/home/local/gpu-cluster-system/runtime/users/dataset_1f209201
/home/local/gpu-cluster-system/runtime/users/dataset_45a69351
/home/local/gpu-cluster-system/runtime/users/debugcheck_1be4b5fc
/home/local/gpu-cluster-system/runtime/users/debugcheck_d63169c5
/home/local/gpu-cluster-system/runtime/users/deletecheck_358f387b
/home/local/gpu-cluster-system/runtime/users/deletecheck_64cdfe81
/home/local/gpu-cluster-system/runtime/users/gpucheck_5338c085
/home/local/gpu-cluster-system/runtime/users/gpucheck_abad32c2
/home/local/gpu-cluster-system/runtime/users/gpuchoice_0121ddda
/home/local/gpu-cluster-system/runtime/users/path_24d7915a
/home/local/gpu-cluster-system/runtime/users/path_34dbd16f
/home/local/gpu-cluster-system/runtime/users/path_3b479a3e
/home/local/gpu-cluster-system/runtime/users/path_f69d5ffd
/home/local/gpu-cluster-system/runtime/users/portal_ae26efaa
/home/local/gpu-cluster-system/runtime/users/portal_f71528bc
/home/local/gpu-cluster-system/runtime/users/remote_041a58ae
/home/local/gpu-cluster-system/runtime/users/remote_0444a9a9
/home/local/gpu-cluster-system/runtime/users/remote_61001bb3
/home/local/gpu-cluster-system/runtime/users/remote_9e391dca
/home/local/gpu-cluster-system/runtime/users/remote_ae859cfd
/home/local/gpu-cluster-system/runtime/users/remote_bc399d96
/home/local/gpu-cluster-system/runtime/users/remote_cb3edd04
/home/local/gpu-cluster-system/runtime/users/remote_e2d45202
/home/local/gpu-cluster-system/runtime/users/remote_e8860189
/home/local/gpu-cluster-system/runtime/users/remote_f61b57ce
/home/local/gpu-cluster-system/runtime/users/test_a_96ed7def
/home/local/gpu-cluster-system/runtime/users/test_a_9b4f999d
/home/local/gpu-cluster-system/runtime/users/test_a_9c9a3387
/home/local/gpu-cluster-system/runtime/users/test_a_a42cb5cc
/home/local/gpu-cluster-system/runtime/users/test_a_bbeee40f
/home/local/gpu-cluster-system/runtime/users/test_a_d65a40a9
/home/local/gpu-cluster-system/runtime/users/test_b_14da6618
/home/local/gpu-cluster-system/runtime/users/test_b_218995e1
/home/local/gpu-cluster-system/runtime/users/test_b_5a536fe5
/home/local/gpu-cluster-system/runtime/users/test_b_68d224fb
/home/local/gpu-cluster-system/runtime/users/test_b_bbb87521
/home/local/gpu-cluster-system/runtime/users/test_b_eea064eb
```

### 2. 本次保留的合成测试容器

全部已停止，不是实际成员的工作区，不含真实成员凭据。

| 容器名称 | 状态 |
| --- | --- |
| `lab-recovery-editor-511385bd18-2` | exited |
| `lab-recovery-editor-511385bd18-1` | exited |
| `xenodochial_kowalevski` | exited |
| `festive_darwin` | exited |


### 3. 本次保留的合成测试卷

供上面的新建/重建测试使用，只含测试环境、设置和合成标记。清理时应先删除对应的测试容器，再检查这些卷未被挂载。

- `lab_recovery_workspace_511385bd18`
- `lab_recovery_python_511385bd18`
- `lab_recovery_state_511385bd18`


### 4. 镜像盘点

当前未发现同时满足“无容器引用、无环境模板引用、不是配置默认镜像”的镜像删除候选。旧工作区镜像仍由恢复后的真实容器引用；不列入无用镜像。

### 继续保留的数据

- 三个真实成员的项目、结果、缓存、`lab_pyenv_*` 和 `lab_userstate_*`。
- 两位管理员仍有账号关联的旧 Python 卷，不能仅凭目前未挂载就视为无用。
- 原 HOME 备份、此次约 1.9 GiB 的恢复前状态卷备份、数据库和镜像回滚副本。
- `/home/local/Desktop/code/Datasets` 与 `runtime/tandt_db.1.zip`、`runtime/tandt_db.zip`。下载文件的用途和完整性尚未确认，未列入确定无用的数据。

完整机器清单：`runtime/logs/workspace-recovery-20261007/cleanup-candidates.json`。
验证报告：同目录的 `editors.json`、`preservation.json`、`image-acceptance.json` 与各成员的 `*.restore.json`。
