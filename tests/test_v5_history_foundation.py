# -*- coding: utf-8 -*-
"""v5.0 offline SQLite tests; all listings are synthetic fixtures."""
from __future__ import annotations

from dataclasses import replace
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from app_v5 import HistoryStore, Observation

URL = "https://www.daangn.com/kr/buy-sell/test-abcdefghijkl/"
URL_SAME_ID = "https://www.daangn.com/kr/buy-sell/renamed-abcdefghijkl/"
URL_OTHER = "https://www.daangn.com/kr/buy-sell/test-bbbbbbbbbbbb/"


def row(time: str, *, price=50000, description="HDD 4TB", **kwargs):
    base = dict(
        canonical_url=URL, observed_at_utc=time, identity_verified=True,
        title="4TB HDD", price_krw=price, price_verified=True,
        transaction_status="NOT_OBSERVABLE", primary_status_verified=False,
        stock_availability="IN_STOCK", stock_verified=True,
        description=description, description_verified=True,
        evidence_level="REVIEWABLE",
        sale_filter_eligible=True, sale_state_inferred=True,
    )
    base.update(kwargs)
    return Observation(**base)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "private" / "history.sqlite3"
        self.store = HistoryStore(self.path, b"fixed-test-secret-" + b"x" * 32)
        self.store.create_profile("hdd-cheonan", name="4TB HDD", keyword="HDD",
                                  region_id="2292", max_price_krw=50000)
        for j in ("run1", "run2", "run3", "run4", "run5"):
            self.store.create_job(j, "hdd-cheonan")

    def test_schema_wal_foreign_keys_and_reinitialization(self):
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            names = {x[0] for x in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({"search_profiles", "collection_jobs", "listings",
                             "listing_observations", "listing_events"} <= names)
        again = HistoryStore(self.path, b"fixed-test-secret-" + b"x" * 32)
        again.create_profile("hdd-cheonan", name="4TB HDD", keyword="HDD",
                             region_id="2292", max_price_krw=50000)

    def test_stable_id_across_jobs_titles_profiles_and_secret_rotation(self):
        key = self.store.stable_key(URL)
        self.assertEqual(key, self.store.stable_key(URL_SAME_ID))
        self.assertNotEqual(key, self.store.stable_key(URL_OTHER))
        with self.assertRaisesRegex(ValueError, "HISTORY_DATABASE_HMAC_KEY_MISMATCH"):
            HistoryStore(self.path, b"other-test-secret" + b"x" * 32)
        alternate = HistoryStore(
            self.path.parent / "alternate.sqlite3", b"other-test-secret" + b"x" * 32)
        self.assertNotEqual(key, alternate.stable_key(URL))
        self.assertNotIn("abcdefghijkl", key)

    def test_initial_snapshot_no_event_then_price_drop_and_increase(self):
        a = self.store.ingest("run1", row("2026-11-10T00:00:00Z"))
        self.assertEqual(a["events"], [])
        b = self.store.ingest("run2", row("2026-11-10T03:00:00Z", price=40000))
        self.assertEqual(b["events"], ["PRICE_DROPPED"])
        c = self.store.ingest("run3", row("2026-11-10T06:00:00Z", price=45000))
        self.assertEqual(c["events"], ["PRICE_INCREASED"])
        changes = self.store.get_events(a["listing_key"])
        self.assertEqual([(x["event_type"], x["previous_value"], x["current_value"])
                          for x in changes],
                         [("PRICE_DROPPED", "50000", "40000"),
                          ("PRICE_INCREASED", "40000", "45000")])

    def test_idempotent_rerun_and_conflicting_same_job_fail_closed(self):
        item = row("2026-11-10T00:00:00Z")
        a = self.store.ingest("run1", item)
        b = self.store.ingest("run1", item)
        self.assertTrue(b["idempotent"])
        self.assertEqual(a["observation_id"], b["observation_id"])
        with self.assertRaisesRegex(ValueError, "CONFLICTING_SAME_JOB"):
            self.store.ingest("run1", replace(item, price_krw=1))
        self.assertEqual(len(self.store.get_observations(a["listing_key"])), 1)

    def test_description_digest_only_and_change_event(self):
        a = self.store.ingest("run1", row("2026-11-10T00:00:00Z",
                                           description="unused SMART information"))
        b = self.store.ingest("run2", row("2026-11-10T03:00:00Z",
                                           description="updated SMART information"))
        self.assertEqual(b["events"], ["DESCRIPTION_CHANGED"])
        observations = self.store.get_observations(a["listing_key"])
        self.assertTrue(all("description" not in v for v in observations))
        self.assertNotIn("updated SMART", str(observations))
        self.assertEqual(len(observations[0]["description_sha256"]), 64)

    def test_unverified_prices_and_descriptions_never_trigger_events(self):
        a = self.store.ingest("run1", row("2026-11-10T00:00:00Z"))
        unknown = row("2026-11-10T03:00:00Z", price_krw=None,
                      price_verified=False, description=None,
                      description_verified=False)
        self.assertEqual(self.store.ingest("run2", unknown)["events"], [])
        b = self.store.ingest("run3", row("2026-11-10T06:00:00Z", price=40000))
        self.assertEqual(b["events"], ["PRICE_DROPPED"])
        self.assertEqual(self.store.get_listing(a["listing_key"])["latest_observation_id"],
                         b["observation_id"])

    def test_transaction_ui_and_stock_are_orthogonal(self):
        self.store.ingest("run1", row(
            "2026-11-10T00:00:00Z", transaction_status="FOR_SALE",
            primary_status_verified=True))
        changed = self.store.ingest("run2", row(
            "2026-11-10T03:00:00Z", transaction_status="RESERVED",
            primary_status_verified=True, stock_availability="OUT_OF_STOCK"))
        self.assertEqual(changed["events"],
                         ["TRANSACTION_STATUS_CHANGED", "STOCK_AVAILABILITY_CHANGED"])
        self.assertEqual(self.store.get_events()[-1]["current_value"], "OUT_OF_STOCK")

    def test_stock_out_of_stock_never_infers_sold(self):
        self.store.ingest("run1", row("2026-11-10T00:00:00Z"))
        b = self.store.ingest("run2", row("2026-11-10T03:00:00Z",
                                           stock_availability="OUT_OF_STOCK"))
        self.assertEqual(b["events"], ["STOCK_AVAILABILITY_CHANGED"])
        self.assertEqual(self.store.get_observations(b["listing_key"])[-1]
                         ["transaction_status"], "NOT_OBSERVABLE")

    def test_advisory_record_cannot_change_trusted_baseline(self):
        a = self.store.ingest("run1", row("2026-11-10T00:00:00Z"))
        b = self.store.ingest("run2", row("2026-11-10T03:00:00Z", price=10000,
                                           evidence_level="ADVISORY"))
        self.assertEqual(b["events"], [])
        self.assertEqual(self.store.get_listing(a["listing_key"])["latest_observation_id"],
                         a["observation_id"])
        c = self.store.ingest("run3", row("2026-11-10T06:00:00Z", price=45000))
        self.assertEqual(c["events"], ["PRICE_DROPPED"])
        self.assertEqual(self.store.get_events()[-1]["previous_value"], "50000")

    def test_out_of_order_does_not_override_current_or_create_event(self):
        a = self.store.ingest("run1", row("2026-11-10T06:00:00Z"))
        earlier = self.store.ingest("run2", row("2026-11-10T03:00:00Z", price=30000))
        self.assertTrue(earlier["historical"])
        self.assertEqual(earlier["events"], [])
        self.assertEqual(self.store.get_listing(a["listing_key"])["latest_observation_id"],
                         a["observation_id"])

    def test_same_timestamp_conflict_rejected(self):
        self.store.ingest("run1", row("2026-11-10T00:00:00Z"))
        with self.assertRaisesRegex(ValueError, "CONFLICTING_SAME_TIMESTAMP"):
            self.store.ingest("run2", row("2026-11-10T00:00:00Z", price=45000))

    def test_same_listing_across_profiles_not_duplicated(self):
        self.store.create_profile("hdd-asan", name="HDD Asan", keyword="HDD",
                                  region_id="2333")
        self.store.create_job("asan1", "hdd-asan")
        a = self.store.ingest("run1", row("2026-11-10T00:00:00Z"))
        b = self.store.ingest("asan1", row("2026-11-10T03:00:00Z", price=45000))
        self.assertEqual(a["listing_key"], b["listing_key"])
        self.assertEqual(b["events"], ["PRICE_DROPPED"])
        self.assertEqual(len(self.store.get_observations(a["listing_key"])), 2)

    def test_invalid_evidence_must_not_modify_db(self):
        good = row("2026-11-10T00:00:00Z")
        failures = (
            replace(good, identity_verified=False),
            replace(good, canonical_url="https://evil.example/kr/buy-sell/x-abcdefghijkl/"),
            replace(good, canonical_url=URL + "?tracking=1"),
            replace(good, price_verified=False),
            replace(good, primary_status_verified=False, transaction_status="SOLD"),
            replace(good, primary_status_verified=True,
                    transaction_status="RESERVED", stock_availability="IN_STOCK"),
            replace(good, stock_verified=False),
            replace(good, description_verified=False),
            replace(good, observed_at_utc="2026-11-10T00:00:00"),
            replace(good, evidence_level="APPROVED"),
            replace(good, sale_filter_eligible=False, sale_state_inferred=True),
        )
        for bad in failures:
            with self.subTest(bad=bad):
                with self.assertRaises((ValueError, TypeError)):
                    self.store.ingest("run1", bad)
        self.assertEqual(self.store.get_events(), [])
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute(
                "SELECT count(*) FROM listing_observations").fetchone()[0], 0)

    def test_missing_search_result_is_never_a_sold_event(self):
        a = self.store.ingest("run1", row("2026-11-10T00:00:00Z"))
        self.store.finish_job("run2", succeeded=True)  # no result for this listing
        self.assertEqual(self.store.get_events(), [])
        self.assertEqual(self.store.get_listing(a["listing_key"])["latest_observation_id"],
                         a["observation_id"])
        with self.assertRaisesRegex(
                ValueError, "COMPLETED_JOB_CANNOT_ACCEPT_NEW_OBSERVATIONS"):
            self.store.ingest("run2", row("2026-11-10T03:00:00Z"))

    def test_owner_forget_deletes_all_listing_linked_rows(self):
        a = self.store.ingest("run1", row("2026-11-10T00:00:00Z"))
        self.store.ingest("run2", row("2026-11-10T01:00:00Z", price=40000))
        other = self.store.ingest("run3", row(
            "2026-11-10T02:00:00Z", canonical_url=URL_OTHER))
        result = self.store.forget_listing(a["listing_key"])
        self.assertTrue(result["deleted"])
        self.assertEqual(result["observations_removed"], 2)
        self.assertEqual(result["events_removed"], 1)
        self.assertIsNone(self.store.get_listing(a["listing_key"]))
        self.assertEqual(self.store.get_observations(a["listing_key"]), [])
        self.assertEqual(self.store.get_events(a["listing_key"]), [])
        self.assertIsNotNone(self.store.get_listing(other["listing_key"]))
        self.assertFalse(self.store.forget_listing(a["listing_key"])["deleted"])
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_verified_sold_is_deleted_not_unverified_or_stock_only(self):
        original = self.store.ingest("run1", row("2026-11-10T00:00:00Z"))
        self.store.ingest("run2", row(
            "2026-11-10T01:00:00Z", stock_availability="OUT_OF_STOCK"))
        self.assertIsNotNone(self.store.get_listing(original["listing_key"]))
        sold = self.store.ingest("run3", row(
            "2026-11-10T02:00:00Z", transaction_status="SOLD",
            primary_status_verified=True, stock_availability="OUT_OF_STOCK"))
        self.assertEqual(sold["listing_key"], original["listing_key"])
        self.assertIsNone(self.store.get_listing(original["listing_key"]))
        self.assertEqual(self.store.get_events(original["listing_key"]), [])
        self.assertEqual(self.store.purge_verified_sold()["listings_deleted"], 0)

    def test_invalid_forget_key_does_not_delete_records(self):
        original = self.store.ingest("run1", row("2026-11-10T00:00:00Z"))
        for invalid in ("../listing", "", original["listing_key"].upper()):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "INVALID_LISTING_KEY"):
                    self.store.forget_listing(invalid)
        self.assertIsNotNone(self.store.get_listing(original["listing_key"]))

    def test_bad_profile_or_job_references_rejected(self):
        with self.assertRaisesRegex(ValueError, "PROFILE_ID_CONFLICT"):
            self.store.create_profile("hdd-cheonan", name="different", keyword="HDD",
                                      region_id="2292")
        with self.assertRaisesRegex(ValueError, "JOB_ID_CONFLICT"):
            self.store.create_job("run1", "missing-profile")
        with self.assertRaisesRegex(ValueError, "JOB_NOT_ACCEPTING"):
            self.store.ingest("unknown", row("2026-11-10T00:00:00Z"))


if __name__ == "__main__":
    unittest.main()
