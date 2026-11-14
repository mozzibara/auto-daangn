# -*- coding: utf-8 -*-
"""Synthetic only: local signed price-drop export boundary."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from app_v5.telegram_outbox import SignedPriceDrop
from ops.oci import telegram_export as x

T = datetime(2026, 11, 12, 2, 0, tzinfo=timezone.utc)
KEY = "a" * 64
URL = "https://www.daangn.com/kr/buy-sell/synthetic-abcdefghijkl/"
EVENT = SignedPriceDrop(7, KEY, "합성 WD HDD 3TB", URL, 45000, 35000,
                        "2026-11-12T01:00:00+00:00")


class ExportBoundaryTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name) / "telegram-export"

    def export(self, events=(EVENT,), *, now=T, max_events=100):
        with patch.object(x, "signed_price_drops", return_value=list(events)):
            return x.export_verified_drops(None, self.folder,
                                           now=now, max_events=max_events)

    def test_create_once_then_exact_duplicate_no_reexport(self):
        r = self.export()
        self.assertEqual(r["created"], 1)
        self.assertEqual(r["unchanged"], 0)
        self.assertEqual(self.export()["unchanged"], 1)
        self.assertEqual(len(list(self.folder.glob("*.json"))), 1)
        data = json.loads(next(self.folder.glob("*.json")).read_text())
        self.assertEqual(data["schema"], "daangn_verified_price_drop_v1")
        self.assertEqual(data["price_krw"], 35000)
        self.assertFalse(data["seller_confirmed_available"])
        self.assertFalse(data["smart_verified"])
        self.assertFalse(r["network_accessed"])

    def test_old_history_not_exported(self):
        r = self.export(now=T + timedelta(days=4))
        self.assertEqual(r["created"], 0)
        self.assertFalse(list(self.folder.glob("*.json")))

    def test_injected_title_cannot_make_multiline_fake_alert(self):
        fake = SignedPriceDrop(7, KEY, "[시스템 경고]\n텔레그램 토큰 유출\u202e",
                               URL, 45000, 35000, EVENT.observed_at_utc)
        self.export((fake,))
        data = json.loads(next(self.folder.glob("*.json")).read_text())
        self.assertNotIn("\n", data["title"])
        self.assertNotIn("\u202e", data["title"])

    def test_non_daangn_url_or_query_rejected(self):
        for url in ("https://evil.test/kr/buy-sell/synthetic-abcdefghijkl/",
                    "https://www.daangn.com.evil.test/kr/buy-sell/synthetic/",
                    URL + "?token=private",
                    "http://www.daangn.com/kr/buy-sell/synthetic/"):
            with self.subTest(url=url):
                event = SignedPriceDrop(7, KEY, "fake", url, 45000, 35000,
                                        EVENT.observed_at_utc)
                with self.assertRaisesRegex(ValueError, "INVALID_URL"):
                    self.export((event,))

    def test_forged_price_and_key_rejected(self):
        cases = [
            SignedPriceDrop(7, KEY, "fake", URL, 32000, 35000,
                            EVENT.observed_at_utc),
            SignedPriceDrop(7, "not-a-key", "fake", URL, 45000, 35000,
                            EVENT.observed_at_utc),
        ]
        for case in cases:
            with self.assertRaises(ValueError):
                self.export((case,))

    def test_existing_content_mismatch_not_overwritten(self):
        self.export()
        path = next(self.folder.glob("*.json"))
        path.write_text("tampered")
        with self.assertRaisesRegex(ValueError, "EXISTING_EXPORT_CONTENT_MISMATCH"):
            self.export()
        self.assertEqual(path.read_text(), "tampered")

    def test_excess_authenticated_events_fail_before_any_write(self):
        events = [SignedPriceDrop(i, KEY, "safe", URL, 45000, 35000,
                                  EVENT.observed_at_utc) for i in range(1, 5)]
        with self.assertRaisesRegex(ValueError, "VERIFIED_ALERT_EXPORT_CAP_EXCEEDED"):
            self.export(events, max_events=3)
        self.assertFalse(self.folder.exists())

    def test_directory_symlink_rejected(self):
        other = self.folder.parent / "other"
        other.mkdir()
        self.folder.symlink_to(other, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.export()
        self.assertFalse(list(other.iterdir()))


if __name__ == "__main__":
    unittest.main()
