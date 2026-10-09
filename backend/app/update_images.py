"""Explicit application-image cleanup; no global prune or force removal."""
import argparse
import json
import os
from pathlib import Path

from docker.errors import APIError, NotFound
from sqlalchemy import select

from .db import SessionLocal
from .docker_runtime import runtime
from .models import Environment


def write_ledger(path, values, owner=None):
    # The CLI runs as container root; keep files readable by the host updater.
    owner = path.stat() if path.exists() else owner
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(sorted(set(values))))
        temporary.chmod(0o600)
        if owner:
            os.chown(temporary, owner.st_uid, owner.st_gid)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def cleanup_images(candidates, builder_tag=None, builder_tags=()):
    client = runtime.client
    # Compute every reference before removing anything; failure here fails closed.
    container_images = {c.attrs["Image"] for c in client.containers.list(all=True)}
    with SessionLocal() as db:
        template_refs = {env.image for env in db.scalars(select(Environment))}
    template_images = set(template_refs)
    for reference in template_refs:
        try:
            template_images.add(client.images.get(reference).id)
        except NotFound:
            pass
    protected = container_images | template_images
    removed = []
    for identifier in set(candidates):
        try:
            item = client.images.get(identifier)
            if item.id in protected or item.tags:
                print(f"Retained referenced/tagged application image {identifier[:19]}")
                continue
            client.images.remove(item.id, force=False)
            removed.append(item.id)
        except NotFound:
            pass
        except APIError as error:
            print(f"Retained application image {identifier[:19]}: {error.explanation}")
    for builder_tag in set(builder_tags) | ({builder_tag} if builder_tag else set()):
        try:
            item = client.images.get(builder_tag)
            if item.id not in protected:
                # Remove only the temporary tag this script pulled, not other tags.
                client.images.remove(builder_tag, force=False)
                print(f"Removed temporary builder tag {builder_tag}")
        except NotFound:
            pass
        except APIError as error:
            print(f"Retained builder tag {builder_tag}: {error.explanation}")
    return removed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", action="append", default=[])
    parser.add_argument("--builder-tag")
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--builder-ledger", type=Path)
    args = parser.parse_args()
    candidates = args.candidate
    ledger_owner = args.ledger.stat() if args.ledger and args.ledger.exists() else None
    if args.ledger and args.ledger.exists():
        candidates += json.loads(args.ledger.read_text())
    builders = json.loads(args.builder_ledger.read_text()) if args.builder_ledger and args.builder_ledger.exists() else []
    removed = cleanup_images(candidates, args.builder_tag, builders)
    if args.ledger:
        pending = []
        for identifier in set(candidates) - set(removed):
            try:
                if not runtime.client.images.get(identifier).tags:
                    pending.append(identifier)
            except NotFound:
                pass
        write_ledger(args.ledger, pending, ledger_owner)
    if args.builder_ledger:
        pending_builders = []
        for tag in builders:
            try:
                runtime.client.images.get(tag)
                pending_builders.append(tag)
            except NotFound:
                pass
        write_ledger(args.builder_ledger, pending_builders, ledger_owner)
