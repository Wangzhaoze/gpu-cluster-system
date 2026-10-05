# Windows 本机测试

## 启动与登录

1. Docker Desktop 使用 Linux containers。
2. 运行 `scripts/bootstrap.ps1` 和 `scripts/up.ps1`。已构建则 `up.ps1 -NoBuild`。
3. 打开 http://localhost:8080，使用 `.env` 里的管理员账号登录。
4. 用户管理创建 `student01`、`student02`，密码至少 12 位，角色 MEMBER。
5. 在浏览器隐身窗口分别登录，验证管理员菜单不会向成员显示。

## 工作区 / Python 持久化

student01 打开「工作区」→ 启动 → 打开 VS Code。VS Code 首次可能显示 Restricted Mode；对自己创建且确认可信的工作目录选择 Trust Folder & Continue，然后打开 Terminal → New Terminal。终端运行：

```bash
python -c "import sys; print(sys.executable)"
pip install rich==13.9.4
echo HELLO > /workspace/persist.txt
ls /datasets
touch /datasets/should-fail.txt  # 必须报 Read-only file system
```

停止工作区，再次启动，检查：

```bash
python -c "import rich; print('PERSIST_OK')"
cat /workspace/persist.txt
```

student02 应无法访问 student01 的 `/workspace/student01/` 路由；其独立环境未安装 rich。管理员应能访问全部工作区。

## Debug / Training

Debug 新建 1 GPU、30 分钟会话；打开 VS Code，验证 `import rich`。结束后资源卡片应释放 GPU。短 TTL 的自动测试由验收脚本执行。

Training 提交：

```bash
python -c "import rich,os,pathlib; p=pathlib.Path(os.environ['LAB_RESULT_DIR']); (p/'result.txt').write_text('RESULT_OK'); print('TRAIN_OK')"
```

应进入 COMPLETED，日志显示 TRAIN_OK，宿主机 `runtime/results/student01/experiment/<id>/result.txt` 存在。点击重试应创建新 ID。提交 `exit 7` 应 FAILED、退出码 7。提交 `sleep 60`，最大运行时间 5 秒，应 TIMED_OUT。

## 5 GPU 队列

mock 模式依次提交两个 2 GPU 的 `sleep 120` 训练，再开启 1 GPU Debug，应该分配 0,1 / 2,3 / 4。再提交 1 GPU 任务应保持 PENDING。停止 Debug 后排队任务自动启动。设置用户 max_gpus 会同时限制单次请求和实际并发 GPU 总数。

有运行和排队任务时，执行：

```powershell
docker compose restart backend scheduler-worker
```

验证运行容器 ID 不变、无重复容器、队列继续。停止静态服务不会删除数据库/卷，实际整套服务停止还可用 `down.ps1`。

## 真实 GPU

```powershell
.\scripts\set-scheduler.ps1 -Mode local-gpu-docker
.\scripts\acceptance-test.ps1 -Gpu
```

Portal 会显示 LOCAL GPU MODE 和 1 个真实 GPU；训练请求 1 GPU。可直接提交 `nvidia-smi`。Workspace 无 GPU，Training/Debug 使用 Docker DeviceRequest。没有 PyTorch 的情况下可以先验证 CUDA API；需要 PyTorch 时在自己的持久化环境中安装兼容版本。

结束任务后回到 mock：

```powershell
.\scripts\set-scheduler.ps1 -Mode mock-docker
```

## 可选远程

```powershell
.\scripts\up.ps1 -Remote -NoBuild
```

「远程访问」显示当前 trycloudflare URL。使用外网浏览器登录并打开 Workspace，确认终端可交互、WebSocket 保持连接。这个命令会建立公网入口；基础本机验收不自动开启。停止 tunnel：`docker compose --profile remote stop cloudflared`。

## 自动验收

```powershell
.\scripts\acceptance-test.ps1
```

先跑 Python 合约单元测试，再跑真正的 HTTP/PostgreSQL/Docker 验收。测试运行在独立临时 runner，能够重启 backend/worker。验收会安装 rich 包，不拉取镜像；完成后停用测试账号，保留测试日志和结果。

报告在 `runtime/logs/acceptance.json` 与 `acceptance-gpu.json`。若失败，查看 `scripts/logs.ps1` 和任务日志，不要先使用 reset-dev 清空证据。
