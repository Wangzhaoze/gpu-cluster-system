# Shared datasets and resource overview — 2026-10-15

## Requested changes

Move the existing `/home/local/dataset` data to the new NVMe filesystem, add the ELAB shared dataset, and show CPU/RAM availability beside the existing GPU/task/queue overview cards.

## Paths and access

| Variable | Ubuntu host | Member workspace / debug / training |
| --- | --- | --- |
| `DATASET` | `/media/local/NVME-Storage/dataset` | `/home/<username>/dataset` (also `/datasets`) |
| `DATASET_ELAB_SHARE` | `/mnt/elab-share/Datasets` | `/home/<username>/dataset_elab_share` (also `/datasets_elab_share`) |

Both dataset binds are read-only in student containers. Existing code using `$DATASET` keeps the same member path. The host aliases `/home/local/dataset` and `/home/local/dataset_elab_share` provide convenient access; the original `/home/local/Desktop/code/Datasets` path will redirect to NVMe after verified cutover.

The NVMe filesystem is ext4 on `/dev/sdb1`, UUID `aa347f5c-9f6d-4d60-b63e-d1fc2370177a`. `/etc/fstab` records it by UUID with systemd automount. The read-only CIFS mount is `//192.168.189.30/elab-share` at `/mnt/elab-share`, exposing only its `Datasets` subtree to students. Its existing authenticated credential is stored root-only in `/etc/samba/credentials-elab-share`; no SMB password is stored in the repository, Compose, student environments, or this document. `/etc/fstab.before-gpu-datasets-20261015` preserves the previous mount configuration.

The share needs network/NAS access when a container starts or reads network files. Systemd automount is configured independently of desktop login. The native administrator editor can start even when the optional SMB server is offline.

## Migration safeguards

Copy with `rsync -aHAX --numeric-ids`, retaining the original source. Compare the complete source/destination with `rsync -aHAXnc --numeric-ids --delete --itemize-changes --stats` (dry run; `--delete` only reports destination extras). Do not cut over or remove the source until checksum verification succeeds.

Private recovery manifests, account fingerprints, original debug start/expiry/GPU assignment and copies of the running containers' unmounted home files are stored under `runtime/backups/dataset-migration-20261015/`. Dataset mountpoints are excluded from home backups. Preserve the original Python and user-state volumes and `/workspace`, `/results`, `/scratch` bind sources. Keep old stopped workspaces intact; their next portal start builds a container with current mappings.

The two running interactive containers require a brief recreation to change Docker binds. Their unmounted home contents (including Conda) are restored at the same home path. Original debug identity, GPU, CPU, RAM and deadline remain unchanged. No training job is running at the preflight checkpoint.

## Overview semantics

Admin/member overview cards display remaining **scheduler allocation budget**, updated through the existing resource polling:

- CPU: `capacity.available_cpus / capacity.total_cpus` threads.
- RAM: `capacity.available_ram_mb / capacity.schedulable_ram_mb`, displayed in GB using the existing 1024 MiB convention.
- The host budget panel details allocations and the 8 GB OS/portal reserve. These figures represent quotas available for allocation, rather than a measurement of instantaneous Linux CPU idle percentage or `MemAvailable`.

## Verification checkpoints

- Full isolated backend/script suite: 183 passed, followed by 2 passing host-editor path/offline-SMB checks after adding the offline regression case.
- TypeScript / Vite production build passed.
- Seven browser regression groups passed, including admin/member resource values, zero remaining capacity, mobile layout, GPU selection, training permissions and announcements. Desktop/mobile screenshots inspected.
- CIFS systemd automount exercised; a container running as UID/GID 2001 listed and read the dataset without write access.
- Local copy complete: 359,002,511,258 file bytes, 585,144 total rsync entries. Full checksum pass completed with zero changed, created or deleted files; 584,576 regular files and 568 directories match in content and metadata. The verification receipt is `runtime/backups/dataset-migration-20261015/dataset-checksum.ok`.
- All four member identities (UIDs 2001, 2006, 2007 and 2009) read both sources through read-only binds in isolated containers.

## Live cutover verification

- Deployed through `./apply-latest.sh --remote`; public portal stayed at https://only-sonic-mercury-ensemble.trycloudflare.com. Infrastructure and tunnel containers were preserved.
- Recreated only the running yinshengwang debug container and yuanxinli workspace. Both read-only dataset binds point to the new sources. Existing workspace/results/scratch paths and Python/user-state volumes are unchanged.
- Compared all 8,091 restored Conda file/link entries against the final pre-cutover home archive. All matched. PyTorch remains 2.7.1+cu128; a CUDA tensor calculation passed on debug GPU 0, and the CPU workspace correctly has no GPU.
- All six account fingerprints, enabled states, quotas and environment template selections are unchanged. The original debug start time, expiry, GPU assignment and requested CPU/RAM are unchanged.
- Live admin and member browser checks passed for six overview cards, including CPU and memory values and all five GPU cards. Temporary verification sessions were removed.
- At this checkpoint the scheduler reported 20 / 30 CPU threads and 23.44 / 49.44 GB memory available for allocation (8 GB system reserve, 8 CPU / 24 GB debug plus 2 CPU / 2 GB workspace allocated).
- Host login shells, new local Bash terminals and the native administrator editor now use both physical dataset paths. Already-open desktop terminals can load `/etc/profile.d/gpu-cluster-datasets.sh` or open a new terminal.
- Stopped workspaces were retained, including their existing writable layers. The next portal start recreates them with the current dataset configuration, using the same persistent user volumes.

The first cold `/api/storage` scan of the existing large student workspace exceeded the acceptance client's 20-second timeout. The requested mounts and variables were verified through direct UID reads, container inspection and the lightweight environment endpoint instead; resource cards update independently of that storage scan. No storage-statistics behavior was changed.

## Completed move

The original 335.6 GiB disk allocation was removed only after the full checksum pass, restored-home checks, all-member UID access tests and live browser verification. `/home/local/Desktop/code/Datasets` and `/home/local/dataset` now resolve to `/media/local/NVME-Storage/dataset`. The redundant old-disk data directory no longer exists. Root filesystem free space after the move was about 581 GiB.

The two stopped rollback containers created for this cutover were removed after verifying they were not referenced by any workload/workspace row. Student persistent volumes and the two previously stopped workspaces remain untouched. Home/Conda, database and configuration recovery backups are retained privately under `runtime/backups/dataset-migration-20261015/`.
