#!/usr/bin/env python3
"""Hash precisely the inputs copied into each application image."""
import argparse
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def fingerprint(service, base_id, node_ref=""):
    digest = hashlib.sha256()
    digest.update((service + "\0" + base_id + "\0" + node_ref).encode())
    roots = ["backend", "tests/backend", "tests/integration"] if service == "backend" else ["frontend"]
    ignored = {"__pycache__", ".pytest_cache", "node_modules", "dist"}
    for relative in roots:
        for path in sorted((ROOT / relative).rglob("*")):
            if path.is_file() and not ignored.intersection(path.relative_to(ROOT).parts) and path.suffix != ".pyc":
                digest.update(str(path.relative_to(ROOT)).encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=["backend", "frontend"])
    parser.add_argument("base_id")
    parser.add_argument("--node-ref", default="")
    args = parser.parse_args()
    print(fingerprint(args.service, args.base_id, args.node_ref))
