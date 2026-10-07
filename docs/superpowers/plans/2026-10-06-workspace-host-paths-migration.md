# Workspace Host Paths and Runtime Migration Implementation Plan

> **For agentic workers:** Execute these checked steps inline in the authorized deployment session; retain live database and Python volumes.

**Goal:** Show each user's actual host workspace directory in the portal and run the cluster independently of the previous checkout.

**Architecture:** Centralize host bind paths in DockerStorage, return them only through the existing authorized workspace API, and show copyable host paths and ownership-preserving rsync instructions. Move runtime data and private configuration to this checkout while preserving the Compose project, database volume, per-user Python volumes and running Cloudflare tunnel.

**Tech Stack:** FastAPI, Docker SDK, PostgreSQL, React/TypeScript, Docker Compose, Ubuntu file ownership.

---

### Task 1: Host path contract

Files: `backend/app/storage.py`, `backend/app/main.py`, `tests/backend/test_workspace_paths.py`.

- [x] Test custom host root/dataset path, agreement between API and bind mounts, stopped workspace visibility, anonymous denial and cross-user denial.
- [x] Run the new tests with the existing backend image and read the failures before adding the feature.
- [x] Add `DockerStorage.host_paths(username)` returning configured workspace/results/scratch/dataset paths; make `mounts()` use the same paths.
- [x] Extend the workspace response with `host_paths`, `host_uid`, `host_gid`, and `host_import_command` generated with `shlex.quote`; keep existing fields and authorization.
- [x] Run all backend tests, expecting every test to pass.

### Task 2: Portal instructions

Files: `frontend/src/types.ts`, `frontend/src/main.tsx`, `frontend/src/styles.css`, `README.md`.

- [x] Add the corresponding fields to Workspace and display a host-to-container path table, copy buttons, UID/GID and import command.
- [x] Explain that the host workspace and `/workspace` are the same directory, imported projects open under `/workspace/project`, shared datasets remain read-only and imported files must have the user's ownership.
- [x] Run the frontend Docker build and shell syntax checks.

### Task 3: Live migration and acceptance

Files/data: private `.env`, ignored `runtime/`, `tests/integration/workspace_paths.py`, `docs/UBUNTU_VALIDATION.md`.

- [x] Confirm no active debug/training workloads; inventory existing workspace containers, volumes and current public URL.
- [x] Preserve private credentials in mode-600 `.env` and change only host runtime/dataset paths. Build updated backend/frontend images before pausing services.
- [x] Stop workspace writers, backend, worker and monitor. Back up PostgreSQL and copy runtime data with numeric ownership using a root helper container. Retain all named volumes.
- [x] Start updated backend/worker/frontend/monitor from this checkout and recreate only the previously running workspace containers. Keep the existing Cloudflare container and URL.
- [x] Verify no bind mount or service path environment references the old checkout, preserve users/history/volumes, and test host-to-workspace-to-host file edits using a disposable member.
- [x] Test public HTTPS, editor availability, GPU telemetry and Python interpreter/PyTorch, clean up only disposable test data, and record validation.
Delivery: commit and push the verified code to the existing feature branch as Lang5Max; exclude private configuration and runtime files.
