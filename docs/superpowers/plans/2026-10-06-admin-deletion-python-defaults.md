# Admin deletion and Python defaults implementation plan

> Execute inline in this session; the user authorized refinement and deployment.

**Goal:** Allow only administrators to delete accounts, workspace data, unused Docker images and finished workload records, and launch editors with the persistent PyTorch Python environment.

**Architecture:** Add DELETE routes protected by `admin_user`, coordinated with the scheduler advisory lock. Use explicit deletion scope and reject active resources, self-deletion and images referenced by templates or containers. Add admin UI actions with confirmation text. Keep member stop/cancel operations. Write VS Code interpreter defaults at editor startup without replacing unrelated settings; install the Python extension in lab images. Default new accounts to the available PyTorch template. Existing Python environments remain pinned unless explicitly reset by an administrator.

**Tech Stack:** FastAPI, SQLAlchemy/PostgreSQL, Docker SDK, React/TypeScript, Bash, code-server.

- [x] Add permission tests proving each DELETE route returns 403 for members before accessing Docker/storage, and 401 for anonymous requests.
- [x] Implement account deletion (disabled and idle accounts only; delete associated records, volumes and user storage; preserve audit history with detached actor references). Reject deleting the signed-in administrator.
- [x] Implement workspace deletion (idle user only; clear workspace and Python volume, recreate an empty workspace record; retain training results and history).
- [x] Implement finished debug/training record deletion (terminal status only; remove logs and leftover container; retain result files).
- [x] Implement admin Docker image listing/deletion (immutable full SHA256 ID; refuse template/container references and service/base images; no force/prune).
- [x] Add corresponding admin-only UI actions and confirmation descriptions; choose the recommended PyTorch template for new accounts.
- [x] Add per-editor settings for `python.defaultInterpreterPath=/opt/user-env/venv/bin/python` and terminal activation; install Python extension, preserve settings and verify new Bash terminals resolve the same Python with inherited torch.
- [x] Build refreshed lab and application images; register an immutable updated PyTorch template. Preserve existing user data/templates; configure the admin's new workspace to the PyTorch image with its old venv backed up inside the existing Python volume.
- [x] Run backend permission tests and disposable end-to-end deletion checks (members denied, admins succeed, conflicts enforced, shared data/results preserved).
- [x] Verify real one-GPU PyTorch debug/editor startup and public HTTPS/editor/WebSockets, then update deployment validation documentation.

Validation commands: `./scripts/lab.sh test --gpu`, `./scripts/lab.sh torch-test`, `./scripts/lab.sh remote-test`, `git diff --check`, plus disposable HTTP deletion checks from `tests/integration/admin_deletion.py`. Never delete a real account or workspace as part of verification.

Results: 42 backend tests, seven admin deletion checks, two real GPU scheduler checks and seven public HTTPS/editor/WSS checks passed. New and all enabled administrator/student workspaces use the default PyTorch venv; previous Python environments were backed up and student workspace states restored. Browser plugin setup failed, so visual browser inspection was unavailable; the production frontend build and editor HTTP/WSS checks passed.
