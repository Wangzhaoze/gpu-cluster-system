# Ubuntu public access and PyTorch environment plan

**Goal:** Keep Ubuntu support only, provide a tested public Cloudflare URL, and make a CUDA 12.8/nvcc/PyTorch environment available for one-GPU, four-hour student debug sessions.

**Architecture:** Keep the existing application and data. Remove obsolete platform scripts/docs and update UI labels. Pull an official PyTorch development image and derive an editor-enabled lab image with a Python interpreter matching its preinstalled torch. Register it as a separate immutable template for fresh students.

- [x] Remove obsolete platform files and references; validate with `rg` and `git diff --check`.
- [x] Start `./scripts/lab.sh up --remote --no-build`; verify public health, authentication, editor routing and WebSockets using remote acceptance.
- [x] Pull `pytorch/pytorch:2.7.1-cuda12.8-cudnn9-devel`; inspect Python/CUDA/nvcc/torch and build `lab-torch-dev:2.7.1-cu128`.
- [x] Verify fresh student venvs import preinstalled torch, register the new immutable template, and document the four-hour/one-GPU UI settings.
- [x] Rebuild/redeploy the Ubuntu application, run backend/local/remote acceptance as appropriate, and confirm data and tunnel remain available.
- [x] When administrator authentication enables the NVIDIA toolkit, run CUDA kernel and tensor checks, switch the idle scheduler to real GPUs and verify an actual scheduled debug session. If host authentication is unavailable, retain the functioning mock deployment and report that specific blocker.

Verification: 29 backend, 11 initial mock, two real-GPU and seven public acceptance checks passed. Official and lab PyTorch images are present; sm_120 CUDA kernel execution and PyTorch matrix multiplication passed on all four RTX 5060 Ti GPUs. After toolkit installation, the cluster was restarted in real GPU mode and a student venv passed CUDA computation with exactly one physical GPU and a four-hour debug expiry. Public administrator login passed. The unused hello-world container was removed; persistent data was retained.
