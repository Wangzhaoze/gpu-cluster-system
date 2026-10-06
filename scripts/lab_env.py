#!/usr/bin/env python3
"""Read and prepare Compose configuration without sourcing it as shell code."""

import argparse
import os
from pathlib import Path
import secrets
import subprocess

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"


def read_env():
    return dict(
        line.split("=", 1)
        for line in ENV.read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    )


def update_env(changes):
    lines = ENV.read_text().splitlines()
    for key, value in changes.items():
        if any(c in value for c in "\r\n"):
            raise ValueError(f"Invalid multiline value for {key}")
        # Single quotes protect spaces, $, # and backslashes in Compose .env files.
        if any(c in value for c in " $'#\\"):
            value = "'" + value.replace("'", "\\'") + "'"
        replacement = f"{key}={value}"
        for index, line in enumerate(lines):
            if line.startswith(key + "="):
                lines[index] = replacement
                break
        else:
            lines.append(replacement)
    ENV.write_text("\n".join(lines) + "\n")
    ENV.chmod(0o600)


def get_env(key):
    value = read_env()[key]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("\\'", "'")
    return value


def bootstrap(dataset_path=None):
    if not ENV.exists():
        ENV.touch(mode=0o600)
        ENV.write_text((ROOT / ".env.example").read_text())
    ENV.chmod(0o600)
    changes = {}
    for key in ("POSTGRES_PASSWORD", "INITIAL_ADMIN_PASSWORD", "SESSION_SECRET"):
        if get_env(key) == "GENERATE_WITH_BOOTSTRAP":
            changes[key] = secrets.token_hex(24)
    root = get_env("LAB_HOST_ROOT")
    root = ROOT / "runtime" if root == "SET_WITH_BOOTSTRAP" else Path(root)
    if not root.is_absolute():
        raise ValueError("LAB_HOST_ROOT must be a Linux absolute path")
    root = root.resolve()
    for relative in ("users", "datasets/demo", "results", "scratch", "logs/jobs"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    demo = root / "datasets/demo/hello.txt"
    if not demo.exists():
        demo.write_text("GPU Lab demo dataset\n")
    changes["LAB_HOST_ROOT"] = str(root)
    dataset = dataset_path or get_env("DATASET_HOST_PATH")
    if dataset == "SET_WITH_BOOTSTRAP":
        dataset = str(root / "datasets")
    dataset = Path(dataset).expanduser().resolve(strict=True)
    if not dataset.is_dir():
        raise ValueError("Dataset path must be an existing directory")
    changes["DATASET_HOST_PATH"] = str(dataset)
    values = read_env()
    changes["LAB_MONITOR_UID"] = str(os.getuid())
    changes["LAB_MONITOR_GID"] = str(os.getgid())
    defaults = dict(
        line.split("=", 1)
        for line in (ROOT / ".env.example").read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    for key in ("PYTORCH_SOURCE_IMAGE", "LAB_TORCH_IMAGE"):
        if key not in values:
            changes[key] = defaults[key]
    if "LINUX_BOOTSTRAPPED" not in values:
        try:
            gpu_list = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=index", "--format=csv,noheader"],
                text=True, stderr=subprocess.DEVNULL,
            )
            changes["LOCAL_GPU_COUNT"] = str(len(gpu_list.splitlines()))
        except (OSError, subprocess.CalledProcessError):
            pass
        changes["LINUX_BOOTSTRAPPED"] = "true"
    update_env(changes)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("bootstrap", "get", "set"))
    parser.add_argument("key", nargs="?")
    parser.add_argument("value", nargs="?")
    parser.add_argument("--dataset-path")
    args = parser.parse_args()
    if args.action == "bootstrap":
        bootstrap(args.dataset_path)
        print("Linux configuration ready. Credentials are in .env (not printed).")
    elif args.action == "get":
        print(get_env(args.key))
    else:
        update_env({args.key: args.value})
