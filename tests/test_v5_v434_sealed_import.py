# -*- coding: utf-8 -*-
"""Synthetic, offline v4.34 sealed shortlist -> private v5 SQLite tests."""
from __future__ import annotations

from contextlib import closing
from dataclasses import replace
import base64
import copy
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from app_v5.history import HistoryStore
from app_v5.sealed_import import (
    _private_bytes, import_manifest, main, read_encrypted, validate_manifest
)
from daangn_secure_links_v4_34 import seal_manifest


TEST_URL_A = "https://www.daangn.com/kr/buy-sell/test-abcdefghijkl/"
TEST_URL_B = "https://www.daangn.com/kr/buy-sell/test-bbbbbbbbbbbb/"
TEST_HMAC = b"test-local-hmac-secret-not-for-real-use-" + b"x" * 32


def fixture(*, second=False):
    urls = [TEST_URL_A, TEST_URL_B] if second else [TEST_URL_A]
    items = []
    for i, url in enumerate(urls):
        items.append({
            "title": "가상 HDD 4TB " + str(i + 1),
            "url": url,
            "price_krw": 40000 + 10000 * i,
            "category": "디지털기기",
            "availability": ("판매 가능 추정" if i == 0
                             else "판매중 직접 확인"),
            "observation_count": 2 if i == 0 else 1,
            "full_recommendation_approved": False,
            "seller_confirmed_available": False,
            "captured_from_current_primary_h1": True,
        })
    return {
        "version": "4.34",
        "capture_scoped_only": True,
        "created_utc": "2026-11-10T01:23:45+00:00",
        "clickable_unique_count": len(items),
        "unlinked_title_quarantine_count": 0,
        "source_run_unique_candidates": len(items),
        "items": items,
        "unlinked_groups": [],
        "manual_current_price_and_status_recheck_required": True,
        "full_recommendations_approved": 0
    }


def keys():
    prv = X25519PrivateKey.generate()
    private = prv.private_bytes(serialization.Encoding.Raw,
                                serialization.PrivateFormat.Raw,
                                serialization.NoEncryption())
    public = base64.b64encode(prv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    return private, public


class SealedImportTests(unittest.TestCase):
    def setUp(self):
        self.root = TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.db = Path(self.root.name) / "local_private" / "db.sqlite3"
        self.store = HistoryStore(self.db, TEST_HMAC)
        self.private, self.public = keys()

    def _sealed_file(self, manifest=None):
        envelope = seal_manifest(manifest if manifest is not None else fixture(),
                                 self.public)
        target = Path(self.root.name) / "sealed.json"
        target.write_text(json.dumps(envelope), encoding="utf-8")
        return target

    def test_authentic_envelope_roundtrip_to_advisory_db(self):
        envelope_file = self._sealed_file()
        manifest = read_encrypted(envelope_file, self.private)
        res = import_manifest(self.store, manifest, profile_id="hdd", job_id="job1")
        self.assertEqual(res["imported"], 1)
        self.assertEqual(res["events_generated"], 0)
        self.assertFalse(res["source_authentication_verified"])
        key = self.store.stable_key(TEST_URL_A)
        item = self.store.get_listing(key)
        self.assertIsNone(item["latest_observation_id"])
        observations = self.store.get_observations(key)
        self.assertEqual(len(observations), 1)
        row = observations[0]
        self.assertEqual(row["evidence_level"], "ADVISORY")
        self.assertEqual(row["price_krw"], 40000)
        self.assertEqual(row["transaction_status"], "NOT_VERIFIED")
        self.assertEqual(row["stock_availability"], "NOT_OBSERVABLE")
        self.assertEqual(row["title"], "가상 HDD 4TB 1")
        self.assertEqual(self.store.get_events(), [])
        provenance = self.store.get_source_evidence(key)[0]
        self.assertEqual(provenance["source_version"], "4.34")
        self.assertEqual(provenance["category_display"], "디지털기기")
        self.assertEqual(provenance["sale_display"], "판매 가능 추정")
        self.assertEqual(provenance["source_observation_count"], 2)

    def test_second_capture_never_generates_verified_alerts(self):
        first = fixture()
        second = copy.deepcopy(first)
        second["created_utc"] = "2026-11-11T01:23:45+00:00"
        second["items"][0]["price_krw"] = 10000
        import_manifest(self.store, first, profile_id="hdd", job_id="first")
        result = import_manifest(self.store, second, profile_id="hdd", job_id="second")
        self.assertEqual(result["events_generated"], 0)
        key = self.store.stable_key(TEST_URL_A)
        self.assertEqual(len(self.store.get_observations(key)), 2)
        self.assertEqual(self.store.get_events(), [])

    def test_same_job_reimport_idempotence_and_source_conflict(self):
        manifest = fixture()
        first = import_manifest(self.store, manifest, profile_id="hdd", job_id="once")
        again = import_manifest(self.store, manifest, profile_id="hdd", job_id="once")
        self.assertEqual(first["imported"], 1)
        self.assertEqual(again["imported"], 0)
        self.assertEqual(again["already_present"], 1)
        changed = copy.deepcopy(manifest)
        changed["items"][0]["observation_count"] = 3
        with self.assertRaisesRegex(ValueError, "CONFLICTING_SOURCE_EVIDENCE"):
            import_manifest(self.store, changed, profile_id="hdd", job_id="once")
        self.assertEqual(len(self.store.get_source_evidence(
            self.store.stable_key(TEST_URL_A))), 1)

    def test_whole_batch_rolls_back_on_later_conflict(self):
        observations, sources = validate_manifest(fixture())
        self.store.create_profile("hdd", name="v4.34 captured HDD candidates",
                                  keyword="HDD", region_id="2292",
                                  max_price_krw=50000)
        self.store.create_job("once", "hdd")
        self.store.ingest_many("once", observations, source_evidence=sources)
        changed = fixture(second=True)
        changed["items"][0]["price_krw"] = 47000  # conflict with existing A
        changed["items"][1]["price_krw"] = 30000  # new B sorted first
        changed["items"].sort(key=lambda x:(x["price_krw"], x["url"]))
        with self.assertRaisesRegex(ValueError, "CONFLICTING_SAME_JOB_OBSERVATION"):
            import_manifest(self.store, changed, profile_id="hdd", job_id="once")
        self.assertIsNone(self.store.get_listing(self.store.stable_key(TEST_URL_B)))
        self.assertEqual(len(self.store.get_observations(
            self.store.stable_key(TEST_URL_A))), 1)

    def test_quarantined_groups_are_skipped(self):
        m = fixture()
        m["unlinked_groups"] = [{"observation_count":1,
                                 "reason_codes":["TITLE_UNAVAILABLE"]}]
        m["unlinked_title_quarantine_count"] = 1
        m["source_run_unique_candidates"] = 2
        res = import_manifest(self.store, m, profile_id="hdd", job_id="once")
        self.assertEqual(res["quarantined_groups_skipped"], 1)
        self.assertEqual(res["imported"], 1)

    def test_rejects_envelope_tampering_and_wrong_key(self):
        p = self._sealed_file()
        data = json.loads(p.read_text(encoding="utf-8"))
        raw = bytearray(base64.b64decode(data["ciphertext"]))
        raw[-1] ^= 1
        data["ciphertext"] = base64.b64encode(raw).decode()
        p.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "ENVELOPE_DECRYPT_FAILED"):
            read_encrypted(p, self.private)
        with self.assertRaises(ValueError):
            read_encrypted(self._sealed_file(), keys()[0])

    def test_untrusted_but_well_formed_sender_is_never_promoted(self):
        # Encryption is NOT a producer signature.
        other_prv, other_pub = keys()
        m = fixture()
        m["items"][0]["availability"] = "판매중 직접 확인"
        encrypted_by_another_sender = seal_manifest(m, self.public)
        p = Path(self.root.name) / "other_sender.json"
        p.write_text(json.dumps(encrypted_by_another_sender), encoding="utf-8")
        result = import_manifest(
            self.store, read_encrypted(p, self.private), profile_id="hdd", job_id="job")
        self.assertEqual(result["evidence_level"], "ADVISORY")
        self.assertEqual(self.store.get_events(), [])

    def test_manifest_violations_prevent_any_db_ingest(self):
        modifications = (
            lambda m: m["items"][0].update(
                url="https://evil.example/kr/buy-sell/test-abcdefghijkl/"),
            lambda m: m["items"][0].update(url=TEST_URL_A + "?tracking=1"),
            lambda m: m["items"][0].update(title="<script>bad</script>"),
            lambda m: m["items"][0].update(price_krw=True),
            lambda m: m["items"][0].update(price_krw=50001),
            lambda m: m["items"][0].update(category="다른 카테고리"),
            lambda m: m["items"][0].update(availability="판매완료"),
            lambda m: m["items"][0].update(full_recommendation_approved=True),
            lambda m: m.update(full_recommendations_approved=1),
            lambda m: m.update(clickable_unique_count=2),
            lambda m: m.update(created_utc="2026-11-10T12:00:00"),
            lambda m: m["items"][0].update(
                captured_from_current_primary_h1=False),
        )
        for i, edit in enumerate(modifications):
            with self.subTest(i=i):
                m = copy.deepcopy(fixture())
                edit(m)
                with self.assertRaises(ValueError):
                    import_manifest(self.store, m, profile_id="hdd",
                                    job_id="bad-" + str(i))
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM listing_observations").fetchone()[0], 0)

    def test_duplicate_article_id_rejected_even_with_different_slug(self):
        m = fixture(second=True)
        m["items"][1]["url"] = ("https://www.daangn.com/kr/buy-sell/"
                                 "other-abcdefghijkl/")
        m["items"].sort(key=lambda x: (x["price_krw"], x["url"]))
        with self.assertRaisesRegex(ValueError, "DUPLICATE_OR_UNVERIFIED"):
            validate_manifest(m)

    def test_private_key_permissions_and_local_only_cli(self):
        envelope = self._sealed_file()
        p = Path(self.root.name) / "private-key.bin"
        p.write_bytes(self.private)
        h = Path(self.root.name) / "hmac-key.bin"
        h.write_bytes(TEST_HMAC)
        if os.name == "posix":
            p.chmod(0o600)
            h.chmod(0o600)
        self.assertEqual(_private_bytes(p, length=32), self.private)
        flags = [
            "--encrypted-json", str(envelope),
            "--recipient-private-key-file", str(p),
            "--history-hmac-key-file", str(h),
            "--db", str(self.db),
            "--profile-id", "hdd",
            "--job-id", "cmd-001",
            "--dry-run"
        ]
        with patch.dict(os.environ, {"CI":"", "GITHUB_ACTIONS":""}):
            self.assertEqual(main(flags), 0)
        with patch.dict(os.environ, {"CI":"true"}):
            with self.assertRaises(SystemExit):
                main(flags)
        if os.name == "posix":
            p.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "PERMISSIONS"):
                _private_bytes(p, length=32)

    def test_schema_v1_database_migrates_to_v2_without_losing_history(self):
        import_manifest(self.store, fixture(), profile_id="hdd", job_id="job1")
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("DROP TABLE listing_source_evidence")
            conn.execute("PRAGMA user_version=1")
            conn.commit()
        recovered = HistoryStore(self.db, TEST_HMAC)
        self.assertEqual(len(recovered.get_observations(
            recovered.stable_key(TEST_URL_A))), 1)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 3)
            names = {x[0] for x in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("listing_source_evidence", names)


if __name__ == "__main__":
    unittest.main()
