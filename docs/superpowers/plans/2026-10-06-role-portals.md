# Administrator and Member Portal Implementation Plan

> Execute inline in the authorized existing deployment. Preserve the native local editor, public tunnel, passwords, storage and active student workloads.

**Goal:** Implement TODO.md with distinct admin/member interfaces, public member workload summaries, editable variables and centralized help.

**Architecture:** Keep FastAPI role checks authoritative. Workload lists expose complete records to owners/admins and a field allowlist to other members. Administration updates serialize with the scheduler; existing persistent environment rows and editor containers remain intact. React uses role-specific controls, a help component and CSS theme tokens.

**Tech Stack:** FastAPI, SQLAlchemy/PostgreSQL, React/TypeScript, CSS, Docker Compose, native systemd code-server.

### 1. Role and data contracts
Files: `backend/app/auth.py`, `main.py`, `schemas.py`, `tests/backend/test_role_portals.py`, `test_workspace_paths.py`.
- [x] Test that admins cannot submit/retry workloads, members can see other members' brief records but cannot read logs/details or control their sessions, and member responses omit host paths.
- [x] Add `member_user` for POST jobs/debug/retry. Join member workload lists to User role and return only public summary fields for nonowners; keep access checks on every detail/control endpoint.
- [x] Expose member workspace absolute host path only through admin workspace/storage APIs; add storage column metadata and update prior host-path tests.
Verification: backend suite passes; anonymous and cross-member access denied without performing mutations.

### 2. Variable CRUD and task management
Files: `backend/app/main.py`, `schemas.py`, `tests/backend/test_role_portals.py`, `frontend/src/WorkloadEditor.tsx`.
- [x] Test global/personal scopes, protected keys, own-member update/delete, global/other-user denial, and merge priority `task > user > global`.
- [x] Implement variable DELETE and keep existing persistent rows/compatibility flags while removing the unused flags from the UI. Member global variables are read-only; new/update values synchronize through polling.
- [x] Add admin PATCH jobs/debug. PENDING/AWAITING_APPROVAL records accept validated resource/time/command/workdir changes, retaining queue/approval semantics; RUNNING accepts duration only relative to original start, without recreation. STARTING/terminal/cancelling records reject edits. Serialize changes with scheduler lock and retain owner quotas/pinned environments. Use the optional user clarification if it arrives.
Verification: backend permission/validation/race-state tests and disposable live variable/workload checks pass.

### 3. Role UI, simplicity and help
Files: `frontend/src/main.tsx`, `types.ts`, `styles.css`, new `HelpPage.tsx`, `WorkloadEditor.tsx`.
- [x] Remove admin submission forms/dashboard create/retry; retain management, approval and edit controls. Member other-user rows show summary only, with no log/control/editor actions.
- [x] Keep admin host introduction/status and a single `远程 vscode` link. Keep only the first member workspace panel and use a single clear CPU/GPU line. Move host absolute paths to admin storage with copy/open actions.
- [x] Replace environment flags with scope-aware variable/value forms and edit/delete controls; refresh on updates and concurrent polling.
- [x] Add the last navigation item `帮助`, with ordered role-aware chapters covering previous tutorials and a small accessible inline SVG architecture diagram; remove instructional panels from operational pages and the bottom remote section.
- [x] Give admin green accents corresponding blue hues at the same saturation/lightness; preserve member palette and warning/error colors.
Verification: TypeScript/Vite build and rendered admin/member role checks, including navigation, themes, summary controls and help.

### 4. Deployment and verification
Files: `tests/integration/role_portals.py`, `README.md`, `docs/UBUNTU_VALIDATION.md`, `scripts/lab.sh`.
- [x] Capture private pre-deploy user/workload/container fingerprints. Build and replace only backend/worker/frontend; preserve native editor, proxy, tunnel and student containers.
- [x] Run backend tests and disposable live role/variable/workload acceptance; verify actual container environment injection and clean up test sessions, records, containers and variables.
- [x] Verify public updated bundle/health, native host HTTP/WSS access, GPU telemetry, stable passwords/history and live student sessions. Update docs and push verified code as Lang5Max to the existing branch.

Completed verification: 102 backend tests, 7 disposable public role/container checks, 6 public rendered UI checks and 6 native host HTTP/WSS checks passed. Original data/container fingerprints were verified while accounting for normal student debug expiry and a newly submitted session. The user confirmed queued-resource/running-duration editing scope.
