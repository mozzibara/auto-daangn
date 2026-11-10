# -*- coding: utf-8 -*-
"""Offline, signed multi-run price-history accuracy matrix for pre-OCI validation.

Uses ONLY generated synthetic canonical URLs and temporary local SQLite.
No GitHub signing secrets, Daangn network requests, persistent DB, or Telegram.
"""
from __future__ import annotations

import base64
from contextlib import closing
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from app_v5.attestation import sign_capture, signing_public_key
from app_v5.history import HistoryStore
from app_v5.sealed_import import import_manifest, import_signed_capture, read_encrypted
from daangn_secure_links_v4_34 import seal_manifest

URL_A = "https://www.daangn.com/kr/buy-sell/synthetic-hdd-aaaaaaaaaaaa/"
URL_B = "https://www.daangn.com/kr/buy-sell/synthetic-hdd-bbbbbbbbbbbb/"
SOURCE_SHA = "b" * 40
HMAC_KEY = b"pre-oci-synthetic-hmac-key-material-v1"  # test-only


class SignedMultiRunPriceMatrix(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.database = self.root / "price-history-test.sqlite3"
        self.store = HistoryStore(self.database, HMAC_KEY)
        recipient = X25519PrivateKey.generate()
        self.recipient_private = recipient.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption()
        )
        self.recipient_public_b64 = base64.b64encode(
            recipient.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
        ).decode("ascii")
        signer = Ed25519PrivateKey.generate()
        self.signer_private = signer.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption()
        )
        self.signer_public = signing_public_key(self.signer_private)

    def capture(self, run_id: int, when: str, *,
                price_a: int, price_b: int | None = None) -> Path:
        """Build and sign a distinct bounded 4.34 capture at an exact UTC time."""
        created = datetime.fromisoformat(when)
        self.assertIsNotNone(created.tzinfo)
        items = []
        for url, title, price in (
            (URL_A, "합성 저장장치 A", price_a),
            (URL_B, "합성 저장장치 B", price_b)
        ):
            if price is None:
                continue
            items.append({
                "title": title,
                "url": url,
                "price_krw": price,
                "category": "디지털기기",
                "availability": "판매 가능 추정",
                "observation_count": 1,
                "full_recommendation_approved": False,
                "seller_confirmed_available": False,
                "captured_from_current_primary_h1": True
            })
        items.sort(key=lambda x: (x["price_krw"], x["url"]))
        manifest = {
            "version": "4.34", "capture_scoped_only": True,
            "created_utc": when,
            "clickable_unique_count": len(items),
            "unlinked_title_quarantine_count": 0,
            "source_run_unique_candidates": len(items),
            "items": items, "unlinked_groups": [],
            "manual_current_price_and_status_recheck_required": True,
            "full_recommendations_approved": 0
        }
        folder = self.root / f"capture-{run_id}"
        folder.mkdir()
        sources = {
            "v434_private_candidate_links.encrypted.json":
                seal_manifest(manifest, self.recipient_public_b64),
            "v434_secure_links_summary.json": {
                "version": "4.34",
                "status": "SEALED_PRIVATE_CANDIDATES_COMPLETE",
                "unique_candidates": len(items),
                "linked_unique_candidates": len(items),
                "quarantined_title_groups": 0,
                "full_recommendations_approved": 0,
                "key_material_on_github": False,
                "plaintext_urls_or_titles_in_artifacts": False
            },
            "v434_run_status.json": {
                "version": "4.34",
                "status": "SEALED_CAPTURE_COMPLETE",
                "attempted_live": True,
                "encrypted_links_written": True,
                "approval_required": True,
                "strict_listing_approved_count": 0,
                "max_source_visits": 9,
                "max_control_visits": 6,
                "unique_candidates": len(items),
                "linked_unique_candidates": len(items),
                "quarantined_title_groups": 0,
                "ended_utc": (created + timedelta(minutes=5)).isoformat()
            },
            "v433_unique_candidates.json": {
                "evaluation": {"dedup_complete": True}
            },
            "v429_public_status_results.json": {
                "evaluation": {
                    "survey_complete": True,
                    "status":
                        "PUBLIC_STATUS_SIGNAL_SURVEY_COMPLETE_NO_DIRECT_FOR_SALE_PROOF"
                }
            },
            "v434_robots_decision.json": {"allowed": True}
        }
        for name, value in sources.items():
            (folder / name).write_text(
                json.dumps(value, ensure_ascii=False), encoding="utf-8"
            )
        signature = sign_capture(
            folder, self.signer_private,
            run_id=run_id, run_attempt=1, commit_sha=SOURCE_SHA
        )
        (folder / "v434_capture_attestation.json").write_text(
            json.dumps(signature, ensure_ascii=False), encoding="utf-8"
        )
        return folder

    def import_signed(self, run_id: int, folder: Path):
        return import_signed_capture(
            self.store,
            encrypted_json=folder / "v434_private_candidate_links.encrypted.json",
            recipient_private_key=self.recipient_private,
            attestation_json=folder / "v434_capture_attestation.json",
            trusted_signer_public_key=self.signer_public,
            summary_json=folder / "v434_secure_links_summary.json",
            run_status_json=folder / "v434_run_status.json",
            unique_json=folder / "v433_unique_candidates.json",
            profile_id="test-hdd",
            job_id=f"v434-gh-{run_id}-a1",
            expected_commit_sha=SOURCE_SHA
        )

    def events(self, url=URL_A):
        return [{
            "type": r["event_type"],
            "previous": r["previous_value"],
            "current": r["current_value"]
        } for r in self.store.get_events(self.store.stable_key(url))]

    def count_table(self, table: str) -> int:
        self.assertIn(table, {
            "listing_observations", "listing_events", "capture_attestations",
            "listing_source_evidence"
        })
        with closing(sqlite3.connect(self.database)) as conn:
            return conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]

    def test_five_signed_times_drop_flat_increase_drop_and_other_listing(self):
        """45k→35k→35k→38k→30k: two drops, one increase, no false events."""
        moments = [
            (2101, "2026-11-01T10:00:00+00:00", 45000, 0),
            (2102, "2026-11-02T10:00:00+00:00", 35000, 1),
            (2103, "2026-11-03T10:00:00+00:00", 35000, 0),
            (2104, "2026-11-04T10:00:00+00:00", 38000, 1),
            (2105, "2026-11-05T10:00:00+00:00", 30000, 1),
        ]
        last = None
        for run_id, when, price, events in moments:
            folder = self.capture(run_id, when, price_a=price, price_b=25000)
            result = self.import_signed(run_id, folder)
            self.assertEqual(result["imported"], 2)
            self.assertEqual(result["events_generated"], events)
            self.assertTrue(result["source_authentication_verified"])
            last = (run_id, folder)
        self.assertEqual(self.events(), [
            {"type": "PRICE_DROPPED", "previous": "45000", "current": "35000"},
            {"type": "PRICE_INCREASED", "previous": "35000", "current": "38000"},
            {"type": "PRICE_DROPPED", "previous": "38000", "current": "30000"}
        ])
        self.assertEqual(self.events(URL_B), [])
        key = self.store.stable_key(URL_A)
        self.assertNotEqual(key, self.store.stable_key(URL_B))
        observations = self.store.get_observations(key)
        self.assertEqual([x["price_krw"] for x in observations],
                         [45000, 35000, 35000, 38000, 30000])
        self.assertTrue(all(x["evidence_level"] == "REVIEWABLE"
                            and x["price_verified"] == 1
                            and x["transaction_status"] == "NOT_VERIFIED"
                            and x["primary_status_verified"] == 0
                            and x["stock_availability"] == "NOT_OBSERVABLE"
                            and x["stock_verified"] == 0
                            and x["sale_filter_eligible"] == 0
                            for x in observations))
        self.assertEqual(self.count_table("listing_observations"), 10)
        self.assertEqual(self.count_table("listing_source_evidence"), 10)
        self.assertEqual(self.count_table("listing_events"), 3)
        self.assertEqual(self.count_table("capture_attestations"), 5)
        self.assertEqual(self.store.get_listing(key)["latest_observation_id"],
                         observations[-1]["observation_id"])
        for run_id, *_ in moments:
            ledger = self.store.get_attestation(f"v434-gh-{run_id}-a1")
            self.assertIsNotNone(ledger)
            self.assertEqual(ledger["run_id"], run_id)
            self.assertEqual(ledger["source_commit_sha"], SOURCE_SHA)
        repeated = self.import_signed(*last)
        self.assertEqual((repeated["imported"], repeated["already_present"],
                          repeated["events_generated"]), (0, 2, 0))
        self.assertEqual(self.count_table("listing_events"), 3)

    def test_late_arriving_old_capture_does_not_make_fictitious_drop(self):
        latest = self.capture(2201, "2026-11-03T09:00:00+00:00",
                              price_a=32000)
        older = self.capture(2202, "2026-11-01T09:00:00+00:00",
                             price_a=45000)
        next_run = self.capture(2203, "2026-11-04T09:00:00+00:00",
                                price_a=30000)
        self.assertEqual(self.import_signed(2201, latest)["events_generated"], 0)
        self.assertEqual(self.import_signed(2202, older)["events_generated"], 0)
        self.assertEqual(self.events(), [])
        self.assertEqual(self.import_signed(2203, next_run)["events_generated"], 1)
        self.assertEqual(self.events(), [
            {"type": "PRICE_DROPPED", "previous": "32000", "current": "30000"}
        ])
        key = self.store.stable_key(URL_A)
        self.assertEqual([x["price_krw"] for x in self.store.get_observations(key)],
                         [45000, 32000, 30000])
        self.assertEqual(self.store.get_listing(key)["last_seen_utc"],
                         "2026-11-04T09:00:00.000000+00:00")

    def test_unsigned_advisory_price_cannot_create_verified_drop(self):
        advisory = self.capture(2301, "2026-11-01T09:00:00+00:00",
                                price_a=45000)
        manifest = read_encrypted(
            advisory / "v434_private_candidate_links.encrypted.json",
            self.recipient_private
        )
        initial = import_manifest(self.store, manifest,
                                  profile_id="test-hdd", job_id="unsigned-2301")
        self.assertEqual(initial["evidence_level"], "ADVISORY")
        first_signed = self.capture(2302, "2026-11-02T09:00:00+00:00",
                                    price_a=38000)
        second_signed = self.capture(2303, "2026-11-03T09:00:00+00:00",
                                     price_a=33000)
        self.assertEqual(self.import_signed(2302, first_signed)["events_generated"], 0)
        self.assertEqual(self.import_signed(2303, second_signed)["events_generated"], 1)
        self.assertEqual(self.events(), [
            {"type": "PRICE_DROPPED", "previous": "38000", "current": "33000"}
        ])
        self.assertEqual(
            [x["evidence_level"] for x in self.store.get_observations(
                self.store.stable_key(URL_A))],
            ["ADVISORY", "REVIEWABLE", "REVIEWABLE"]
        )

    def test_tampered_second_capture_cannot_change_price_baseline(self):
        first = self.capture(2401, "2026-11-01T09:00:00+00:00",
                             price_a=45000)
        tampered = self.capture(2402, "2026-11-02T09:00:00+00:00",
                                price_a=34000)
        valid_third = self.capture(2403, "2026-11-03T09:00:00+00:00",
                                   price_a=33000)
        self.import_signed(2401, first)
        path = tampered / "v434_private_candidate_links.encrypted.json"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "ATTESTED_FILE_HASH_MISMATCH"):
            self.import_signed(2402, tampered)
        self.assertEqual(self.events(), [])
        self.assertIsNone(self.store.get_attestation("v434-gh-2402-a1"))
        self.assertEqual(self.count_table("listing_observations"), 1)
        self.assertEqual(self.import_signed(2403, valid_third)["events_generated"], 1)
        self.assertEqual(self.events(), [
            {"type": "PRICE_DROPPED", "previous": "45000", "current": "33000"}
        ])

    def test_identical_timestamp_different_price_rejected_atomically(self):
        first = self.capture(2501, "2026-11-01T09:00:00+00:00",
                             price_a=45000)
        conflicting = self.capture(2502, "2026-11-01T09:00:00+00:00",
                                   price_a=40000)
        self.import_signed(2501, first)
        with self.assertRaisesRegex(ValueError, "CONFLICTING_SAME_TIMESTAMP"):
            self.import_signed(2502, conflicting)
        self.assertEqual(self.count_table("listing_observations"), 1)
        self.assertEqual(self.count_table("listing_events"), 0)
        self.assertEqual(self.count_table("capture_attestations"), 1)
        self.assertIsNone(self.store.get_attestation("v434-gh-2502-a1"))

    def test_out_of_profile_price_rejected_without_price_event(self):
        first = self.capture(2601, "2026-11-01T09:00:00+00:00",
                             price_a=45000)
        invalid = self.capture(2602, "2026-11-02T09:00:00+00:00",
                               price_a=50001)
        self.import_signed(2601, first)
        with self.assertRaisesRegex(ValueError, "INVALID_SOURCE_PRICE"):
            self.import_signed(2602, invalid)
        self.assertEqual(self.events(), [])
        self.assertEqual(self.count_table("listing_observations"), 1)
        self.assertEqual(self.count_table("capture_attestations"), 1)


if __name__ == "__main__":
    unittest.main()
