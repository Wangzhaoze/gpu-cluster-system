# GPU Lab

在一台 Windows 电脑上部署 GPU Lab，并通过随机公网链接让其他网络的设备访问。

## 准备

- Windows 10/11，已安装并启动 Docker Desktop（WSL 2 后端、Linux containers）和 Git。
- 能访问 Docker Hub、GitHub 和 apt/pip/npm 软件源。首次部署会下载约 7 GB 的 CUDA 基础镜像，建议预留 30 GB 磁盘空间。
- 使用真实显卡时，已安装 NVIDIA 显卡驱动。

## 部署

在 PowerShell 中执行：

```powershell
git clone https://github.com/Wangzhaoze/lab-cluster-system.git
cd lab-cluster-system
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\scripts\bootstrap.ps1
.\scripts\up.ps1 -Remote
```

- `Set-ExecutionPolicy` 只对当前 PowerShell 窗口生效，每次新开窗口运行脚本前执行一次。
- `bootstrap.ps1` 生成 `.env`（含随机管理员密码），并准备基础镜像，本机没有时自动下载。
- `up.ps1 -Remote` 构建并启动全部服务和公网隧道，结束时打印访问链接。
- 要把本机的数据集目录只读提供给所有成员（容器内路径 `/datasets`），把第四行改为 `.\scripts\bootstrap.ps1 -DatasetPath 'D:\你的数据集目录'`。

## 获取访问链接

`up.ps1 -Remote` 结束时输出：

```
Portal: http://localhost:8080
Remote portal: https://<随机字符>.trycloudflare.com
```

`Remote portal` 是其他网络可以打开的链接，`Portal` 只能在这台电脑上打开。如果提示 `Tunnel is still connecting`，稍等几秒后查看。随时查看当前链接：

```powershell
.\scripts\remote-access.ps1
```

链接是随机的，隧道每次重启（包括重启电脑或 Docker Desktop）都会更换，需要重新查看并发给使用者。这台电脑和 Docker Desktop 必须保持运行。

## 获取密码

**管理员**：用户名 `admin`。密码在首次执行 `bootstrap.ps1` 时随机生成，保存在 `.env` 中。查看：

```powershell
(Get-Content .env) -match '^INITIAL_ADMIN_PASSWORD=' -replace '^[^=]+='
```

这个密码只在第一次启动时写入数据库。之后在 Portal 里改过密码的话，以改后的为准。

**成员**：用管理员登录 Portal，然后：

1. 点击「用户管理」，填写用户名和显示名称。
2. 点击「生成随机密码」，再点击「创建用户」。
3. 在出现的信息卡上点击「复制登录信息」，把内容发给成员。其中包含当前公网链接、用户名和密码。

信息卡关闭后密码不再显示。成员忘记密码时，在成员列表点击「重置密码」。

## 使用真实显卡

部署后默认是模拟 GPU，Portal 顶部显示 `MOCK GPU MODE`，任务拿不到显卡。切换到真实显卡：

```powershell
.\scripts\set-scheduler.ps1 -Mode local-gpu-docker
```

显卡数量不是 1 时，先把 `.env` 里的 `LOCAL_GPU_COUNT` 改成实际数量。切换前需要结束所有训练和调试任务。

## 停止与再次启动

```powershell
.\scripts\down.ps1                  # 停止全部服务；账号、文件和 Python 环境保留
.\scripts\up.ps1 -Remote -NoBuild   # 再次启动，会得到一个新的公网链接
```
