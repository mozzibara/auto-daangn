# -*- coding: utf-8 -*-
"""Pre-OCI, owner-approved v4.34 -> Ed25519 -> REVIEWABLE *ephemeral* test.

Runs exclusively inside the trusted secure-links-v434.yml workflow on main.
No permanent DB, X25519 private key, HMAC secret or plaintext item is uploaded
or printed. This is a proving harness, not a production ingestion service.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from app_v5.history import HistoryStore
from app_v5.sealed_import import _private_bytes, import_signed_capture

REPO = "mozzibara/auto-daangn"
WORKFLOW_REF = REPO + "/.github/workflows/secure-links-v434.yml@refs/heads/main"
PUBLIC_FILE = Path(__file__).resolve().parents[1] / "keys/v434/ed25519_trusted_public.bin"
PINNED_FINGERPRINT = "54473a7acab59b546030d1115f03213c4b6ad7128a902206ef94439d117557e6"
EXPECTED_FILES = (
    "v434_private_candidate_links.encrypted.json",
    "v434_capture_attestation.json",
    "v434_secure_links_summary.json",
    "v434_run_status.json",
    "v433_unique_candidates.json",
)


def _valid_approval_event(env: dict[str, str]) -> bool:
    """Only manual owner dispatch or exact owner-authored issue #1 command."""
    event = env.get("GITHUB_EVENT_NAME")
    if event == "workflow_dispatch":
        return True
    if event != "issue_comment":
        return False
    event_path = env.get("GITHUB_EVENT_PATH")
    if not event_path:
        return False
    try:
        payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
        issue = payload["issue"]
        comment = payload["comment"]
        return (
            payload.get("action") == "created"
            and type(issue.get("number")) is int
            and issue["number"] == 1
            and not issue.get("pull_request")
            and comment.get("body") == "/run-daangn-pre-oci-e2e-v434"
            and comment.get("user", {}).get("login") == "mozzibara"
            and payload.get("sender", {}).get("login") == "mozzibara"
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def require_owner_approved_actions(env: dict[str, str], *,
                                   commit_sha: str) -> tuple[int, int]:
    """Fail closed on PR/push/fork and unauthorized issue comment contexts."""
    if not (
        env.get("GITHUB_ACTIONS") == "true"
        and env.get("GITHUB_REPOSITORY") == REPO
        and env.get("GITHUB_REPOSITORY_OWNER") == "mozzibara"
        and env.get("GITHUB_ACTOR") == "mozzibara"
        and _valid_approval_event(env)
        and env.get("CAPTURE_APPROVAL") == "I_APPROVE_V434_ENCRYPTED_PUBLIC_LINKS"
        and env.get("CAPTURE_TEST_MODE") == "EPHEMERAL_REVIEWABLE_TEST"
        and env.get("GITHUB_REF") == "refs/heads/main"
        and env.get("GITHUB_WORKFLOW_REF") == WORKFLOW_REF
        and re.fullmatch("[a-f0-9]{40}", env.get("GITHUB_SHA", "")) is not None
        and env["GITHUB_SHA"] == commit_sha
    ):
        raise ValueError("OWNER_APPROVED_MAIN_DISPATCH_REQUIRED")
    try:
        run_id = int(env["GITHUB_RUN_ID"])
        attempt = int(env["GITHUB_RUN_ATTEMPT"])
    except (ValueError, KeyError) as exc:
        raise ValueError("INVALID_RUN_CONTEXT") from exc
    if not 1 <= run_id <= 10**20 or not 1 <= attempt <= 1000:
        raise ValueError("INVALID_RUN_CONTEXT")
    return run_id, attempt


def _read_pinned_public() -> bytes:
    raw = PUBLIC_FILE.read_bytes()
    if (len(raw) != 32 or not hmac.compare_digest(
            hashlib.sha256(raw).hexdigest(), PINNED_FINGERPRINT)):
        raise ValueError("PINNED_PUBLIC_KEY_MISMATCH")
    return raw


def generate_ephemeral_recipient(temp_dir: Path, github_env: Path) -> None:
    """Generate throwaway X25519+HMAC; export only recipient public key."""
    temp_dir = Path(temp_dir).resolve()
    temp_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        temp_dir.chmod(0o700)
    recipient = X25519PrivateKey.generate()
    raw = recipient.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
        serialization.NoEncryption()
    )
    for name, secret in (("recipient-private.bin", raw),
                         ("history-hmac.bin", os.urandom(32))):
        target = temp_dir / name
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(secret)
    public = recipient.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    # Public X25519 value only; do not place private bytes in GITHUB_ENV.
    with github_env.open("a", encoding="utf-8") as f:
        f.write("RECIPIENT_PUBLIC_KEY=" +
                base64.b64encode(public).decode("ascii") + "\n")


def audit_ephemeral_capture(output_dir: Path, temp_dir: Path,
                            *, commit_sha: str, run_id: int,
                            attempt: int) -> dict:
    """Authenticate, decrypt, import, read back and replay solely in temp SQLite."""
    output_dir = Path(output_dir).resolve()
    temp_dir = Path(temp_dir).resolve()
    for name in EXPECTED_FILES:
        p = output_dir / name
        if not p.is_file() or p.is_symlink():
            raise ValueError("MISSING_E2E_CAPTURE_EVIDENCE")
    recipient_private = _private_bytes(temp_dir / "recipient-private.bin", length=32)
    hmac_key = _private_bytes(temp_dir / "history-hmac.bin", length=32)
    if recipient_private == hmac_key:
        raise ValueError("EPHEMERAL_KEY_REUSE")
    public = _read_pinned_public()
    job_id = f"v434-gh-{run_id}-a{attempt}"
    params = dict(
        encrypted_json=output_dir / EXPECTED_FILES[0],
        recipient_private_key=recipient_private,
        attestation_json=output_dir / EXPECTED_FILES[1],
        trusted_signer_public_key=public,
        summary_json=output_dir / EXPECTED_FILES[2],
        run_status_json=output_dir / EXPECTED_FILES[3],
        unique_json=output_dir / EXPECTED_FILES[4],
        profile_id="v434-pre-oci-ephemeral",
        job_id=job_id,
        expected_commit_sha=commit_sha,
    )
    preview = import_signed_capture(None, **params, dry_run=True)
    count = preview["validated_candidates"]
    if not preview["source_authentication_verified"] or count < 1:
        raise ValueError("INCONCLUSIVE_NO_REVIEWABLE_CANDIDATES")
    db_path = temp_dir / "test-only.sqlite3"
    store = HistoryStore(db_path, hmac_key)
    imported = import_signed_capture(store, **params)
    ledger = store.get_attestation(job_id)
    if (ledger is None or ledger["run_id"] != run_id
            or ledger["run_attempt"] != attempt
            or ledger["source_commit_sha"] != commit_sha
            or ledger["signer_key_id"] != PINNED_FINGERPRINT[:24]
            or not imported["source_authentication_verified"]
            or imported["imported"] != count
            or imported["events_generated"] != 0):
        raise ValueError("E2E_SOURCE_LEDGER_CONFLICT")
    with closing(sqlite3.connect(db_path)) as conn:
        total, reviewable, price_verified, statuses_unverified, stock_unknown = (
            conn.execute(
                """SELECT COUNT(*),
                          SUM(evidence_level='REVIEWABLE'),
                          SUM(price_verified=1),
                          SUM(primary_status_verified=0 AND transaction_status='NOT_VERIFIED'),
                          SUM(stock_verified=0 AND stock_availability='NOT_OBSERVABLE')
                   FROM listing_observations"""
            ).fetchone()
        )
        meta_count = conn.execute(
            "SELECT COUNT(*) FROM capture_attestations"
        ).fetchone()[0]
        rows_with_source = conn.execute(
            "SELECT COUNT(*) FROM listing_source_evidence"
        ).fetchone()[0]
    if not (total == reviewable == price_verified == statuses_unverified ==
            stock_unknown == rows_with_source == count and meta_count == 1):
        raise ValueError("E2E_REVIEWABLE_ROW_ASSERTION_FAILED")
    repeated = import_signed_capture(store, **params)
    if (repeated["imported"] != 0 or repeated["already_present"] != count
            or repeated["events_generated"] != 0):
        raise ValueError("E2E_IDEMPOTENT_REPLAY_FAILED")
    return {
        "result": "PASS_EPHEMERAL_REVIEWABLE",
        "signed_and_decrypted": True,
        "reviewable_rows": count,
        "unsigned_or_advisory_rows": 0,
        "transaction_status_remains_unverified": True,
        "stock_remains_unobserved": True,
        "idempotent_replay": True,
        "events_generated": 0,
        "database_exported": False,
        "private_keys_exported": False,
    }


def _commit_sha() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True,
        encoding="utf-8", stderr=subprocess.DEVNULL
    ).strip()


def _append_summary(summary_file: str | None, result: dict) -> None:
    if not summary_file:
        return
    lines = [
        "### Pre-OCI v4.34 signed REVIEWABLE integration test",
        "",
        "| Check | Result |",
        "|---|---|",
        "| Authenticated encrypted shortlist | PASS |",
        "| REVIEWABLE rows (temporary SQLite only) | " +
        str(result["reviewable_rows"]) + " |",
        "| Import replay | PASS |",
        "| Transaction/stock truth inferred | No |",
        "| Private item data / key / DB artifact uploaded | No |",
        ""
    ]
    with open(summary_file, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "audit"))
    parser.add_argument("--temp-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        run_id, attempt = require_owner_approved_actions(
            os.environ, commit_sha=_commit_sha()
        )
        if args.mode == "prepare":
            envfile = os.environ.get("GITHUB_ENV")
            if not envfile or args.output_dir is not None:
                raise ValueError("EPHEMERAL_PREPARE_CONTEXT_INVALID")
            generate_ephemeral_recipient(args.temp_dir, Path(envfile))
            print("V434_EPHEMERAL_RECIPIENT_PREPARED")
        else:
            if args.output_dir is None:
                raise ValueError("EPHEMERAL_AUDIT_OUTPUT_DIR_REQUIRED")
            result = audit_ephemeral_capture(
                args.output_dir, args.temp_dir,
                commit_sha=_commit_sha(), run_id=run_id, attempt=attempt
            )
            _append_summary(os.environ.get("GITHUB_STEP_SUMMARY"), result)
            # Aggregate result only; no listing URL/title or secrets.
            print("V434_EPHEMERAL_REVIEWABLE_E2E_PASS")
            print("REVIEWABLE_ROW_COUNT=" + str(result["reviewable_rows"]))
        return 0
    except (ValueError, RuntimeError, TypeError, OSError,
            subprocess.CalledProcessError):
        print("V434_EPHEMERAL_E2E_REJECTED_OR_INCONCLUSIVE", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
