# -*- coding: utf-8 -*-
"""Ed25519 producer attestation for owner-approved v4.34 sealed captures.

The X25519/AES-GCM envelope authenticates ciphertext integrity to a recipient
but does not authenticate its producer. A pinned, independent Ed25519 signer
attests to the *exact ciphertext bytes* and privacy-bounded v4.34 gate reports.

Trust model: this signature authenticates the configured signer and its
asserted gate checks, not the marketplace or its seller. It cannot prove
direct primary-item UI statuses absent from the capture payload.
"""
from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey
)
from scripts.run_status_study_v429_checked import SUCCESS

CONTEXT = "auto-daangn/v5/v434-producer-attestation/v1"
REPOSITORY = "mozzibara/auto-daangn"
WORKFLOW = "secure-links-v434.yml"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
FILES = {
    "encrypted_sha256": "v434_private_candidate_links.encrypted.json",
    "summary_sha256": "v434_secure_links_summary.json",
    "run_status_sha256": "v434_run_status.json",
    "unique_sha256": "v433_unique_candidates.json",
    "study_sha256": "v429_public_status_results.json",
}
CHECKED_FLAGS = {
    "robots_allowed": True, "survey_complete": True, "dedup_complete": True,
    "sealed_complete": True, "strict_recommendations_approved": 0
}


def _canonical(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _utc(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("INVALID_CAPTURE_TIMESTAMP")
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as ex:
        raise ValueError("INVALID_CAPTURE_TIMESTAMP") from ex
    if date.tzinfo is None or date.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError("CAPTURE_TIMESTAMP_NOT_UTC")
    return date.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _data(folder: Path, name: str, max_bytes: int = 512 * 1024) -> bytes:
    p = folder / name
    if not p.is_file() or p.is_symlink() or p.stat().st_size > max_bytes:
        raise ValueError("MISSING_OR_OVERSIZED_CAPTURE_FILE")
    return p.read_bytes()


def _json(raw: bytes) -> dict:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ValueError("INVALID_CAPTURE_JSON") from exc
    if type(value) is not dict:
        raise ValueError("INVALID_CAPTURE_OBJECT")
    return value


def _validate_capture(folder: Path) -> tuple[dict, dict]:
    envelope = _json(_data(folder, FILES["encrypted_sha256"]))
    summary = _json(_data(folder, FILES["summary_sha256"]))
    run = _json(_data(folder, FILES["run_status_sha256"]))
    unique = _json(_data(folder, FILES["unique_sha256"]))
    study = _json(_data(folder, FILES["study_sha256"]))
    robots = _json(_data(folder, "v434_robots_decision.json"))
    evaluation = unique.get("evaluation")
    survey = study.get("evaluation")
    if type(evaluation) is not dict or type(survey) is not dict:
        raise ValueError("INCOMPLETE_SIGNING_EVIDENCE")
    if not (
        robots.get("allowed") is True
        and run.get("status") == "SEALED_CAPTURE_COMPLETE"
        and run.get("attempted_live") is True
        and run.get("encrypted_links_written") is True
        and run.get("approval_required") is True
        and run.get("strict_listing_approved_count") == 0
        and run.get("max_source_visits") == 9
        and run.get("max_control_visits") == 6
        and survey.get("survey_complete") is True
        and survey.get("status") in SUCCESS
        and evaluation.get("dedup_complete") is True
        and summary.get("status") == "SEALED_PRIVATE_CANDIDATES_COMPLETE"
        and summary.get("full_recommendations_approved") == 0
        and summary.get("key_material_on_github") is False
        and summary.get("plaintext_urls_or_titles_in_artifacts") is False
        and envelope.get("version") == "4.34"
        and envelope.get("plaintext_not_archived") is True
        and envelope.get("envelope") == "X25519-HKDF-SHA256-AES256-GCM"
        and type(summary.get("linked_unique_candidates")) is int
        and summary["linked_unique_candidates"] >= 0
        and summary.get("unique_candidates") == run.get("unique_candidates")
        and summary.get("linked_unique_candidates") == run.get("linked_unique_candidates")
        and summary.get("quarantined_title_groups") == run.get("quarantined_title_groups")
        and summary["linked_unique_candidates"] <= summary["unique_candidates"] <= 9
    ):
        raise ValueError("SIGNER_REJECTED_INCOMPLETE_CAPTURE")
    return summary, run


def signing_public_key(private_raw: bytes) -> bytes:
    if type(private_raw) is not bytes or len(private_raw) != 32:
        raise ValueError("INVALID_ED25519_PRIVATE_KEY")
    return Ed25519PrivateKey.from_private_bytes(private_raw).public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


def sign_capture(folder: Path, private_raw: bytes, *, run_id: int,
                 run_attempt: int, commit_sha: str,
                 repository: str = REPOSITORY, workflow: str = WORKFLOW) -> dict:
    """Sign a verified completed capture; no listing plaintext is serialized."""
    if (type(run_id) is not int or not 1 <= run_id <= 10**20
            or type(run_attempt) is not int or not 1 <= run_attempt <= 1000
            or not isinstance(commit_sha, str) or not HEX40.fullmatch(commit_sha)
            or repository != REPOSITORY or workflow != WORKFLOW):
        raise ValueError("INVALID_PRODUCER_CONTEXT")
    folder = Path(folder)
    _summary, run = _validate_capture(folder)
    pub = signing_public_key(private_raw)
    payload = {
        "context": CONTEXT,
        "repository": repository,
        "workflow": workflow,
        "commit_sha": commit_sha,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "capture_ended_utc": _utc(run["ended_utc"]),
        "signer_key_id": hashlib.sha256(pub).hexdigest()[:24],
        "checks": dict(CHECKED_FLAGS),
    }
    for label, filename in FILES.items():
        payload[label] = hashlib.sha256(_data(folder, filename)).hexdigest()
    signature = Ed25519PrivateKey.from_private_bytes(private_raw).sign(
        CONTEXT.encode("ascii") + b"\x00" + _canonical(payload)
    )
    return {"payload": payload, "signature_base64":
            base64.b64encode(signature).decode("ascii")}


def verify_attestation(attestation: dict, trusted_pub: bytes, *,
                       encrypted_bytes: bytes,
                       summary_bytes: bytes, run_bytes: bytes,
                       unique_bytes: bytes, expected_commit_sha: str | None = None) -> dict:
    """Fail closed; return authenticated producer claim without private contents."""
    if type(trusted_pub) is not bytes or len(trusted_pub) != 32:
        raise ValueError("INVALID_TRUSTED_ED25519_PUBLIC_KEY")
    if type(attestation) is not dict or set(attestation) != {
        "payload", "signature_base64"}:
        raise ValueError("INVALID_ATTESTATION")
    payload = attestation["payload"]
    if type(payload) is not dict or set(payload) != {
        "context", "repository", "workflow", "commit_sha", "run_id", "run_attempt",
        "capture_ended_utc", "signer_key_id", "checks", *FILES.keys()
    }:
        raise ValueError("INVALID_ATTESTATION_FIELDS")
    if not (
        payload["context"] == CONTEXT
        and payload["repository"] == REPOSITORY
        and payload["workflow"] == WORKFLOW
        and type(payload["run_id"]) is int and 1 <= payload["run_id"] <= 10**20
        and type(payload["run_attempt"]) is int and 1 <= payload["run_attempt"] <= 1000
        and type(payload["commit_sha"]) is str and HEX40.fullmatch(payload["commit_sha"])
        and payload["signer_key_id"] == hashlib.sha256(trusted_pub).hexdigest()[:24]
        and type(payload["checks"]) is dict and payload["checks"] == CHECKED_FLAGS
        and _utc(payload["capture_ended_utc"]) == payload["capture_ended_utc"]
        and (expected_commit_sha is None or
             expected_commit_sha == payload["commit_sha"])
        and all(type(payload[label]) is str and HEX64.fullmatch(payload[label])
                for label in FILES)
    ):
        raise ValueError("UNTRUSTED_ATTESTATION_CONTEXT")
    signatures = attestation["signature_base64"]
    if type(signatures) is not str or len(signatures) > 128:
        raise ValueError("INVALID_ATTESTATION_SIGNATURE")
    try:
        raw = base64.b64decode(signatures, validate=True)
        if len(raw) != 64:
            raise ValueError("INVALID_SIGNATURE_LENGTH")
        Ed25519PublicKey.from_public_bytes(trusted_pub).verify(
            raw, CONTEXT.encode("ascii") + b"\x00" + _canonical(payload)
        )
    except (ValueError, binascii.Error, InvalidSignature) as exc:
        raise ValueError("PRODUCER_SIGNATURE_VERIFICATION_FAILED") from exc
    for label, content in (
        ("encrypted_sha256", encrypted_bytes),
        ("summary_sha256", summary_bytes),
        ("run_status_sha256", run_bytes),
        ("unique_sha256", unique_bytes),
    ):
        if type(content) is not bytes or not hmac.compare_digest(
            hashlib.sha256(content).hexdigest(), payload[label]
        ):
            raise ValueError("ATTESTED_FILE_HASH_MISMATCH")
    summary, run, unique = (_json(summary_bytes), _json(run_bytes),
                            _json(unique_bytes))
    evaluation = unique.get("evaluation")
    if not (
        summary.get("status") == "SEALED_PRIVATE_CANDIDATES_COMPLETE"
        and type(summary.get("linked_unique_candidates")) is int
        and summary.get("full_recommendations_approved") == 0
        and summary.get("key_material_on_github") is False
        and summary.get("plaintext_urls_or_titles_in_artifacts") is False
        and run.get("status") == "SEALED_CAPTURE_COMPLETE"
        and run.get("encrypted_links_written") is True
        and run.get("strict_listing_approved_count") == 0
        and run.get("linked_unique_candidates") == summary["linked_unique_candidates"]
        and run.get("unique_candidates") == summary.get("unique_candidates")
        and type(evaluation) is dict and evaluation.get("dedup_complete") is True
    ):
        raise ValueError("ATTESTED_GATE_REPORT_INCONSISTENT")
    if _utc(run.get("ended_utc")) != payload["capture_ended_utc"]:
        raise ValueError("ATTESTED_RUN_TIME_MISMATCH")
    return dict(payload, attestation_sha256=hashlib.sha256(
        _canonical(attestation)
    ).hexdigest())


def job_id_for_attestation(payload: dict) -> str:
    return f"v434-gh-{payload['run_id']}-a{payload['run_attempt']}"
