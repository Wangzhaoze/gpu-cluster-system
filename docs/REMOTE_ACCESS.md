# 跨网络使用与账号分配

## 开启临时公网入口

在本机 PowerShell 中执行（不用下载新镜像，也不需要其他设备安装 Docker）：

```powershell
cd D:\Projects\lab-cluster-system
.\scripts\remote-access.ps1 -Action Start
```

控制台显示 `Remote portal: https://....trycloudflare.com`。管理员也可以登录本机 http://localhost:8080，点击左侧「远程访问」，点击「复制访问链接」。在手机移动网络、另一台电脑或其他网络下打开这个 **HTTPS** 地址。

本机和 Docker Desktop 必须一直运行，Windows 休眠会中断服务。Cloudflare 隧道重启后会生成新地址；账号、文件和 Python 环境继续保留，需要将新链接交给成员。浏览器在新域名下需要重新登录。临时隧道没有固定域名及可用性保证，说明见 [Cloudflare Quick Tunnels 官方文档](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)。

查看当前地址与公网健康状态：

```powershell
.\scripts\remote-access.ps1
```

关闭公网入口（本机 Portal、工作区和任务继续运行）：

```powershell
.\scripts\remote-access.ps1 -Action Stop
```

## 管理员：分配一个账号

1. 本机打开 http://localhost:8080。用户名 `admin`，密码查看项目 `.env` 的 `INITIAL_ADMIN_PASSWORD`。它仅在首次初始化时有效；以后若修改管理员密码，以修改后的密码为准。
2. 点击左侧「用户管理」。在「添加实验室成员」中填写：
   - 用户名：如 `student01`；3–32 位小写字母、数字或下划线，以字母开头。
   - 初始密码：至少 12 位，也可以点击「生成随机密码」。
   - 显示名称：如「张同学」。
   - 角色：**成员**。
   - 固定环境：选择 `CUDA 12.8 · nvcc · Python 3.10`（新版编译环境）。
   - GPU 上限：**1**；调试时长上限：**4** 小时。
3. 点击「创建用户」。账号会自动获得独立工作目录、结果目录和持久化 Python 环境，无需手工建容器。
4. 页面出现「账号已创建」信息卡，点击「复制登录信息」。复制内容包含当前公网 URL、成员用户名、初始密码和首次操作步骤。将其交给对应成员。
5. 关闭信息卡后，密码不会再次显示。成员忘记密码时，在成员表格对应行点击「重置密码」；新密码至少 12 位，旧登录立即失效。成员停用时点击「停用」，其登录失效、工作区停止、未完成任务被取消；文件和 Python 环境保留。

每个人使用自己的成员账号。Portal 的本机和公网入口使用同一个数据库和账号体系；无需另外注册 Cloudflare 账号。

如果已有账号绑定的旧环境显示「本机镜像缺失」，管理员在「用户管理」点击该账号「编辑」，把固定环境选为新版 `CUDA 12.8 · nvcc · Python 3.10` 后保存。更换前需先结束该账号的工作区和任务。系统不自动迁移已有账号的固定环境；本次学生已绑定新版环境。

## 成员：按界面操作

1. 打开管理员提供的 HTTPS 链接，用分配的用户名和初始密码点击「登录」。
2. 点击「我的账号」。输入当前密码、新密码、确认新密码，点击「修改密码并重新登录」，再用新密码登录。修改会注销所有设备上的旧登录，不会停止训练或删除文件。「我的账号」也提供「退出登录」，手机同样可用。
3. 点击「工作区」→「启动」，等待状态变成「运行中」，点击「打开 VS Code ↗」。首次初始化可能需要数秒；若过早打开出现网关错误，稍后刷新。
4. VS Code 首次可能提示 Restricted Mode。请自行确认目录可信后点击 **Trust Folder & Continue**。点击顶部菜单 **Terminal → New Terminal**。代码保存到 `/workspace`，本机 D 盘数据集读取路径为 `/datasets`（只读），输出放在 `/results`。
5. 终端中测试：

```bash
python -c "import sys; print(sys.executable)"
ls /datasets
echo REMOTE_OK > /workspace/remote-check.txt
cat /workspace/remote-check.txt
```

「工作区」使用 CPU。需要 GPU 交互时，点击「在线调试」，选择 1 GPU、所需时长，点击「开启调试」，等待「运行中」，点击对应会话的「VS Code ↗」。用完点击「停止」，或者等待到期自动释放。

批量训练点击「训练任务」。第一次建议 GPU 数量 **0**，其他资源保留默认，把「运行命令」改为：

```bash
python -c "import os,pathlib; p=pathlib.Path(os.environ['LAB_RESULT_DIR']); (p/'remote.txt').write_text('REMOTE_TRAIN_OK'); print('REMOTE_TRAIN_OK')"
```

点击「提交训练」，状态依次为「排队中」→「运行中」→「已完成」。点击任务「日志」，确认 `REMOTE_TRAIN_OK`。输出位于 `/results/experiment/<任务ID>/remote.txt`，可以在工作区中查看。退出浏览器不会取消训练；需要终止时在 Portal 点击「取消」。

## 真实 GPU 与当前模式

Portal 顶部 `MOCK GPU MODE` 表示测试调度槽位，不透传显卡；`LOCAL GPU MODE` 表示真实 GPU。Windows 本机 RTX 3060 为 1 GPU。管理员在所有训练/调试任务结束后切换：

```powershell
.\scripts\set-scheduler.ps1 -Mode local-gpu-docker
```

远程成员刷新页面，调试或训练申请 **1 GPU**。训练命令先用 `nvidia-smi`，在「日志」确认 RTX 3060。工作区仍使用 CPU。基础镜像没有预装 PyTorch，需要时在自己的 Python 环境中安装。模拟模式测试完毕也可用同一脚本切回 `mock-docker`。

## 远程验收

```powershell
.\scripts\remote-test.ps1
```

在当前公网 URL 上测试 HTTPS 登录、Secure/HttpOnly cookie、跨站写拒绝、成员权限、工作区与 WebSocket、密码修改和其他会话失效、训练日志及结果。创建独立测试成员，结束后停用测试账号并停止测试工作区，保留测试数据及 `runtime/logs/acceptance-remote.json`。不改变实际成员或调度模式。

## 提示用户名或密码错误

登录页对所有原因显示同一句提示，具体原因由管理员查看：登录本机 Portal，点击「操作记录」，找到对应时间的 `login.failed`。「详情」列出原因、该设备实际提交的用户名、提交的密码位数、来源公网 IP 和浏览器；不记录密码本身。

- **用户名不存在**：设备提交的用户名与账号不一致，以详情中显示的为准（例如 `student-gpu` 与 `student_gpu`）。
- **账号已停用**：在「用户管理」点击「启用」。
- **密码不匹配**：提交的密码与设置的不同。位数与设置的密码不一致，说明多了或少了字符；位数一致，通常是大小写或 `0`/`O`、`1`/`l`/`I` 这类形近字符。在「用户管理」点击「重置密码」，设置一个不含这些字符的新密码再交给成员。

登录时用户名不区分大小写；用户名和密码中的全角字符、零宽字符及首尾空白（输入法和粘贴常带入）会被忽略，按原样提交的密码优先匹配。密码其余内容区分大小写。这样登录成功时，「操作记录」的 `login` 详情会注明。本次 student_gpu 初始密码中 `Q0EX` 的 `0` 是数字零。

登录限流为每个来源公网 IP 每分钟 20 次；超过时提示「登录过于频繁」，一分钟后重试。

2026-10-05 登录排查：学生账号启用、原密码匹配数据库；使用原值从当前公网 URL 登录和会话验证均成功。已复测 `student_gpu` 和带空格/大写的 ` Student_GPU `，两者均登录成功；浏览器重新登录通过。尚未取得失败设备的具体输入，因此不能断定该设备失败的原因。此次未重置密码、未重建学生 GPU 会话。

2026-10-05 第二次排查：Traefik 日志中另一台设备的 8 次登录（21:23–21:37 UTC）均到达后端并返回 401，即提交的用户名或密码与数据库不一致；隧道、Cookie、跨站校验和限流均未参与。当时后端不记录失败原因，无法还原那 8 次提交的内容，因此加入上述 `login.failed` 记录和不可见字符容错。同时修正限流：此前所有远程访问者共用隧道容器的 IP，一人反复重试会让其他人一并被限流。此次未重置任何密码。
