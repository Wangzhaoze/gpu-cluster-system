# GPU telemetry, selection and debug approval plan

> Execute inline in this authorized refinement/deployment session.

**Goal:** Show live per-GPU hardware metrics, honor selected GPU indices in debug/training, and require admin approval for debug sessions beyond ten hours.

**Architecture:** A utility-only NVIDIA monitor writes atomic telemetry snapshots every three seconds. The API merges these with durable allocations and reports unavailable/stale readings explicitly. Schemas persist optional GPU selections; the scheduler waits for exactly those cards and avoids externally occupied free slots. Long debug requests enter AWAITING_APPROVAL without allocating GPUs. Admin approval releases them into the FIFO; rejection/cancellation retains history. Additive Alembic migration preserves existing jobs and sets account limits to ten hours.

**Files:** `infra/gpu-monitor.py`, `backend/app/gpu_telemetry.py`, models/schemas/main/scheduler, additive migration `0002_gpu_selection_approval.py`, Compose/management script, frontend types/forms/dashboard, unit and disposable integration tests, README/validation.

- [x] Write regression tests for GPU selection validation/allocation, telemetry parsing/staleness, ten-hour boundaries and admin-only approval.
- [x] Implement atomic monitor snapshots and a GPU-profile Compose service, plus API telemetry integration and utility-only GPU access.
- [x] Persist GPU selections and approval metadata via additive migration; raise existing and default user debug limits to ten hours.
- [x] Honor exact GPU selection, preserve exclusive allocations/FIFO, and block launch before approval; skip free cards occupied by external compute processes.
- [x] Add member cancellation and admin approve/reject APIs, including disabled-user/quota/template checks and audit events.
- [x] Add detailed live GPU cards, auto/manual/CPU selectors, hour inputs/reasons, and admin approval controls.
- [x] Build/test, back up the database, deploy migration/services without disturbing external GPU jobs or public tunnel.
- [x] Verify live metrics against nvidia-smi, selected GPU UUID inside debug/training, pending/rejected/approved/cancelled requests and public HTTPS/editor access; update docs.

Commands: mounted-source pytest before deployment; `docker compose build backend frontend`; additive migration; GPU profile start; disposable `integration/gpu_features.py`; `./scripts/lab.sh test --gpu`; `./scripts/lab.sh remote-test`; `git diff --check`. Use available cards only and dispose test accounts/resources.

Results: 54 backend tests, seven GPU feature/approval checks, two GPU scheduler checks, seven admin deletion checks and seven public HTTPS/editor/WSS checks passed. Live metrics timestamp refresh was verified publicly. Host PID visibility plus ordinary host UID/GID resolves NVML process enumeration and snapshot permissions; GPU 0/3 external processes remain running. The database was backed up before additive migration, and no test workloads remain.
