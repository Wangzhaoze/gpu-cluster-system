# Host resource upgrade implementation plan

> Execute inline in this session. Source changes and rollout are authorized by the user's request; do not modify member quotas, student files, datasets or base images.

**Goal:** Use all five GPU slots and the upgraded 30-vCPU/~57.44-GiB host, with dynamic limits and bounded shared RAM allocation.

**Architecture:** Read capacity from Docker Engine, reserve configurable8GiB for OS/control plane, account running member workspaces and active training/debug reservations, serialize workspace admission with the existing scheduler advisory lock. Keep FIFO. Expose capacity through the existing GPU API and React inputs. No database schema migration.

**Tech stack:** FastAPI/SQLAlchemy, Docker SDK/Compose, React/TypeScript, isolated pytest and browser checks.

### Task1: Dynamic capacity and scheduling

Files: backend/app/resources.py (new), config.py, main.py, scheduler/mock_docker.py, schemas.py; tests/backend/test_host_resources.py and isolated conftest.py.

- [x] Test Docker30CPUs/58820MiB: `assert limits['schedulable_ram_mb']==50628` with8192MiB reserve; reject31CPUs and memory over budget before Docker creation.
- [x] Test FIFO waits when an active job or running workspace consumes budget, then launches after release; invalid legacy queued resources fail clearly, running legacy jobs remain untouched.
- [x] Implement host_limits, capacity(db), validate_request and require_available helpers. Runtime workspace allocation counts only running, matching project/kind. Account active rows STARTING/RUNNING once. Fail closed when Engine capacity cannot be read.
- [x] Guard workspace start under existing advisory lock, including the legacy stopped-container replacement. Reject409 before removing a stopped container if budget unavailable.
- [x] Update schema static maxima to host validation and skip new size checks for duration-only edits of existing running jobs.
- [x] Run isolated tests using existing backend image and read-only staged source mount, no Docker socket/production DB.

### Task2: UI and configuration

Files: frontend/src/main.tsx, types.ts, WorkloadEditor.tsx; compose.yaml, .env.example; tests/frontend/portal_updates.py.

- [x] Return host total/reserved/allocated/available CPU/RAM in /api/resources/gpus.capacity.
- [x] Replace32CPU/64GB UI maxima with detected total CPU/schedulable RAM, display shared host budget and queued resource waiting accurately. Keep existing4CPU/4GB defaults.
- [x] Wire LAB_MEMORY_RESERVE_MB default8192 via Compose and document it; set actual LOCAL_GPU_COUNT=5 only during rollout.
- [x] Build and browser-test limits30CPU/49.44GiB, all5GPU cards, multi-GPU choice and existing permissions.

### Task3: Apply and verify

Files: docs/RESOURCE_UPGRADE_2026-10-15.md; existing apply-latest.sh.

- [x] Snapshot existing containers, member configurations, volumes and .env securely in temporary rollout directory; do not print secrets.
- [x] Copy reviewed source; update only GPU count and memory reserve settings; run apply-latest.sh preserving infrastructure and student containers.
- [x] Verify API/worker/public portal,5free GPU slots and capacity30CPU/57.44GiB; run tiny CUDA work on all five GPUs and an isolated platform validation task.
- [x] Remove only newly-created verification resources, record checks and final resource budget. No global prune, source commit or push.

Completed inline.177isolated unit/script tests,6browser groups,all5GPU CUDA probes,and6live platform checks passed. Original member account fingerprints/mounts and infrastructure/tunnel container identity verified unchanged. No source commit or push.
