# Ubuntu Docker Deployment Implementation Plan

> Execute the tasks inline in this session. The user has requested adaptation and deployment.

**Goal:** Run the existing GPU Lab on this Ubuntu host using its Docker engine and verify real application workflows.

**Architecture:** Retain the current Compose services, Docker scheduler and persistent volumes. Add a Bash management command and a Python configuration helper for Linux paths, secrets and portable base-image preparation. Default to mock scheduling until NVIDIA Docker passthrough is verified.

**Tech Stack:** Ubuntu 24.04, Docker Compose, CUDA 12.8.1, Bash, Python, FastAPI, PostgreSQL, React, Traefik.

- [x] Add `scripts/lab.sh` for bootstrap, build/start, stop, logs, tests, GPU checks and scheduler switching. Reuse the existing Compose file and Dockerfiles.
- [x] Add `scripts/lab_env.py` to generate a private `.env`, initialize Linux runtime paths and read/update configuration without executing it as shell code.
- [x] Update `README.md`, `docs/UBUNTU_MIGRATION.md` and the seed error to include the Linux commands.
- [x] Check shell syntax and configuration idempotence, then build and start with `./scripts/lab.sh up`.
- [x] Run `./scripts/lab.sh test` and inspect HTTP health, portal routing and container health.
- [x] Test Docker GPU passthrough. After administrator toolkit installation, CUDA/PyTorch execution passed on all four GPUs and the cluster now runs in real GPU mode.

Deployment verification: 29 backend tests and all 11 mock acceptance checks passed. Fixed the first-start venv/pip race and verified interrupted initialization recovery in a disposable container. Assigned the administrator's default template to the fixed immutable Ubuntu image via the application API.

Physical GPU enablement is complete: the administrator installed the toolkit, the idle scheduler switched to `local-gpu-docker`, and all services restarted with a fresh public tunnel. Real GPU acceptance and a four-hour, one-GPU PyTorch student debug session passed.

Keep credentials out of version control; the administrator explicitly requested their portal password. The administrator authorized removing unused containers: the exited hello-world test container was removed. Persistent data was retained. The host Docker engine was not restarted as part of the application deployment.
