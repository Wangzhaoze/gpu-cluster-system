# Public access and student GPU sessions

## Cloudflare HTTPS link

```bash
./scripts/lab.sh up --remote --no-build
./scripts/lab.sh remote-url
./scripts/lab.sh remote-test
```

The public URL forwards to the same portal, database and account system as `http://localhost:8080`. It works from other networks without opening an inbound router port. The PC and Docker must remain running. A tunnel restart generates a new hostname, so retrieve and share the new URL and log in again. [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) have temporary hostnames and no uptime guarantee; use a named tunnel with your own domain if a permanent address is required.

To stop only public access while keeping local services and jobs:

```bash
sg docker -c 'docker compose --profile remote stop cloudflared'
```

## Administrator: create a student

Open **用户管理** after logging in as `admin`. Choose a lowercase username such as `student01`, enter a display name and generate a password. Set:

| Field | Value |
| --- | --- |
| 角色 | 成员 (MEMBER) |
| 固定环境 | CUDA 12.8 · nvcc · PyTorch 2.7.1 |
| GPU 上限 | 1 |
| Debug 免审批上限 (小时) | 10 |

Click **创建用户**, then **复制登录信息**. The invitation includes the current public URL, username and initial password. The password is not shown again after the invitation closes. Use **重置密码** if needed. Students may change their password in **我的账号**; this revokes previous login sessions while preserving their running jobs and files.

Choose the template marked **新用户默认 · PyTorch** (`2.7.1-cu128-editor`). New accounts select it by default. VS Code has the Python extension installed, points to `/opt/user-env/venv/bin/python`, and activates that persistent environment in new terminals. All currently enabled administrator/student accounts use this template too; their previous Python environments were backed up inside their existing volumes.

The API equivalent is `POST /api/users` with `role="MEMBER"`, `max_gpus=1`, `max_debug_hours=10` and the registered PyTorch template's `default_environment_id`. No example password is embedded in this documentation.

## Student: choose a real GPU and request up to ten hours

The portal must show **LOCAL GPU MODE**. Open **总览** to check per-card load, memory, temperature, power and external/platform occupancy. In **在线调试**, choose the assigned PyTorch environment, automatic allocation or **指定显卡**, select a card and enter the duration in hours (e.g. `10`). Set suitable CPU/RAM limits and click **开启调试**. A selected card being occupied waits for that card rather than switching to another. Once running, click **VS Code ↗**, then open **Terminal → New Terminal**.

For GPU 2 and ten hours, the request uses `requested_gpus=1`, `gpu_indices=[2]`, `time_limit_seconds=36000`. Use `gpu_indices=null` for automatic allocation. Training supports selecting multiple GPUs within the user's limit; debug supports one. The expiry is measured from container start. Inside a one-GPU container the selected physical card is CUDA device 0. Workspace/debug/training share code, results and persistent packages. Workspaces use CPU; use debug or GPU training for CUDA.

For more than ten hours (maximum seven days), enter an approval reason. **提交审批申请** creates a waiting request without reserving GPUs. Administrators review it in **在线调试** and click **批准** or **拒绝**. Approval enters the queue; each request requires approval separately. Students may withdraw a pending request. API decisions are `POST /api/debug/{id}/approve` or `/reject`, admin-only, with optional `{"note":"..."}`. User GPU limits, enabled status and assigned template are checked again at approval.

```bash
nvcc --version
nvidia-smi
python -c "import torch; assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0)); x=torch.ones(128,128,device='cuda'); print((x@x)[0,0].item())"
```

Save code in `/workspace`, read shared data from `/datasets`, and write results under `/results`. Press **停止** when done, or let the session expire. Closing the browser preserves the session until its time limit.

## Admin-only deletion

Members can stop sessions and cancel jobs; only administrators can delete accounts, workspace data, templates/images and debug/training history. Delete records after they reach a terminal state. Delete workspace data only after all debug/training workloads finish or stop; results and history remain. Account deletion requires a disabled, idle account and removes its private data, results and history while retaining audit events. Configured default images and images referenced by templates or containers cannot be deleted. Every deletion action shows its scope before confirmation.

## Verification and login issues

`./scripts/lab.sh remote-test` verifies public HTTPS, secure cookies, permissions, editor routing, WebSockets, password/session behavior and job results. It creates disposable accounts, disables them afterward, and saves `runtime/logs/acceptance-remote.json`.

If login fails, an administrator can inspect **操作记录** for `login.failed`. The audit records the submitted username, password length and failure reason without the password. Login is limited to 20 attempts per source IP per minute. Usernames ignore case and accidental input padding; passwords otherwise remain case-sensitive.
