# -*- coding: utf-8 -*-
"""Offline Ed25519 v4.34 producer-signature and v5 evidence-promotion tests."""
from __future__ import annotations

import base64
from contextlib import closing
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from app_v5.attestation import (
    sign_capture, signing_public_key, verify_attestation,
    job_id_for_attestation
)
from app_v5.history import HistoryStore
from app_v5.sealed_import import import_signed_capture, import_manifest, read_encrypted
from daangn_secure_links_v4_34 import seal_manifest


URL = "https://www.daangn.com/kr/buy-sell/demo-abcdefghijkl/"
URL2 = "https://www.daangn.com/kr/buy-sell/demo-bbbbbbbbbbbb/"
COMMIT = "a" * 40
HMAC = b"test-hmac-key-material-fixed" + b"x" * 32


def fixture(*, price=45000, created="2026-11-10T01:23:45+00:00", second=False):
    urls = [URL, URL2] if second else [URL]
    rows = [{
        "title": "합성 HDD 테스트 " + str(i),
        "url": url, "price_krw": price if i == 0 else 50000,
        "category": "디지털기기", "availability": "판매 가능 추정",
        "observation_count": 1, "full_recommendation_approved": False,
        "seller_confirmed_available": False,
        "captured_from_current_primary_h1": True
    } for i, url in enumerate(urls)]
    return {
        "version": "4.34", "capture_scoped_only": True,
        "created_utc": created,
        "clickable_unique_count": len(rows),
        "unlinked_title_quarantine_count": 0,
        "source_run_unique_candidates": len(rows),
        "items": rows, "unlinked_groups": [],
        "manual_current_price_and_status_recheck_required": True,
        "full_recommendations_approved": 0
    }


class AttestationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.db = self.directory / "db.sqlite3"
        self.store = HistoryStore(self.db, HMAC)
        x = X25519PrivateKey.generate()
        self.recipient_private = x.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
            serialization.NoEncryption()
        )
        self.recipient_public = base64.b64encode(x.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )).decode("ascii")
        self.signing_private = Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
            serialization.NoEncryption()
        )
        self.trusted_public = signing_public_key(self.signing_private)

    def capture(self, *, run_id=501, price=45000, created="2026-11-10T01:23:45+00:00",
                second=False, valid=True):
        folder = self.directory / ("run-" + str(run_id))
        folder.mkdir()
        sealed = seal_manifest(fixture(price=price, created=created, second=second),
                               self.recipient_public)
        linked = 2 if second else 1
        data = {
            "v434_private_candidate_links.encrypted.json": sealed,
            "v434_secure_links_summary.json": {
                "version": "4.34",
                "status": "SEALED_PRIVATE_CANDIDATES_COMPLETE",
                "unique_candidates": linked, "linked_unique_candidates": linked,
                "quarantined_title_groups": 0,
                "full_recommendations_approved": 0,
                "key_material_on_github": False,
                "plaintext_urls_or_titles_in_artifacts": False
            },
            "v434_run_status.json": {
                "version": "4.34", "status": "SEALED_CAPTURE_COMPLETE",
                "attempted_live": True, "encrypted_links_written": True,
                "approval_required": True, "strict_listing_approved_count": 0,
                "max_source_visits": 9, "max_control_visits": 6,
                "unique_candidates": linked, "linked_unique_candidates": linked,
                "quarantined_title_groups": 0,
                "ended_utc": "2026-11-12T02:00:00+00:00"
            },
            "v433_unique_candidates.json": {"evaluation": {"dedup_complete": True}},
            "v429_public_status_results.json": {"evaluation": {
                "survey_complete": True,
                "status": "PUBLIC_STATUS_SIGNAL_SURVEY_COMPLETE_NO_DIRECT_FOR_SALE_PROOF"
            }},
            "v434_robots_decision.json": {"allowed": True if valid else False}
        }
        for filename, value in data.items():
            (folder / filename).write_text(
                json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return folder

    def signed(self, folder, *, run_id=501, private=None, sha=COMMIT):
        bundle = sign_capture(
            folder, self.signing_private if private is None else private,
            run_id=run_id, run_attempt=1, commit_sha=sha
        )
        (folder / "v434_capture_attestation.json").write_text(
            json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
        return bundle

    def verify(self, folder, *, pub=None, sha=COMMIT):
        def read(name):
            return (folder / name).read_bytes()
        bundle = json.loads((folder / "v434_capture_attestation.json")
                            .read_text(encoding="utf-8"))
        return verify_attestation(
            bundle, self.trusted_public if pub is None else pub,
            encrypted_bytes=read("v434_private_candidate_links.encrypted.json"),
            summary_bytes=read("v434_secure_links_summary.json"),
            run_bytes=read("v434_run_status.json"),
            unique_bytes=read("v433_unique_candidates.json"),
            expected_commit_sha=sha
        )

    def imported(self, folder, *, run_id=501, job_id=None, pub=None, sha=COMMIT,
                 store=None, dry_run=False):
        return import_signed_capture(
            self.store if store is None else store,
            encrypted_json=folder / "v434_private_candidate_links.encrypted.json",
            recipient_private_key=self.recipient_private,
            attestation_json=folder / "v434_capture_attestation.json",
            trusted_signer_public_key=self.trusted_public if pub is None else pub,
            summary_json=folder / "v434_secure_links_summary.json",
            run_status_json=folder / "v434_run_status.json",
            unique_json=folder / "v433_unique_candidates.json",
            profile_id="hdd",
            job_id=job_id if job_id is not None else "v434-gh-" + str(run_id) + "-a1",
            expected_commit_sha=sha,
            dry_run=dry_run
        )

    def test_signed_roundtrip_reviewer_only_price_and_exact_title(self):
        folder = self.capture()
        bundle = self.signed(folder)
        claim = self.verify(folder)
        self.assertEqual(claim["run_id"], 501)
        self.assertEqual(job_id_for_attestation(claim), "v434-gh-501-a1")
        self.assertEqual(len(claim["attestation_sha256"]), 64)
        result = self.imported(folder)
        self.assertEqual(result["evidence_level"], "REVIEWABLE")
        self.assertEqual(result["imported"], 1)
        self.assertTrue(result["source_authentication_verified"])
        self.assertFalse(result["transaction_state_verified"])
        key = self.store.stable_key(URL)
        rows = self.store.get_observations(key)
        self.assertEqual(rows[0]["evidence_level"], "REVIEWABLE")
        self.assertEqual(rows[0]["price_krw"], 45000)
        self.assertEqual(rows[0]["transaction_status"], "NOT_VERIFIED")
        self.assertEqual(rows[0]["stock_availability"], "NOT_OBSERVABLE")
        self.assertEqual(rows[0]["primary_status_verified"], 0)
        self.assertEqual(rows[0]["stock_verified"], 0)
        self.assertEqual(self.store.get_listing(key)["latest_observation_id"],
                         rows[0]["observation_id"])
        ledger = self.store.get_attestation("v434-gh-501-a1")
        self.assertEqual(ledger["attestation_sha256"], claim["attestation_sha256"])
        self.assertEqual(ledger["source_commit_sha"], COMMIT)
        self.assertEqual(self.store.get_events(), [])
        self.assertEqual(self.imported(folder)["already_present"], 1)

    def test_valid_signature_but_wrong_pinned_commit_rejected(self):
        folder = self.capture()
        self.signed(folder)
        with self.assertRaisesRegex(ValueError, "UNTRUSTED_ATTESTATION_CONTEXT"):
            self.imported(folder, sha="f" * 40)
        self.assertEqual(self.store.get_events(), [])

    def test_wrong_trusted_signer_rejected(self):
        folder = self.capture()
        self.signed(folder)
        outsider = Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        with self.assertRaisesRegex(ValueError, "UNTRUSTED_ATTESTATION_CONTEXT"):
            self.imported(folder, pub=outsider)

    def test_payload_signature_tamper_rejected(self):
        folder = self.capture()
        self.signed(folder)
        target = folder / "v434_capture_attestation.json"
        data = json.loads(target.read_text(encoding="utf-8"))
        data["payload"]["run_attempt"] = 2
        target.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "PRODUCER_SIGNATURE_VERIFICATION_FAILED"):
            self.imported(folder)
        self.assertEqual(self.store.get_job("v434-gh-501-a1"), None)

    def test_modified_envelope_summary_and_unique_are_rejected(self):
        for suffix, filename in enumerate((
            "v434_private_candidate_links.encrypted.json",
            "v434_secure_links_summary.json",
            "v433_unique_candidates.json"
        )):
            folder = self.capture(run_id=600 + suffix)
            self.signed(folder, run_id=600 + suffix)
            target = folder / filename
            target.write_bytes(target.read_bytes() + b" ")
            with self.subTest(filename=filename):
                with self.assertRaisesRegex(ValueError, "ATTESTED_FILE_HASH_MISMATCH"):
                    self.imported(folder, run_id=600 + suffix)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM listing_observations").fetchone()[0], 0)

    def test_signer_rejects_failed_gates(self):
        folder = self.capture(valid=False)
        with self.assertRaisesRegex(ValueError, "SIGNER_REJECTED_INCOMPLETE_CAPTURE"):
            self.signed(folder)
        self.assertFalse((folder / "v434_capture_attestation.json").exists())

    def test_same_listing_verified_price_drop_across_signed_runs(self):
        first = self.capture(run_id=701, price=45000,
                             created="2026-11-10T01:23:45+00:00")
        second = self.capture(run_id=702, price=35000,
                              created="2026-11-11T01:23:45+00:00")
        self.signed(first, run_id=701)
        self.signed(second, run_id=702)
        one = self.imported(first, run_id=701)
        two = self.imported(second, run_id=702)
        self.assertEqual(one["events_generated"], 0)
        self.assertEqual(two["events_generated"], 1)
        self.assertEqual(self.store.get_events()[-1]["event_type"], "PRICE_DROPPED")
        self.assertEqual(self.store.get_events()[-1]["previous_value"], "45000")
        self.assertEqual(self.store.get_events()[-1]["current_value"], "35000")
        self.assertEqual(self.store.get_events()[0]["event_type"], "PRICE_DROPPED")

    def test_previous_advisory_is_preserved_not_mutated(self):
        folder = self.capture(run_id=801)
        manifest = read_encrypted(
            folder / "v434_private_candidate_links.encrypted.json",
            self.recipient_private
        )
        import_manifest(self.store, manifest, profile_id="hdd", job_id="unsigned-801")
        self.signed(folder, run_id=801)
        result = self.imported(folder, run_id=801)
        self.assertEqual(result["imported"], 1)
        rows = self.store.get_observations(self.store.stable_key(URL))
        self.assertEqual([r["evidence_level"] for r in rows],
                         ["ADVISORY", "REVIEWABLE"])
        self.assertEqual(len(self.store.get_events()), 0)

    def test_reuse_attested_run_with_other_job_rejected(self):
        folder = self.capture(run_id=901)
        self.signed(folder, run_id=901)
        self.imported(folder, run_id=901)
        with self.assertRaisesRegex(ValueError, "SIGNED_JOB_ID_MUST_MATCH"):
            self.imported(folder, run_id=901, job_id="different")
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM capture_attestations").fetchone()[0], 1)

    def test_signed_batch_is_all_or_nothing(self):
        folder = self.capture(run_id=950, second=True)
        self.signed(folder, run_id=950)
        # Make a conflicting job first, then prove the signature import cannot
        # enter the same job without matching signed evidence.
        self.store.create_profile("hdd", name="v4.34 captured HDD candidates",
                                  keyword="HDD", region_id="2292", max_price_krw=50000)
        self.store.create_job("v434-gh-950-a1", "hdd")
        unsigned = read_encrypted(
            folder / "v434_private_candidate_links.encrypted.json",
            self.recipient_private
        )
        from app_v5.sealed_import import validate_manifest
        observations, sources = validate_manifest(unsigned)
        self.store.ingest_many("v434-gh-950-a1", observations[:1],
                               source_evidence=sources[:1])
        with self.assertRaisesRegex(ValueError, "CONFLICTING_SAME_JOB_OBSERVATION"):
            self.imported(folder, run_id=950)
        self.assertIsNone(self.store.get_listing(self.store.stable_key(URL2)))
        self.assertIsNone(self.store.get_attestation("v434-gh-950-a1"))

    def test_dry_run_verifies_without_db_write(self):
        folder = self.capture()
        self.signed(folder)
        result = self.imported(folder, dry_run=True, store=None)
        self.assertTrue(result["source_authentication_verified"])
        self.assertFalse(result["database_written"])
        self.assertIsNone(self.store.get_job("v434-gh-501-a1"))


if __name__ == "__main__":
    unittest.main()
