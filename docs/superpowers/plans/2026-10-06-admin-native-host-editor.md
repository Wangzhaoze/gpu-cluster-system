# Native Host Administrator Editor Implementation Plan

> **For agentic workers:** Execute inline in the authorized deployment; use the selected existing Linux user `local`, retaining sudo password requirements and student containers.

**Goal:** Make an ADMIN workspace a real Ubuntu host VS Code terminal with Docker access rather than a student container.

**Architecture:** Run bundled code-server natively as local using a lingering systemd user service and a mode-600 Unix socket. A minimal Node HTTP/WebSocket proxy mounts only the socket directory and checks the backend ADMIN session on every connection; Traefik also authorizes the host route. Members retain their existing container workspaces and storage.

**Tech Stack:** Ubuntu systemd user service, code-server 4.140.0, Node built-in HTTP/net, FastAPI, React, Docker Compose.

---

### Task 1: Authorization and workspace contract
Files: `backend/app/host_editor.py`, `config.py`, `main.py`, `tests/backend/test_host_editor.py`.
- [x] Add failing tests for admin native workspace, member/anonymous host denial, host route traversal denial, and host workspace deletion/stop rejection without touching files.
- [x] Add configured host identity/Python/status metadata and a distinct `mode=host` response for admins; member mode remains `container`.
- [x] Add an admin-only proxy authorization endpoint and recognize `/host/` in forward auth.
- [x] Run all backend tests with no failures.

### Task 2: Native process and authenticated proxy
Files: `scripts/host_editor.py`, `scripts/host-editor.sh`, `infra/host-editor-proxy.mjs`, `tests/proxy/host-editor.test.mjs`, `compose.yaml`, `.env.example`, `scripts/lab.sh`.
- [x] Extract existing code-server and Python extension from the base image into ignored runtime; configure `/home/local`, host Conda dl Python and an editor-specific shell startup without modifying the user's shell configuration.
- [x] Install and enable a systemd user service using refreshed Docker group membership, a private Unix socket and automatic restart. Use no privileged editor container and grant no passwordless sudo.
- [x] Add a readonly socket proxy and test allowed admin HTTP/WebSocket, denied member/guest/direct access, cross-origin rejection and fail-closed backend authorization.
- [x] Add host profile/configuration and lifecycle commands; preserve the public tunnel and existing student workspace containers during deployment.

### Task 3: Portal and live verification
Files: `frontend/src/types.ts`, `frontend/src/main.tsx`, `README.md`, `docs/UBUNTU_VALIDATION.md`, `tests/integration/host_editor.py`.
- [x] Replace admin workspace controls with a native host entry showing Linux identity, host folder, Python path and Docker/sudo usage; remove host deletion/stop controls. Preserve student UI.
- [x] Build backend/frontend; start native service and proxy; update application services without recreating tunnel or student workspaces.
- [x] Verify public admin editor HTTP/WSS and member/guest rejection, direct proxy denial, native PID/UID/mount namespace, Docker access, PyTorch, host file writes and protected sudo behavior.
- [x] Verify unchanged user passwords/history and healthy GPU telemetry; remove disposable test sessions/files.
Delivery: commit and push the verified change to the existing Lang5Max branch, excluding private configuration and runtime.

Verification: 72 backend tests, 7 production-runtime proxy tests and 6 public host-editor checks passed; native local/PyTorch/Docker verification and existing-user/workload/container fingerprint checks passed. Temporary verification resources were removed.
