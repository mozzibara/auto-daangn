# -*- coding: utf-8 -*-
"""OCI offsite-recoverable X25519/AES-GCM SQLite+keyring backup (no cloud upload).

The recovery PRIVATE key must be generated and stored on a separate trusted
machine, never on OCI/GitHub. This does NOT silently certify an offsite copy.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app_v5.history import HistoryStore
from ops.oci import runtime

SCHEMA = "auto-daangn/oci-offsite-backup/v1"
AAD = SCHEMA.encode("ascii")
MAX_DB = 32 * 1024 * 1024
MAX_ARCHIVE = 65 * 1024 * 1024
MAX_AGE = timedelta(days=7)
RECEIPT = "backup/offsite-verified.json"
BASELINE = "backup/offline-restore-baseline.json"
BASELINE_MAX_AGE = timedelta(days=30)


def _utc() -> datetime:
    return datetime.now(timezone.utc)


def _json(data: dict) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _raw_public(path: Path) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise ValueError("RECOVERY_PUBLIC_KEY_MISSING")
    try:
        public = base64.b64decode(path.read_text(encoding="utf-8").strip(),
                                  validate=True)
        if len(public) != 32:
            raise ValueError("WRONG_RECOVERY_KEY")
        X25519PublicKey.from_public_bytes(public)
        return public
    except (ValueError, TypeError) as exc:
        raise ValueError("INVALID_RECOVERY_PUBLIC_KEY") from exc


def generate_recovery_keys(folder: Path) -> dict:
    """Only on the owner's separate OFFLINE machine; never in Actions/OCI."""
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        raise ValueError("RECOVERY_KEY_GENERATION_FORBIDDEN_IN_CI")
    folder = Path(folder).expanduser()
    if not folder.is_absolute() or folder.is_symlink() or not folder.is_dir():
        raise ValueError("ABSOLUTE_EXISTING_OFFLINE_DIR_REQUIRED")
    private = X25519PrivateKey.generate()
    raw = private.private_bytes(serialization.Encoding.Raw,
                                serialization.PrivateFormat.Raw,
                                serialization.NoEncryption())
    pub = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    runtime._new_file(folder / "recovery-private.bin", raw)
    runtime._new_file(folder / "recovery-public.b64",
                      base64.b64encode(pub) + b"\n")
    return {"state": "OFFLINE_RECOVERY_KEYPAIR_CREATED",
            "public_key_sha256": hashlib.sha256(pub).hexdigest(),
            "private_key_should_leave_offline_machine": False}


def _snapshot(db: Path, folder: Path) -> tuple[bytes, int]:
    if not db.is_file() or db.is_symlink():
        raise ValueError("HISTORY_DATABASE_MISSING")
    with tempfile.TemporaryDirectory(dir=folder) as td:
        copy_path = Path(td) / "snapshot.sqlite3"
        # SQLite online backup creates a consistent WAL-aware snapshot.
        with closing(sqlite3.connect(str(db))) as source, closing(
                sqlite3.connect(str(copy_path))) as destination:
            source.backup(destination)
            if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("DATABASE_SNAPSHOT_INTEGRITY_FAILED")
            signed_count = int(destination.execute(
                "SELECT count(*) FROM capture_attestations").fetchone()[0])
        if copy_path.stat().st_size > MAX_DB:
            raise ValueError("DATABASE_SNAPSHOT_EXCEEDS_LIMIT")
        return copy_path.read_bytes(), signed_count


def _derive(shared: bytes, ephemeral_public: bytes, recipient_public: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=AAD + b"\x00" + ephemeral_public + recipient_public).derive(shared)


def _check_backup_root(state_dir: Path) -> tuple[Path, Path]:
    root = runtime._root(state_dir, create=False)
    folder = runtime._dir(root, "backup", create=True)
    return root, folder


def create_backup(state_dir: Path, recovery_public_key: Path,
                  *, now: datetime | None = None) -> Path:
    root, folder = _check_backup_root(state_dir)
    _, history_secret, current_public = runtime._keyring(root)
    recipient_secret = runtime._private_bytes(
        root / "keys" / runtime.PRIVATE_FILE, length=32)
    backup_pub = _raw_public(Path(recovery_public_key))
    if hmac.compare_digest(backup_pub, base64.b64decode(current_public)):
        raise ValueError("RECOVERY_KEY_MUST_BE_INDEPENDENT_OF_OCI_RECIPIENT")
    db = root / "db" / "history.sqlite3"
    HistoryStore(db, history_secret)
    contents, signed_count = _snapshot(db, folder)
    clock = now or _utc()
    if clock.utcoffset() != timedelta(0):
        raise ValueError("UTC_REQUIRED")
    payload = _json({
        "schema": SCHEMA,
        "created_utc": clock.isoformat(timespec="microseconds"),
        "sqlite_b64": base64.b64encode(contents).decode("ascii"),
        "recipient_private_b64": base64.b64encode(recipient_secret).decode("ascii"),
        "history_hmac_b64": base64.b64encode(history_secret).decode("ascii"),
        "recipient_public_b64": current_public,
        "attestation_count_snapshot": signed_count,
    })
    ephemeral = X25519PrivateKey.generate()
    eph_public = ephemeral.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    aes_key = _derive(ephemeral.exchange(
        X25519PublicKey.from_public_bytes(backup_pub)), eph_public, backup_pub)
    nonce = os.urandom(12)
    sealed = {
        "schema": SCHEMA,
        "recipient_fingerprint": hashlib.sha256(backup_pub).hexdigest(),
        "ephemeral_public": base64.b64encode(eph_public).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(
            AESGCM(aes_key).encrypt(nonce, payload,
                                    AAD + b"/" + str(signed_count).encode("ascii"))).decode("ascii"),
        "snapshot_attestations": signed_count,
    }
    encoded = _json(sealed)
    if len(encoded) > MAX_ARCHIVE:
        raise ValueError("BACKUP_ARCHIVE_TOO_LARGE")
    destination = folder / (
        "snapshot-" + clock.strftime("%Y%m%dT%H%M%S") + "-"
        + hashlib.sha256(encoded).hexdigest()[:12] + ".sealed.json")
    runtime._new_file(destination, encoded)
    return destination


def inspect_backup(archive_path: Path, recovery_private_key: Path,
                   *, scratch: Path | None = None) -> dict:
    """Read-only restore verification; no writes to live OCI state."""
    file = Path(archive_path)
    if (file.is_symlink() or not file.is_file()
            or file.stat().st_size > MAX_ARCHIVE):
        raise ValueError("INVALID_BACKUP_ARCHIVE")
    private = runtime._private_bytes(recovery_private_key, length=32)
    try:
        envelope = json.loads(file.read_text(encoding="utf-8"))
        if (type(envelope) is not dict or set(envelope) != {
                "schema", "recipient_fingerprint", "ephemeral_public",
                "nonce", "ciphertext", "snapshot_attestations"}
                or envelope["schema"] != SCHEMA
                or type(envelope["snapshot_attestations"]) is not int
                or envelope["snapshot_attestations"] < 0):
            raise ValueError("INVALID_BACKUP_ENVELOPE")
        public = X25519PrivateKey.from_private_bytes(private).public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        if not hmac.compare_digest(envelope["recipient_fingerprint"],
                                   hashlib.sha256(public).hexdigest()):
            raise ValueError("WRONG_OFFLINE_RECOVERY_KEY")
        eph_public = base64.b64decode(envelope["ephemeral_public"], validate=True)
        nonce = base64.b64decode(envelope["nonce"], validate=True)
        ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
        if len(eph_public) != 32 or len(nonce) != 12:
            raise ValueError("INVALID_BACKUP_CRYPTOPARAMS")
        shared = X25519PrivateKey.from_private_bytes(private).exchange(
            X25519PublicKey.from_public_bytes(eph_public))
        payload = json.loads(AESGCM(_derive(shared, eph_public, public)).decrypt(
            nonce, ciphertext,
            AAD + b"/" + str(envelope["snapshot_attestations"]).encode("ascii")).decode("utf-8"))
        if (type(payload) is not dict or set(payload) != {
                "schema", "created_utc", "sqlite_b64", "recipient_private_b64",
                "history_hmac_b64", "recipient_public_b64",
                "attestation_count_snapshot"} or payload["schema"] != SCHEMA
                or payload["attestation_count_snapshot"] != envelope[
                    "snapshot_attestations"]):
            raise ValueError("INVALID_BACKUP_PAYLOAD")
        db = base64.b64decode(payload["sqlite_b64"], validate=True)
        key = base64.b64decode(payload["history_hmac_b64"], validate=True)
        recipient = base64.b64decode(payload["recipient_private_b64"], validate=True)
        expected_pub = X25519PrivateKey.from_private_bytes(recipient).public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        if (len(db) > MAX_DB or len(key) != 32 or len(recipient) != 32
                or not hmac.compare_digest(
                    base64.b64decode(payload["recipient_public_b64"], validate=True),
                    expected_pub)):
            raise ValueError("BACKUP_KEYRING_MISMATCH")
        with tempfile.TemporaryDirectory(dir=scratch) as td:
            target = Path(td) / "restore.sqlite3"
            target.write_bytes(db)
            with closing(sqlite3.connect(str(target))) as conn:
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("BACKUP_DATABASE_CORRUPT")
            verified = HistoryStore(target, key)
            if _count_captures(target) != payload["attestation_count_snapshot"]:
                raise ValueError("SNAPSHOT_ATTESTATION_COUNT_MISMATCH")
            if verified.path != target:
                raise ValueError("RESTORE_PATH_MISMATCH")
        return {
            "state": "OFFLINE_RESTORE_VERIFIED",
            "archive_sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
            "key_fingerprint": hashlib.sha256(expected_pub).hexdigest()[:24],
            "sqlite_bytes": len(db),
            "created_utc": payload["created_utc"],
            "live_server_modified": False,
        }
    except (KeyError, TypeError, UnicodeError, ValueError, sqlite3.Error, InvalidTag) as exc:
        raise ValueError("OFFLINE_RESTORE_VERIFICATION_FAILED") from exc


def register_offsite_confirmation(state_dir: Path, local_backup: Path,
                                  returned_offsite_copy: Path, *,
                                  operator_verified_offline_restore: bool,
                                  now: datetime | None = None) -> dict:
    """Operator attests independently testing full recovery OUTSIDE OCI.

    Compare actual downloaded ciphertext to local encrypted backup; no secret
    or GitHub token crosses the service boundary. Not a remote-provider proof.
    """
    if operator_verified_offline_restore is not True:
        raise ValueError("OFFSITE_RESTORE_OPERATOR_CONFIRMATION_REQUIRED")
    root, folder = _check_backup_root(state_dir)
    local = Path(local_backup)
    returned = Path(returned_offsite_copy)
    if (local.is_symlink() or not local.is_file()
            or local.resolve().parent != folder
            or returned.is_symlink() or not returned.is_file()
            or returned.resolve() == local.resolve()
            or returned.stat().st_size > MAX_ARCHIVE):
        raise ValueError("OFFSITE_COPY_MUST_BE_SEPARATELY_DOWNLOADED")
    if local.stat().st_size > MAX_ARCHIVE:
        raise ValueError("BACKUP_ARCHIVE_TOO_LARGE")
    try:
        envelope = json.loads(local.read_text(encoding="utf-8"))
        signed_count = envelope["snapshot_attestations"]
        if (type(signed_count) is not int or signed_count < 0
                or envelope.get("schema") != SCHEMA):
            raise ValueError("UNVERIFIED_SNAPSHOT_COUNT")
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise ValueError("UNVERIFIED_SNAPSHOT_COUNT") from None
    digest = hashlib.sha256(local.read_bytes()).hexdigest()
    if not hmac.compare_digest(hashlib.sha256(returned.read_bytes()).hexdigest(),
                               digest):
        raise ValueError("OFFSITE_CIPHERTEXT_MISMATCH")
    clock = now or _utc()
    if clock.utcoffset() != timedelta(0):
        raise ValueError("UTC_REQUIRED")
    # This records the CURRENT local DB state for operational freshness checks.
    # It does not attest that an external provider actually stored the object.
    db = root / "db" / "history.sqlite3"
    count = _count_captures(db)
    if count != signed_count:
        raise ValueError("SNAPSHOT_IS_OLDER_THAN_CURRENT_DATABASE")
    receipt = {
        "schema": SCHEMA,
        "confirmed_at_utc": clock.isoformat(timespec="microseconds"),
        "archive_sha256": digest,
        "snapshot_filename": local.name,
        "attestation_count_at_backup": count,
        "offline_restore_operator_confirmed": True,
    }
    baseline = {
        "schema": SCHEMA,
        "verified_at_utc": receipt["confirmed_at_utc"],
        "recovery_public_sha256": envelope["recipient_fingerprint"],
        "archive_sha256": digest,
    }
    # Only an explicit operator-confirmed OFFLINE recovery can set baseline.
    _atomic_receipt(folder, root / BASELINE, baseline)
    _atomic_receipt(folder, root / RECEIPT, receipt)
    return {"state": "OFFSITE_BACKUP_CONFIRMED", "archive_sha256": digest,
            "attestation_count_at_backup": count}



def _atomic_receipt(folder: Path, target: Path, contents: dict) -> None:
    tmp = folder / ("receipt-" + os.urandom(8).hex() + ".tmp")
    runtime._new_file(tmp, _json(contents))
    os.replace(tmp, target)


def _read_baseline(root: Path, *, now: datetime) -> dict:
    path = root / BASELINE
    if path.is_symlink() or not path.is_file():
        raise ValueError("INDEPENDENT_OFFLINE_RESTORE_BASELINE_REQUIRED")
    baseline = json.loads(path.read_text(encoding="utf-8"))
    if (type(baseline) is not dict or set(baseline) != {
            "schema", "verified_at_utc", "recovery_public_sha256", "archive_sha256"}
            or baseline["schema"] != SCHEMA
            or not isinstance(baseline["recovery_public_sha256"], str)
            or len(baseline["recovery_public_sha256"]) != 64):
        raise ValueError("INVALID_OFFLINE_RESTORE_BASELINE")
    validated_at = datetime.fromisoformat(baseline["verified_at_utc"])
    if (validated_at.utcoffset() != timedelta(0)
            or now.utcoffset() != timedelta(0)
            or now < validated_at
            or now - validated_at > BASELINE_MAX_AGE):
        raise ValueError("OFFLINE_RESTORE_BASELINE_EXPIRED")
    return baseline


def register_cloud_readback_confirmation(
        state_dir: Path, local_backup: Path, returned_offsite_copy: Path,
        recovery_public_key: Path, *, now: datetime | None = None) -> dict:
    """Automated readback after independent offline restore baseline.

    Compares the actual cloud readback to the snapshot and current signed
    capture count. Does NOT perform fresh offline decryption; 30-day baseline
    must be periodically renewed by an operator.
    """
    root, folder = _check_backup_root(state_dir)
    clock = now or _utc()
    baseline = _read_baseline(root, now=clock)
    pub_sha = hashlib.sha256(_raw_public(Path(recovery_public_key))).hexdigest()
    if not hmac.compare_digest(pub_sha, baseline["recovery_public_sha256"]):
        raise ValueError("RECOVERY_PUBLIC_KEY_CHANGED_REQUIRES_OFFLINE_RESTORE")
    local, returned = Path(local_backup), Path(returned_offsite_copy)
    if (local.is_symlink() or returned.is_symlink()
            or not local.is_file() or not returned.is_file()
            or local.resolve().parent != folder
            or returned.resolve() == local.resolve()
            or not 0 < local.stat().st_size <= MAX_ARCHIVE
            or not 0 < returned.stat().st_size <= MAX_ARCHIVE):
        raise ValueError("INVALID_CLOUD_READBACK_INPUT")
    digest = hashlib.sha256(local.read_bytes()).hexdigest()
    if not hmac.compare_digest(digest, hashlib.sha256(returned.read_bytes()).hexdigest()):
        raise ValueError("CLOUD_READBACK_HASH_MISMATCH")
    envelope = json.loads(local.read_text(encoding="utf-8"))
    if (type(envelope) is not dict or envelope.get("schema") != SCHEMA
            or envelope.get("recipient_fingerprint") != pub_sha
            or type(envelope.get("snapshot_attestations")) is not int
            or envelope["snapshot_attestations"] < 0):
        raise ValueError("INVALID_CLOUD_BACKUP_ENVELOPE")
    count = _count_captures(root / "db" / "history.sqlite3")
    if count != envelope["snapshot_attestations"]:
        raise ValueError("CLOUD_BACKUP_DOES_NOT_MATCH_CURRENT_DB")
    receipt = {
        "schema": SCHEMA, "confirmed_at_utc": clock.isoformat(timespec="microseconds"),
        "archive_sha256": digest, "snapshot_filename": local.name,
        "attestation_count_at_backup": count,
        "offline_restore_operator_confirmed": False,
        "verification_mode": "CLOUD_READBACK_WITH_OFFLINE_BASELINE",
        "baseline_verified_at_utc": baseline["verified_at_utc"],
    }
    _atomic_receipt(folder, root / RECEIPT, receipt)
    return {"state": "CLOUD_READBACK_BACKUP_CONFIRMED",
            "attestation_count_at_backup": count,
            "offline_recovery_test_performed_now": False}


def _count_captures(db: Path) -> int:
    with closing(sqlite3.connect(str(db))) as conn:
        return int(conn.execute("SELECT count(*) FROM capture_attestations").fetchone()[0])


def require_recent_offsite_backup(state_dir: Path, *, now: datetime | None = None) -> dict:
    root, folder = _check_backup_root(state_dir)
    receipt_file = root / RECEIPT
    if receipt_file.is_symlink() or not receipt_file.is_file():
        raise ValueError("OFFSITE_VERIFIED_BACKUP_REQUIRED")
    receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    common = {"schema", "confirmed_at_utc", "archive_sha256", "snapshot_filename",
              "attestation_count_at_backup", "offline_restore_operator_confirmed"}
    if type(receipt) is not dict or receipt.get("schema") != SCHEMA:
        raise ValueError("INVALID_OFFSITE_BACKUP_RECEIPT")
    if receipt.get("offline_restore_operator_confirmed") is True:
        if set(receipt) != common:
            raise ValueError("INVALID_OFFSITE_BACKUP_RECEIPT")
    elif (receipt.get("offline_restore_operator_confirmed") is False
          and receipt.get("verification_mode") == "CLOUD_READBACK_WITH_OFFLINE_BASELINE"
          and set(receipt) == common | {"verification_mode", "baseline_verified_at_utc"}):
        baseline = _read_baseline(root, now=now or _utc())
        if receipt["baseline_verified_at_utc"] != baseline["verified_at_utc"]:
            raise ValueError("CLOUD_RECEIPT_OFFLINE_BASELINE_MISMATCH")
        recovery_pub = _raw_public(root / "keys" / "offsite-recovery-public.b64")
        if not hmac.compare_digest(hashlib.sha256(recovery_pub).hexdigest(),
                                   baseline["recovery_public_sha256"]):
            raise ValueError("RECOVERY_PUBLIC_KEY_CHANGED_REQUIRES_OFFLINE_RESTORE")
    else:
        raise ValueError("INVALID_OFFSITE_BACKUP_RECEIPT")
    archive = folder / receipt["snapshot_filename"]
    if (archive.is_symlink() or not archive.is_file()
            or archive.stat().st_size > MAX_ARCHIVE
            or archive.resolve().parent != folder
            or not hmac.compare_digest(hashlib.sha256(archive.read_bytes()).hexdigest(),
                                       receipt["archive_sha256"])):
        raise ValueError("CONFIRMED_BACKUP_ARCHIVE_CHANGED")
    when = datetime.fromisoformat(receipt["confirmed_at_utc"])
    clock = now or _utc()
    if (when.utcoffset() != timedelta(0) or clock.utcoffset() != timedelta(0)
            or clock < when or clock - when > MAX_AGE):
        raise ValueError("OFFSITE_BACKUP_CONFIRMATION_EXPIRED")
    if _count_captures(root / "db" / "history.sqlite3") > receipt[
            "attestation_count_at_backup"]:
        raise ValueError("DATABASE_HAS_UNBACKED_SIGNED_CAPTURES")
    return {"state": "OFFSITE_BACKUP_GATE_PASS",
            "confirmed_at_utc": receipt["confirmed_at_utc"],
            "attestation_count_at_backup": receipt["attestation_count_at_backup"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline X25519 encrypted backup and recovery checks")
    parser.add_argument("action", choices=("generate-recovery", "create", "verify",
                                            "confirm-offsite", "gate"))
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--offline-dir", type=Path)
    parser.add_argument("--recovery-public", type=Path)
    parser.add_argument("--recovery-private", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--returned-offsite-copy", type=Path)
    parser.add_argument("--operator-verified-offline-restore", action="store_true")
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        if args.action == "generate-recovery":
            if args.offline_dir is None:
                raise ValueError("OFFLINE_DIR_REQUIRED")
            result = generate_recovery_keys(args.offline_dir)
        elif args.action == "create":
            if args.state_dir is None or args.recovery_public is None:
                raise ValueError("BACKUP_STATE_AND_PUBLIC_KEY_REQUIRED")
            path = create_backup(args.state_dir, args.recovery_public)
            result = {"state": "ENCRYPTED_BACKUP_CREATED",
                      "archive_path": str(path),
                      "archive_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        elif args.action == "verify":
            if args.archive is None or args.recovery_private is None:
                raise ValueError("BACKUP_AND_OFFLINE_RECOVERY_PRIVATE_REQUIRED")
            result = inspect_backup(args.archive, args.recovery_private)
        elif args.action == "confirm-offsite":
            if (args.state_dir is None or args.archive is None
                    or args.returned_offsite_copy is None):
                raise ValueError("OFFSITE_VERIFICATION_INPUTS_REQUIRED")
            result = register_offsite_confirmation(
                args.state_dir, args.archive, args.returned_offsite_copy,
                operator_verified_offline_restore=
                args.operator_verified_offline_restore)
        else:
            if args.state_dir is None:
                raise ValueError("STATE_DIR_REQUIRED")
            result = require_recent_offsite_backup(args.state_dir)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, TypeError, sqlite3.Error):
        print("OCI_BACKUP_OPERATION_REJECTED", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
