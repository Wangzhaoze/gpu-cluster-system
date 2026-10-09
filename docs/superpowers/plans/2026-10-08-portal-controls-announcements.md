# Portal controls and announcements implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement the requested portal improvements as source changes only, without deploying, restarting, or modifying production data.

**Architecture:** Keep the existing FastAPI/SQLAlchemy scheduler and React portal. Add durable announcement drafts, immutable publication and per-member read receipts. Run terminal workload retention under the existing scheduler lock. Replace the update script with an idempotent local checkout update that preserves student containers, images, volumes and the existing public tunnel.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic/PostgreSQL, React/TypeScript, Docker Compose, pytest and isolated browser tests.

---

### Task 1: Resource and session contracts

Files: `backend/app/schemas.py`, `backend/app/main.py`, `backend/app/models.py`, `backend/app/scheduler/mock_docker.py`, migration `0003_portal_announcements.py`; tests `tests/backend/test_portal_updates.py` and existing GPU/role tests.

- [x] Add regression tests for GPU-required submissions, defaults and the 8-hour boundary:
  ```python
  assert JobSpec(command='true').requested_cpus == 4
  assert DebugSpec().requested_ram_mb == 4096
  with pytest.raises(ValidationError): DebugSpec(time_limit_seconds=28801)
  ```
- [x] Enforce one unfinished debug session per member under the existing user row lock, including pending/cancelling requests; reject a duplicate with HTTP 409. Preserve existing running sessions until their original deadlines. Keep multi-GPU allocation.
- [x] Clamp stored user limits to 8 in the new migration; enforce 8 hours for all new/edited debug requests. Keep historical approval fields for compatibility.
- [x] Verify `DATABASE_URL=sqlite:////tmp/portal-unit.sqlite PYTHONPATH=backend /tmp/gpu-cluster-portal-test-env/bin/pytest tests/backend -q` using only an isolated database and mocked Docker.

### Task 2: Kill and administrator extension controls

Files: `backend/app/main.py`, `frontend/src/main.tsx`, `frontend/src/types.ts`, `frontend/src/WorkloadEditor.tsx`; tests `tests/backend/test_portal_updates.py`.

- [x] Verify member cancellation of their own training and rejection of other-member cancellation. Add `/api/jobs/{id}/kill` as the explicit cancellation control, keeping the existing cancel route compatible; let the scheduler stop the container and capture logs.
- [x] Supply queue `can_manage` and cancellation state without exposing private task details. Display a disabled kill button for other members' tasks and completed/cancelling tasks.
- [x] Provide an administrator-only training extension form using `POST /api/jobs/{id}/extend`, retaining the current container and rejecting an expired deadline or a member request.
- [x] Put `保存 TXT 日志` beside each training's `打开日志` button, linking to the existing authorized download endpoint.

### Task 3: Durable announcements

Files: `backend/app/models.py`, `backend/app/schemas.py`, `backend/app/announcements.py`, `backend/app/main.py`, new Alembic migration, `frontend/src/Announcements.tsx`, `frontend/src/main.tsx`, `frontend/src/types.ts`.

- [x] Add `announcements` (title, body, creator, created/updated/published timestamps) and `announcement_reads` (announcement/user composite key, read timestamp) tables.
- [x] Implement admin draft create/edit and explicit publish APIs; require nonblank title/body, reject member writes, and prevent edits after publication.
- [x] Query unread published announcements for members, oldest publication first. Acknowledge through `POST /api/announcements/{id}/read`, scoped to the signed-in member, with idempotent receipts.
- [x] Admin UI saves drafts, previews them and explicitly confirms publishing. Member UI polls independently of slow storage refreshes and shows one unread announcement at a time; only successful close/read acknowledgment dismisses it permanently.
- [x] Test draft invisibility, publication authorization, online delivery, offline/login delivery and durable per-user receipts.

### Task 4: Seven-day history retention

Files: `backend/app/retention.py`, `backend/app/worker.py`, tests `tests/backend/test_portal_updates.py`.

- [x] Under the scheduler's existing advisory lock, scan only terminal workloads with completion older than seven days; use creation date only for legacy terminal rows with no completion timestamp.
- [x] Remove leftover managed terminal containers and their task log files, then their records. Retain workspace, results, scratch, Python environments, user state, active/pending work and audit history. Run hourly and on worker start.
- [x] Test cutoff, long-running and pending preservation, log removal and filesystem errors without deleting a record prematurely.

### Task 5: GPU cards and resource input UI

Files: `frontend/src/main.tsx`, `frontend/src/styles.css`, `frontend/src/WorkloadEditor.tsx`, `frontend/src/HelpPage.tsx`.

- [x] Use role-independent green/blue/orange/gray backgrounds and badges for free/debug/train/external; display `用户：xxx`; remove fan and memory-controller utilization from the overview.
- [x] Remove CPU-only choices, default to auto one GPU and guard empty/manual and zero-quota submissions. Keep occupied cards disabled and gray.
- [x] Default both forms to 4 CPU and 4 GB. Convert displayed GB to integer MiB at the API boundary with `Math.round(gb * 1024)`; admin edit uses the same unit.
- [x] Enforce the 8-hour and one-session policy in UI; keep backend authoritative. Update help text and browser regression fixtures.

### Task 6: Repeatable manual update/start script

Files: `apply-latest.sh`, `backend/app/update_images.py`, `scripts/image_fingerprint.py`, `backend/Dockerfile`, `frontend/Dockerfile`, `compose.yaml`, `.gitignore`, `tests/scripts/test_apply_latest.py`, `docs/PORTAL_UPDATE_2026-10-08.md`.

- [x] Default to applying the current checkout, including local source changes, with no automatic branch switch or pull. Add explicit `--pull`, `--remote` and `--no-build`; document the behavior.
- [x] Use a process lock, validate configuration and required images before downtime, record current application image IDs, and build backend/frontend only with existing base images. Never rebuild the CUDA/Torch student image during a portal update.
- [x] Stop the scheduler before backend migration; wait for backend health before restoring it. On failure restore old backend/frontend tags and service health when possible. Preserve student workspaces, running training/debug, database volumes and any existing tunnel container.
- [x] After success remove only superseded untagged application image IDs with no container/template references; never use global prune, force removal or volume deletion. Repeat the script without creating duplicate persistent containers/images.
- [x] Test ordering, repeated starts, build failure, update failure rollback, profiles, local changes and cleanup against fake Docker commands; run `bash -n apply-latest.sh`.

### Task 7: Verify and deliver source only

- [x] Build with `npm run build` in the isolated frontend copy.
- [x] Serve that build on localhost and run intercepted browser tests with synthetic accounts, GPUs, workloads and announcements; do not call the production API.
- [x] Review `git diff --check` and feature coverage, copy only changed source/test/docs files back to the real checkout, and preserve the user's edited `TODO.md`.
- [x] Compare production container IDs/start timestamps to the read-only baseline. Report tests and the exact manual update command; do not execute the update script, push, or restart services.
