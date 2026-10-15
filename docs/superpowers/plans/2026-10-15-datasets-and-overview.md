# Dataset migration and CPU overview Implementation Plan

> **For agentic workers:** Execute this plan inline, using verification-before-completion. Do not delegate, commit, or push.

**Goal:** Move the shared local dataset to NVMe, expose the ELAB SMB dataset to all members, and show available CPU and RAM as overview summary cards.

**Architecture:** Preserve member paths at $HOME/dataset while changing the host bind source. Add an optional second read-only dataset bind and environment variable. Use Docker host capacity budgets already returned by the resources endpoint for overview cards. Mount persistence must not depend on a desktop login and a missing disk/share must never silently turn into a writable empty local directory.

**Tech Stack:** Ubuntu ext4/CIFS, Docker Compose, Python/FastAPI, React/TypeScript.

## Storage migration
- [x] Inspect source aliases, permissions, destination disk identity, running workloads and existing SMB authentication without exposing credentials.
- [x] Copy the resolved source to /media/local/NVME-Storage/dataset with rsync preserving metadata. Verify with a checksum dry run before cutover.
- [x] Configure durable mounts for the NVMe disk and read-only SMB Datasets subtree; validate access as a student UID.
- [x] Update backend/app/config.py, backend/app/storage.py, backend/app/docker_runtime.py, compose.yaml and .env.example to pass the optional shared dataset path and DATASET_ELAB_SHARE.
- [x] Update scripts/host_editor.py and documentation with host physical paths and member home aliases.
- [x] Test dataset mounts and environment expansion; preserve persistent code, volumes, user identities and debug deadlines during container migration.
- [x] Deploy only necessary application services, verify all users, and retain source until the verified cutover is complete.

## CPU and memory overview
- [x] In frontend/src/main.tsx add CPU and RAM cards beside existing GPU/jobs/queue cards, using capacity.available_cpus and capacity.available_ram_mb, total pool, units and allocated/reserved details.
- [x] Extend tests/frontend/portal_updates.py to assert both admin/member cards render the API capacity, including exhausted capacity, and remain readable on mobile.
- [x] Run backend/script tests, frontend build and browser verification, then check live API and deployed UI without changing accounts or task settings.

## Verification
Run isolated backend tests with the existing lab-backend image, binding the staged repository read-only and using SQLite. Run npm build and the existing Playwright portal checks from staging. Record source/destination identity, checksum results, mount options, member UID access and final live resource/API verification in docs/DATASET_MIGRATION_2026-10-15.md.
