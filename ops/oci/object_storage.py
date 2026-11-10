# -*- coding: utf-8 -*-
"""OCI Object Storage: immutable sealed snapshots via instance principals.

No API private keys, auth tokens, pre-authenticated URLs, deletes, or bucket
management. The code verifies actual readback SHA256 before creating a receipt.
Real network client is lazy-loaded; offline CI injects a fake ObjectStore.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Protocol

from ops.oci import backup, runtime

CONFIG_REL = "keys/object-storage.json"
RECPUB_REL = "keys/offsite-recovery-public.b64"
REGION = re.compile(r"[a-z]{2}-[a-z0-9-]{3,40}-[1-9][0-9]*\Z")
IDENT = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")
PREFIX = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*/?\Z")
MAX_REMOTE = backup.MAX_ARCHIVE
OBJECT_TAG = "auto-daangn/oci-backup"


class ObjectStore(Protocol):
    def put_once(self, name: str, contents: bytes) -> None: ...
    def get(self, name: str) -> bytes: ...


class InstancePrincipalObjectStore:
    def __init__(self, *, region: str, namespace: str, bucket: str):
        # Import only on the actual OCI host; CI never contacts IMDS.
        try:
            import oci
        except ImportError as exc:
            raise ValueError("OCI_SDK_NOT_INSTALLED") from exc
        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
        self.client = oci.object_storage.ObjectStorageClient(
            config={"region": region}, signer=signer, timeout=(5, 35)
        )
        self.namespace = namespace
        self.bucket = bucket
        self.service_error = oci.exceptions.ServiceError

    def put_once(self, name: str, contents: bytes) -> None:
        if len(contents) > MAX_REMOTE:
            raise ValueError("OBJECT_STORAGE_UPLOAD_TOO_LARGE")
        try:
            self.client.put_object(
                self.namespace, self.bucket, name, contents,
                content_length=len(contents), if_none_match="*",
            )
        except self.service_error as err:
            # Only permit idempotent readback for already-existing objects.
            # Any other access/retry/availability error must fail closed.
            if err.status != 412:
                raise

    def get(self, name: str) -> bytes:
        response = self.client.get_object(self.namespace, self.bucket, name)
        source = getattr(response.data, "raw", response.data)
        if not hasattr(source, "read"):
            raise ValueError("OBJECT_STORAGE_DOWNLOAD_NOT_STREAM")
        try:
            contents = source.read(MAX_REMOTE + 1)
        finally:
            if hasattr(response.data, "close"):
                response.data.close()
        if type(contents) is not bytes or len(contents) > MAX_REMOTE:
            raise ValueError("OBJECT_STORAGE_DOWNLOAD_TOO_LARGE")
        return contents


def load_settings(state_dir: Path) -> dict:
    root = runtime._root(state_dir, create=False)
    file = root / CONFIG_REL
    if (file.is_symlink() or not file.is_file()
            or file.stat().st_size > 4096
            or (os.name == "posix"
                and stat.S_IMODE(file.stat().st_mode) & 0o077)):
        raise ValueError("OBJECT_STORAGE_CONFIG_MISSING_OR_UNSAFE")
    doc = json.loads(file.read_text(encoding="utf-8"))
    if (type(doc) is not dict
            or set(doc) != {"version", "region", "namespace", "bucket", "prefix"}
            or doc.get("version") != 1
            or not isinstance(doc["region"], str)
            or not REGION.fullmatch(doc["region"])
            or not isinstance(doc["namespace"], str)
            or not IDENT.fullmatch(doc["namespace"])
            or not isinstance(doc["bucket"], str)
            or not IDENT.fullmatch(doc["bucket"])
            or not isinstance(doc["prefix"], str)
            or not PREFIX.fullmatch(doc["prefix"])
            or doc["prefix"].startswith(".")
            or ".." in doc["prefix"].split("/")):
        raise ValueError("INVALID_OBJECT_STORAGE_CONFIG")
    return doc


def _remote_name(settings: dict, archive: Path) -> str:
    name = archive.name
    if (not name.startswith("snapshot-") or not name.endswith(".sealed.json")
            or not re.fullmatch(
                r"snapshot-[0-9]{8}T[0-9]{6}-[a-f0-9]{12}\.sealed\.json", name)):
        raise ValueError("NON_CANONICAL_ENCRYPTED_SNAPSHOT_NAME")
    return settings["prefix"].rstrip("/") + "/" + name


def upload_and_readback(
    state_dir: Path, archive: Path, cloud: ObjectStore, settings: dict,
) -> dict:
    """No production receipt until independent offline restore is established."""
    root = runtime._root(state_dir, create=False)
    parent = runtime._dir(root, "backup", create=False)
    if (archive.is_symlink() or not archive.is_file()
            or archive.resolve().parent != parent
            or not 0 < archive.stat().st_size <= MAX_REMOTE):
        raise ValueError("ENCRYPTED_SNAPSHOT_MUST_BE_IN_PRIVATE_BACKUP_DIR")
    sealed = archive.read_bytes()
    name = _remote_name(settings, archive)
    cloud.put_once(name, sealed)
    downloaded = cloud.get(name)
    digest = hashlib.sha256(sealed).hexdigest()
    if not hmac.compare_digest(hashlib.sha256(downloaded).hexdigest(), digest):
        raise ValueError("OBJECT_STORAGE_READBACK_SHA256_MISMATCH")
    inbox = runtime._dir(root, "inbox", create=False)
    readback = inbox / ("object-storage-readback-" + digest[:24] + ".sealed.json")
    if readback.exists() or readback.is_symlink():
        if (readback.is_symlink() or
                hashlib.sha256(readback.read_bytes()).hexdigest() != digest):
            raise ValueError("OBJECT_STORAGE_READBACK_ALREADY_CONFLICTS")
    else:
        runtime._new_file(readback, downloaded)
    return {"state": "OBJECT_STORAGE_READBACK_VERIFIED",
            "archive_path": str(archive),
            "readback_path": str(readback),
            "object_name": name,
            "sha256": digest,
            "offline_restore_verified": False}


def sync_backup(
    state_dir: Path, cloud: ObjectStore, settings: dict, *,
    now: datetime | None = None, unattended: bool = False,
) -> dict:
    root = runtime._root(state_dir, create=False)
    public = root / RECPUB_REL
    if public.is_symlink() or not public.is_file():
        raise ValueError("OFFLINE_RECOVERY_PUBLIC_KEY_REQUIRED")
    clock = now or datetime.now(timezone.utc)
    if clock.utcoffset() != timedelta(0):
        raise ValueError("UTC_REQUIRED")
    # Unattended operation requires an independent offline restore baseline.
    # This is not allowed to create or extend that baseline.
    if unattended:
        baseline = backup._read_baseline(root, now=clock)
        pub_sha = hashlib.sha256(backup._raw_public(public)).hexdigest()
        if not hmac.compare_digest(pub_sha, baseline["recovery_public_sha256"]):
            raise ValueError("RECOVERY_PUBLIC_KEY_CHANGED_REQUIRES_OFFLINE_RESTORE")
        try:
            gate = backup.require_recent_offsite_backup(root, now=clock)
            when = datetime.fromisoformat(gate["confirmed_at_utc"])
            if clock - when < timedelta(hours=12):
                return {"state": "REMOTE_BACKUP_FRESH_SKIP",
                        "backup_gate": gate["state"]}
        except ValueError:
            pass
    archive = backup.create_backup(root, public, now=clock)
    transferred = upload_and_readback(root, archive, cloud, settings)
    if unattended:
        result = backup.register_cloud_readback_confirmation(
            root, archive, Path(transferred["readback_path"]), public, now=clock
        )
        return {**transferred, **result,
                "offline_restore_verified": False,
                "basis": "RECENT_INDEPENDENT_OFFLINE_RESTORE_BASELINE"}
    return transferred



def probe_existing_remote(state_dir: Path, cloud: ObjectStore,
                          settings: dict) -> dict:
    """Before timer enablement, verify remote has operator-restored snapshot."""
    root = runtime._root(state_dir, create=False)
    baseline = backup._read_baseline(root, now=datetime.now(timezone.utc))
    gate = backup.require_recent_offsite_backup(root)
    receipt = json.loads((root / backup.RECEIPT).read_text(encoding="utf-8"))
    archive = root / "backup" / receipt["snapshot_filename"]
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if not hmac.compare_digest(digest, baseline["archive_sha256"]):
        raise ValueError("OFFLINE_BASELINE_OBJECT_NOT_CURRENT")
    name = _remote_name(settings, archive)
    downloaded = cloud.get(name)
    if not hmac.compare_digest(hashlib.sha256(downloaded).hexdigest(), digest):
        raise ValueError("REMOTE_OBJECT_DOES_NOT_MATCH_BASELINE")
    return {"state": "OBJECT_STORAGE_BASELINE_REMOTE_PROBE_PASS",
            "object_name": name, "sha256": digest, "backup_gate": gate["state"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OCI instance-principal sealed Object Storage backup")
    parser.add_argument("action", choices=("sync", "automatic", "status", "probe"))
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        config = load_settings(args.state_dir)
        if args.action == "status":
            result = {"state": "OBJECT_STORAGE_SETTINGS_VALID",
                      "auth": "instance_principal",
                      "region": config["region"],
                      "namespace": config["namespace"],
                      "bucket": config["bucket"],
                      "network_request_performed": False}
        else:
            client = InstancePrincipalObjectStore(
                region=config["region"], namespace=config["namespace"],
                bucket=config["bucket"],
            )
            if args.action == "probe":
                result = probe_existing_remote(args.state_dir, client, config)
            else:
                result = sync_backup(
                    args.state_dir, client, config,
                    unattended=(args.action == "automatic")
                )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception:
        # OCI auth/HTTP failures must not leak token-derived or network context
        # into the systemd journal. Investigate IAM via separately audited logs.
        print("OCI_OBJECT_STORAGE_BACKUP_REJECTED", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
