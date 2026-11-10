# -*- coding: utf-8 -*-
"""Phase 1 OCI runtime: server-owned keys, signed v4.34 import and redacted health.

No browser, SSH/GitHub token, listening socket, Telegram sender or cloud API.
Only user-approved, independently attested v4.34 capture *files* are imported.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import closing
import hashlib
import hmac
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from app_v5.history import HistoryStore
from app_v5.sealed_import import _private_bytes, import_signed_capture

PINNED_SIGNER_SHA256 = (
    "54473a7acab59b546030d1115f03213c4b6ad7128a902206ef94439d117557e6"
)
TRUSTED_SIGNER = (
    Path(__file__).resolve().parents[2] /
    "keys/v434/ed25519_trusted_public.bin"
)
SIGNED_FILES = {
    "encrypted_json": "v434_private_candidate_links.encrypted.json",
    "attestation_json": "v434_capture_attestation.json",
    "summary_json": "v434_secure_links_summary.json",
    "run_status_json": "v434_run_status.json",
    "unique_json": "v433_unique_candidates.json",
}
COMMIT = re.compile(r"[a-f0-9]{40}\Z")
PRIVATE_FILE = "recipient-x25519-private.bin"
HMAC_FILE = "history-hmac-private.bin"
PUBLIC_FILE = "recipient-x25519-public.b64"


def _root(path: str | Path, *, create: bool) -> Path:
    value = Path(path).expanduser()
    if not value.is_absolute() or value.is_symlink():
        raise ValueError("ABSOLUTE_REAL_STATE_DIR_REQUIRED")
    if create:
        value.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not value.is_dir() or value.is_symlink():
        raise ValueError("INVALID_STATE_DIR")
    if os.name == "posix" and stat.S_IMODE(value.stat().st_mode) & 0o077:
        raise ValueError("STATE_DIR_MUST_BE_PRIVATE")
    return value.resolve()


def _dir(root: Path, name: str, *, create: bool) -> Path:
    target = root / name
    if create:
        target.mkdir(mode=0o700, exist_ok=True)
    if not target.is_dir() or target.is_symlink():
        raise ValueError("PRIVATE_SUBDIRECTORY_REQUIRED")
    if os.name == "posix" and stat.S_IMODE(target.stat().st_mode) & 0o077:
        raise ValueError("PRIVATE_SUBDIRECTORY_PERMISSIONS")
    return target


def _new_file(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(content)
    if os.name == "posix":
        path.chmod(0o600)


def _check_signer() -> bytes:
    if TRUSTED_SIGNER.is_symlink() or not TRUSTED_SIGNER.is_file():
        raise ValueError("TRUSTED_SIGNER_MISSING")
    public = TRUSTED_SIGNER.read_bytes()
    if (len(public) != 32 or not hmac.compare_digest(
            hashlib.sha256(public).hexdigest(), PINNED_SIGNER_SHA256)):
        raise ValueError("TRUSTED_SIGNER_FINGERPRINT_MISMATCH")
    return public


def _keyring(root: Path) -> tuple[bytes, bytes, str]:
    keys = _dir(root, "keys", create=False)
    recipient = _private_bytes(keys / PRIVATE_FILE, length=32)
    history = _private_bytes(keys / HMAC_FILE, length=32)
    if hmac.compare_digest(recipient, history):
        raise ValueError("HISTORY_AND_RECIPIENT_KEY_REUSE_FORBIDDEN")
    actual_public = X25519PrivateKey.from_private_bytes(
        recipient
    ).public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    public_string = base64.b64encode(actual_public).decode("ascii")
    saved = keys / PUBLIC_FILE
    if saved.is_symlink() or not saved.is_file():
        raise ValueError("RECIPIENT_PUBLIC_KEY_FILE_MISSING")
    if not hmac.compare_digest(
            saved.read_text(encoding="utf-8").strip(), public_string):
        raise ValueError("RECIPIENT_PUBLIC_KEY_MISMATCH")
    return recipient, history, public_string


def initialize(state_dir: str | Path) -> dict:
    """Create secrets exactly once. Never replace existing keys or DB identity."""
    root = _root(state_dir, create=True)
    keys = _dir(root, "keys", create=True)
    db_folder = _dir(root, "db", create=True)
    _dir(root, "inbox", create=True)
    recipient_path = keys / PRIVATE_FILE
    hmac_path = keys / HMAC_FILE
    exists = [p.exists() or p.is_symlink() for p in
              (recipient_path, hmac_path)]
    if any(exists) and not all(exists):
        raise ValueError("PARTIAL_KEYRING_NO_AUTOMATIC_ROTATION")
    if not any(exists):
        key = X25519PrivateKey.generate()
        secret = key.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
            serialization.NoEncryption()
        )
        _new_file(recipient_path, secret)
        _new_file(hmac_path, os.urandom(32))
        public = key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        _new_file(keys / PUBLIC_FILE, base64.b64encode(public) + b"\n")
    recipient, history, pub = _keyring(root)
    _check_signer()
    db = db_folder / "history.sqlite3"
    HistoryStore(db, history)  # creates/migrates v5 SQLite, binds HMAC continuity
    if os.name == "posix":
        db.chmod(0o600)
    return {
        "state": "OCI_PHASE1_READY",
        "keyring_reused": bool(all(exists)),
        "history_db_present": db.is_file(),
        "signer_fingerprint": PINNED_SIGNER_SHA256[:24],
        "recipient_public_key_present": bool(pub),
        "network_listener": False,
    }


def status(state_dir: str | Path) -> dict:
    root = _root(state_dir, create=False)
    _check_signer()
    _, history, _ = _keyring(root)
    db = _dir(root, "db", create=False) / "history.sqlite3"
    if db.is_symlink() or not db.is_file():
        raise ValueError("HISTORY_DATABASE_NOT_INITIALIZED")
    HistoryStore(db, history)  # validates persisted HMAC key continuity
    with closing(sqlite3.connect(str(db))) as conn:
        counts = {}
        for name in ("search_profiles", "collection_jobs", "listings",
                     "listing_observations", "listing_events",
                     "capture_attestations"):
            counts[name] = conn.execute(
                "SELECT count(*) FROM " + name
            ).fetchone()[0]
        schema = conn.execute("PRAGMA user_version").fetchone()[0]
    return {
        "state": "OCI_PHASE1_HEALTHY",
        "schema_version": schema,
        "signer_fingerprint": PINNED_SIGNER_SHA256[:24],
        "counts": counts,
        "private_data_exported": False,
    }


def import_capture(state_dir: str | Path, bundle_dir: str | Path, *,
                   expected_commit_sha: str, run_id: int,
                   run_attempt: int = 1, dry_run: bool = False) -> dict:
    """Fail closed on exact independent source SHA/run identity and evidence.

    No GitHub API integration yet: obtain commit SHA and run ID from trusted
    GitHub Actions metadata, not from seller pages or the encrypted bundle.
    """
    if (not isinstance(expected_commit_sha, str)
            or not COMMIT.fullmatch(expected_commit_sha)
            or type(run_id) is not int or not 1 <= run_id <= 10**20
            or type(run_attempt) is not int or not 1 <= run_attempt <= 1000):
        raise ValueError("EXACT_GITHUB_RUN_AND_COMMIT_REQUIRED")
    root = _root(state_dir, create=False)
    bundle = Path(bundle_dir).expanduser()
    inbox = _dir(root, "inbox", create=False)
    if (not bundle.is_absolute() or bundle.is_symlink()
            or not bundle.is_dir() or bundle.resolve().parent != inbox):
        raise ValueError("CAPTURE_BUNDLE_MUST_BE_ONE_DIRECT_INBOX_CHILD")
    if os.name == "posix" and stat.S_IMODE(bundle.stat().st_mode) & 0o077:
        raise ValueError("CAPTURE_BUNDLE_NOT_PRIVATE")
    inputs = {}
    for label, filename in SIGNED_FILES.items():
        entry = bundle / filename
        if (entry.is_symlink() or not entry.is_file()
                or not 0 < entry.stat().st_size <= 512 * 1024):
            raise ValueError("CAPTURE_EVIDENCE_MISSING_OR_UNSAFE")
        inputs[label] = entry
    recipient, hmac_secret, _ = _keyring(root)
    trusted = _check_signer()
    params = dict(
        **inputs,
        recipient_private_key=recipient,
        trusted_signer_public_key=trusted,
        profile_id="oci-v434-hdd",
        job_id=f"v434-gh-{run_id}-a{run_attempt}",
        expected_commit_sha=expected_commit_sha,
    )
    check = import_signed_capture(None, **params, dry_run=True)
    if not check["source_authentication_verified"]:
        raise ValueError("UNAUTHENTICATED_IMPORT_FORBIDDEN")
    if dry_run:
        return {
            "state": "SIGNED_DRY_RUN_PASS",
            "validated_candidates": check["validated_candidates"],
            "db_written": False,
        }
    db = _dir(root, "db", create=False) / "history.sqlite3"
    if db.is_symlink() or not db.is_file():
        raise ValueError("HISTORY_DATABASE_NOT_INITIALIZED")
    store = HistoryStore(db, hmac_secret)
    result = import_signed_capture(store, **params)
    return {
        "state": "SIGNED_REVIEWABLE_IMPORT_PASS",
        "imported": result["imported"],
        "already_present": result["already_present"],
        "events_generated": result["events_generated"],
        "source_authentication_verified": True,
        "transaction_state_verified": False,
        "stock_availability_verified": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OCI v5 signed local runtime")
    parser.add_argument("operation", choices=("init", "status", "public-key", "import"))
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--bundle-dir", type=Path)
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--run-attempt", type=int, default=1)
    parser.add_argument("--expected-commit-sha")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    # Never initialize permanent server secrets from GitHub CI.
    if args.operation == "init" and (os.environ.get("CI") or
                                     os.environ.get("GITHUB_ACTIONS")):
        parser.error("OCI_SERVER_ONLY_KEY_INITIALIZATION")
    previous_umask = os.umask(0o077)
    try:
        if args.operation == "init":
            value = initialize(args.state_dir)
        elif args.operation == "status":
            value = status(args.state_dir)
        elif args.operation == "public-key":
            root = _root(args.state_dir, create=False)
            _, _, pub = _keyring(root)
            print(pub)  # X25519 PUBLIC only; never any private key
            return 0
        else:
            if (args.bundle_dir is None or args.run_id is None or
                    args.expected_commit_sha is None):
                parser.error("IMPORT_REQUIRES_BUNDLE_RUN_ID_COMMIT_SHA")
            value = import_capture(
                args.state_dir, args.bundle_dir,
                expected_commit_sha=args.expected_commit_sha,
                run_id=args.run_id, run_attempt=args.run_attempt,
                dry_run=args.dry_run
            )
        import json
        print(json.dumps(value, ensure_ascii=False, sort_keys=True))
        return 0
    except (ValueError, RuntimeError, OSError, TypeError, sqlite3.Error):
        print("OCI_PHASE1_OPERATION_REJECTED", file=sys.stderr)
        return 2
    finally:
        os.umask(previous_umask)


if __name__ == "__main__":
    raise SystemExit(main())
