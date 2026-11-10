# -*- coding: utf-8 -*-
"""Offline, owner-local import of v4.34 encrypted private candidate lists.

The v4.34 X25519/AES-GCM envelope is encrypted for the receiver but DOES NOT
authenticate the sender. Without an independently verified producer signature
or run provenance, all imported observations remain ADVISORY: never advance
verified current state or generate price/status alerts.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import stat
import sys
from datetime import datetime, timezone

from app_v5.history import HistoryStore, Observation, SourceEvidence
from app_v5.attestation import job_id_for_attestation, verify_attestation
from daangn_secure_links_v4_34 import clean_title, unseal_manifest
from daangn_v4_1_core import normalized_listing
from daangn_v4_4_gate import stable_article_id

MAX_ENVELOPE_BYTES = 512 * 1024
MAX_CANDIDATES = 9
ALLOWED_SALE_LABELS = frozenset({"판매 가능 추정", "판매중 직접 확인"})
EXPECTED_CATEGORY = "디지털기기"


def _fail(code: str):
    raise ValueError(code)


def _private_bytes(path: str | Path, *, length: int | None = None) -> bytes:
    target = Path(path)
    if target.is_symlink() or not target.is_file():
        _fail("PRIVATE_KEY_FILE_NOT_REGULAR")
    info = target.stat()
    if os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077:
        _fail("PRIVATE_KEY_PERMISSIONS_NOT_0600")
    if not 32 <= info.st_size <= 128:
        _fail("PRIVATE_KEY_SIZE_INVALID")
    raw = target.read_bytes()
    if length is not None and len(raw) != length:
        _fail("PRIVATE_KEY_LENGTH_INVALID")
    return raw


def read_encrypted(path: str | Path, recipient_private_key: bytes) -> dict:
    """Limit ciphertext, then authenticate and decrypt fully in memory."""
    source = Path(path)
    if not source.is_file() or source.stat().st_size > MAX_ENVELOPE_BYTES:
        _fail("INVALID_ENVELOPE_SIZE")
    try:
        envelope = json.loads(source.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError, OSError):
        _fail("INVALID_ENVELOPE_JSON")
    if not isinstance(envelope, dict):
        _fail("INVALID_ENVELOPE_FORMAT")
    expected = {
        "version", "envelope", "ephemeral_public_key", "nonce",
        "ciphertext", "plaintext_not_archived"
    }
    if (set(envelope) != expected or envelope.get("version") != "4.34"
            or envelope.get("envelope") != "X25519-HKDF-SHA256-AES256-GCM"
            or envelope.get("plaintext_not_archived") is not True
            or not all(isinstance(envelope.get(x), str) for x in
                       ("ephemeral_public_key", "nonce", "ciphertext"))):
        _fail("INVALID_ENVELOPE_FIELDS")
    try:
        manifest = unseal_manifest(envelope, recipient_private_key)
    except (ValueError, TypeError, KeyError, AttributeError):
        _fail("ENVELOPE_DECRYPT_FAILED")
    return manifest


def validate_manifest(manifest: dict) -> tuple[list[Observation], list[SourceEvidence]]:
    """Validate the exact v4.34 builder's *display* contract, not source authenticity."""
    if not isinstance(manifest, dict):
        _fail("INVALID_MANIFEST")
    keys = {
        "version", "capture_scoped_only", "created_utc",
        "clickable_unique_count", "unlinked_title_quarantine_count",
        "source_run_unique_candidates", "items", "unlinked_groups",
        "manual_current_price_and_status_recheck_required",
        "full_recommendations_approved"
    }
    if (set(manifest) != keys or manifest.get("version") != "4.34"
            or manifest.get("capture_scoped_only") is not True
            or manifest.get("manual_current_price_and_status_recheck_required") is not True
            or type(manifest.get("full_recommendations_approved")) is not int
            or manifest["full_recommendations_approved"] != 0):
        _fail("INVALID_MANIFEST_HEADER")
    items, quarantined = manifest.get("items"), manifest.get("unlinked_groups")
    if type(items) is not list or type(quarantined) is not list:
        _fail("INVALID_MANIFEST_COLLECTIONS")
    counts = (
        manifest.get("clickable_unique_count"),
        manifest.get("unlinked_title_quarantine_count"),
        manifest.get("source_run_unique_candidates")
    )
    if (any(type(c) is not int or c < 0 for c in counts)
            or len(items) != counts[0]
            or len(quarantined) != counts[1]
            or sum(counts[:2]) != counts[2]
            or counts[2] > MAX_CANDIDATES):
        _fail("MANIFEST_COUNT_CONFLICT")
    created = manifest.get("created_utc")
    if not isinstance(created, str):
        _fail("INVALID_CAPTURE_TIME")
    try:
        dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
    except ValueError:
        _fail("INVALID_CAPTURE_TIME")
    if dt.tzinfo is None or dt.utcoffset() != timezone.utc.utcoffset(None):
        _fail("CAPTURE_TIME_NOT_UTC")
    capture_at = dt.astimezone(timezone.utc).isoformat(timespec="microseconds")
    for x in quarantined:
        if (not isinstance(x, dict) or set(x) !=
                {"observation_count", "reason_codes"}
                or type(x["observation_count"]) is not int
                or not 1 <= x["observation_count"] <= MAX_CANDIDATES
                or not isinstance(x["reason_codes"], list)
                or not x["reason_codes"]
                or any(not isinstance(s, str) or not (1 <= len(s) <= 100)
                       for s in x["reason_codes"])):
            _fail("INVALID_QUARANTINED_GROUP")
    observations: list[Observation] = []
    sources: list[SourceEvidence] = []
    ids = set()
    previous_order = None
    expected_item_fields = {
        "title", "url", "price_krw", "category", "availability",
        "observation_count", "full_recommendation_approved",
        "seller_confirmed_available", "captured_from_current_primary_h1"
    }
    for x in items:
        if not isinstance(x, dict) or set(x) != expected_item_fields:
            _fail("INVALID_SOURCE_ITEM_FIELDS")
        url = x["url"]
        if not isinstance(url, str) or normalized_listing(url) != url:
            _fail("INVALID_CANONICAL_URL")
        article_id = stable_article_id(url)
        if article_id is None or article_id in ids:
            _fail("DUPLICATE_OR_UNVERIFIED_ARTICLE_ID")
        ids.add(article_id)
        title = x["title"]
        if not isinstance(title, str) or clean_title(title) != title:
            _fail("INVALID_PRIMARY_TITLE")
        price = x["price_krw"]
        if type(price) is not int or not 0 <= price <= 50000:
            _fail("INVALID_SOURCE_PRICE")
        if (x["category"] != EXPECTED_CATEGORY
                or x["availability"] not in ALLOWED_SALE_LABELS
                or type(x["observation_count"]) is not int
                or not 1 <= x["observation_count"] <= MAX_CANDIDATES
                or x["full_recommendation_approved"] is not False
                or x["seller_confirmed_available"] is not False
                or x["captured_from_current_primary_h1"] is not True):
            _fail("INVALID_SOURCE_PROVENANCE")
        order = (price, url)
        if previous_order is not None and previous_order > order:
            _fail("SOURCE_PRICE_ORDER_CONFLICT")
        previous_order = order
        observations.append(Observation(
            canonical_url=url,
            observed_at_utc=capture_at,  # manifest export time, not exact page visit time
            identity_verified=True,  # verified against the manifest, NOT authenticated producer
            title=title,
            price_krw=price,
            price_verified=True,  # v4.34 asserted exact-route price; still ADVISORY
            transaction_status="NOT_VERIFIED",
            primary_status_verified=False,
            stock_availability="NOT_OBSERVABLE",
            stock_verified=False,
            description=None,
            description_verified=False,
            evidence_level="ADVISORY",
            sale_filter_eligible=False,
            sale_state_inferred=False
        ))
        sources.append(SourceEvidence(
            source_version="4.34",
            capture_created_utc=capture_at,
            category_display=x["category"],
            sale_display=x["availability"],
            source_observation_count=x["observation_count"],
            primary_h1_captured=True,
            full_recommendation_approved=False
        ))
    return observations, sources


def import_manifest(store: HistoryStore, manifest: dict, *,
                    profile_id: str, job_id: str) -> dict:
    """Validate all rows before any DB mutation, then commit the batch atomically."""
    observations, sources = validate_manifest(manifest)
    store.create_profile(profile_id, name="v4.34 captured HDD candidates",
                         keyword="HDD", region_id="2292", max_price_krw=50000)
    store.create_job(job_id, profile_id)
    results = store.ingest_many(job_id, observations, source_evidence=sources)
    current_job = store.get_job(job_id)
    if current_job is None:
        _fail("IMPORT_JOB_NOT_FOUND")
    if current_job["status"] == "COMPLETED":
        if not all(r["idempotent"] for r in results):
            _fail("COMPLETED_IMPORT_NOT_IDEMPOTENT")
    else:
        store.finish_job(job_id, succeeded=True)
    return {
        "imported": sum(not r["idempotent"] for r in results),
        "already_present": sum(bool(r["idempotent"]) for r in results),
        "quarantined_groups_skipped": manifest["unlinked_title_quarantine_count"],
        "events_generated": sum(len(r["events"]) for r in results),
        "evidence_level": "ADVISORY",
        "transaction_state_verified": False,
        "source_authentication_verified": False
    }


def _bounded_input(path: str | Path, *, max_bytes: int = 512 * 1024) -> bytes:
    file = Path(path)
    if file.is_symlink() or not file.is_file() or file.stat().st_size > max_bytes:
        _fail("INVALID_ATTESTED_INPUT_FILE")
    return file.read_bytes()


def import_signed_capture(store: HistoryStore, *,
                          encrypted_json: str | Path,
                          recipient_private_key: bytes,
                          attestation_json: str | Path,
                          trusted_signer_public_key: bytes,
                          summary_json: str | Path,
                          run_status_json: str | Path,
                          unique_json: str | Path,
                          profile_id: str, job_id: str,
                          expected_commit_sha: str,
                          dry_run: bool = False) -> dict:
    """Authenticate signature + exact file hashes before any SQLite mutation.

    Only the matched v4.34 title/URL/Route-price claim is promoted to
    REVIEWABLE. Transaction UI, stock, seller confirmation and description
    remain UNVERIFIED because the sealed manifest does not contain proof.
    """
    if not isinstance(expected_commit_sha, str) or len(expected_commit_sha) != 40:
        _fail("EXPECTED_SOURCE_COMMIT_REQUIRED")
    envelope_bytes = _bounded_input(encrypted_json)
    summary_bytes = _bounded_input(summary_json)
    run_bytes = _bounded_input(run_status_json)
    unique_bytes = _bounded_input(unique_json)
    try:
        attestation = json.loads(_bounded_input(attestation_json).decode("utf-8"))
    except (ValueError, UnicodeError):
        _fail("INVALID_ATTESTATION_JSON")
    producer = verify_attestation(
        attestation, trusted_signer_public_key,
        encrypted_bytes=envelope_bytes, summary_bytes=summary_bytes,
        run_bytes=run_bytes, unique_bytes=unique_bytes,
        expected_commit_sha=expected_commit_sha
    )
    if job_id != job_id_for_attestation(producer):
        _fail("SIGNED_JOB_ID_MUST_MATCH_GITHUB_RUN")
    manifest = read_encrypted(encrypted_json, recipient_private_key)
    observations, sources = validate_manifest(manifest)
    summary = json.loads(summary_bytes.decode("utf-8"))
    if (manifest["clickable_unique_count"] != summary["linked_unique_candidates"]
            or manifest["source_run_unique_candidates"] != summary["unique_candidates"]
            or manifest["unlinked_title_quarantine_count"] !=
            summary["quarantined_title_groups"]):
        _fail("SIGNED_MANIFEST_SUMMARY_COUNT_MISMATCH")
    # Export time cannot be after capture completion.
    ended = datetime.fromisoformat(producer["capture_ended_utc"])
    created = datetime.fromisoformat(manifest["created_utc"].replace("Z", "+00:00"))
    if created > ended:
        _fail("SIGNED_CAPTURE_TIME_CONFLICT")
    if dry_run:
        return {
            "validated_candidates": len(observations),
            "evidence_level": "REVIEWABLE",
            "source_authentication_verified": True,
            "transaction_state_verified": False,
            "stock_availability_verified": False,
            "database_written": False
        }
    verified_rows = [replace(item, evidence_level="REVIEWABLE")
                     for item in observations]
    store.create_profile(
        profile_id, name="v4.34 captured HDD candidates",
        keyword="HDD", region_id="2292", max_price_krw=50000
    )
    store.create_job(job_id, profile_id)
    results = store.ingest_many(
        job_id, verified_rows, source_evidence=sources, signed_capture=producer
    )
    current_job = store.get_job(job_id)
    if current_job is None:
        _fail("SIGNED_JOB_NOT_FOUND")
    if current_job["status"] == "COMPLETED":
        if not all(x["idempotent"] for x in results):
            _fail("SIGNED_COMPLETED_JOB_NOT_IDEMPOTENT")
    else:
        store.finish_job(job_id, succeeded=True)
    return {
        "imported": sum(not x["idempotent"] for x in results),
        "already_present": sum(bool(x["idempotent"]) for x in results),
        "quarantined_groups_skipped": manifest["unlinked_title_quarantine_count"],
        "events_generated": sum(len(x["events"]) for x in results),
        "evidence_level": "REVIEWABLE",
        "source_authentication_verified": True,
        "transaction_state_verified": False,
        "stock_availability_verified": False
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline v4.34 encrypted-list import. No plaintext export.")
    parser.add_argument("--encrypted-json", required=True)
    parser.add_argument("--recipient-private-key-file", required=True)
    parser.add_argument("--history-hmac-key-file", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--attestation-json")
    parser.add_argument("--trusted-signer-public-key-file")
    parser.add_argument("--summary-json")
    parser.add_argument("--run-status-json")
    parser.add_argument("--unique-json")
    parser.add_argument("--expected-commit-sha")
    args = parser.parse_args(argv)
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        parser.error("LOCAL_OWNER_EXECUTION_ONLY")
    try:
        recipient_key = _private_bytes(args.recipient_private_key_file, length=32)
        hmac_key = _private_bytes(args.history_hmac_key_file)
        if recipient_key == hmac_key:
            _fail("SEPARATE_SECRET_KEYS_REQUIRED")
        signature_options = (
            args.attestation_json, args.trusted_signer_public_key_file,
            args.summary_json, args.run_status_json, args.unique_json,
            args.expected_commit_sha
        )
        if any(signature_options):
            if not all(signature_options):
                _fail("INCOMPLETE_ATTESTATION_INPUTS")
            signer_pub = _bounded_input(args.trusted_signer_public_key_file,
                                        max_bytes=64)
            store = (None if args.dry_run else HistoryStore(args.db, hmac_key))
            summary = import_signed_capture(
                store, encrypted_json=args.encrypted_json,
                recipient_private_key=recipient_key,
                attestation_json=args.attestation_json,
                trusted_signer_public_key=signer_pub,
                summary_json=args.summary_json,
                run_status_json=args.run_status_json,
                unique_json=args.unique_json,
                profile_id=args.profile_id, job_id=args.job_id,
                expected_commit_sha=args.expected_commit_sha,
                dry_run=args.dry_run
            )
        else:
            manifest = read_encrypted(args.encrypted_json, recipient_key)
            observations, _ = validate_manifest(manifest)
            if args.dry_run:
                summary = {
                    "validated_candidates": len(observations),
                    "quarantined_groups_skipped": manifest["unlinked_title_quarantine_count"],
                    "source_authentication_verified": False,
                    "database_written": False
                }
            else:
                store = HistoryStore(args.db, hmac_key)
                summary = import_manifest(store, manifest,
                                          profile_id=args.profile_id, job_id=args.job_id)
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, TypeError, ValueError, RuntimeError):
        # Do not print potentially sensitive filesystem paths, listing data or keys.
        print("SEALED_IMPORT_REJECTED", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
