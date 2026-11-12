# -*- coding: utf-8 -*-
"""Privacy and no-marketplace safety tests; synthetic only.

The CI Chrome Stable job runs a real local HTML event fixture separately.
"""
from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch

from app_v5.region_input_events import (
    EVENTS, RegionInputEventWitness, sanitize_input_events,
)
from scripts.chrome_stable_input_compare import (
    check_public_robots, sanitize_attempt, main as compare_main,
)
from daangn_v4_1_core import BY_KEY, ui_select_region


class FakeRequestResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, maximum):
        # Minimal, intentionally disallow all other paths
        return b"User-agent: *\nAllow: /kr/search/buy-sell/\n"


class EventSafetyTests(unittest.TestCase):
    def test_private_input_characters_never_reach_report(self):
        data = {
            "armed": True,
            "counts": {k: 3 for k in EVENTS},
            "trusted": {k: 1 for k in EVENTS},
            "sequence": ["FOCUS", "KEYDOWN", "INPUT", "KEYUP",
                         "PRIVATE_PASSWORD", "COMPOSITIONEND"],
            "overflow": True,
            "input_value": "MY_PRIVATE_PASSWORD",
            "raw_key": "불당동", "private_user_id": "12345678",
        }
        once = sanitize_input_events(data)
        twice = sanitize_input_events(once)
        self.assertEqual(once, twice)
        self.assertEqual(once["sequence"], [
            "FOCUS", "KEYDOWN", "INPUT", "KEYUP", "COMPOSITIONEND"])
        self.assertTrue(once["truncated"])
        self.assertFalse(once["authorizes_listings"])
        for secret in ("PRIVATE", "불당동", "12345678", "input_value"):
            self.assertNotIn(secret, json.dumps(once, ensure_ascii=False))

    def test_malformed_counts_and_boolean_values_fail_closed(self):
        malicious = {"armed": "yes", "counts": {"INPUT": True, "KEYUP": 9999},
                     "trusted": {"INPUT": -1, "FOCUS": 2},
                     "sequence": [{"url": "SECRET"}, 3, "CLICK", "INPUT"]}
        safe = sanitize_input_events(malicious)
        self.assertFalse(safe["armed"])
        self.assertEqual(safe["counts"]["INPUT"], -1)
        self.assertEqual(safe["counts"]["KEYUP"], -1)
        self.assertEqual(safe["trusted"]["FOCUS"], 2)
        self.assertEqual(safe["sequence"], ["INPUT"])
        self.assertFalse(safe["authorizes_listings"])

    def test_published_attempt_is_only_whitelisted_categories(self):
        raw = {"mode": "SEQUENTIAL_KEYS", "status": "REGION_NOT_COMMITTED",
               "input_events": {"counts": {"INPUT": 3},
                                "sequence": ["INPUT", "OWNER_PRIVATE_URL"]},
               "native_click": "YES",
               "route_status": "ONE_FRESH",
               "route_responses": 1,
               "server_search": "OTHER",
               "server_filter": "OTHER",
               "selected_ui": "OTHER",
               "api_ready": True,
               "unknown_region": "MY_SECRET_ADDRESS",
               "private_listing_url": "https://private.example/"}
        safe = sanitize_attempt(raw)
        self.assertEqual(safe["mode"], "SEQUENTIAL_KEYS")
        self.assertEqual(safe["status"], "REGION_NOT_COMMITTED")
        self.assertEqual(safe["input_events"]["sequence"], ["INPUT"])
        self.assertFalse(safe["authorizes_listings"])
        self.assertEqual(sanitize_attempt(safe), safe)
        self.assertNotIn("MY_SECRET", json.dumps(safe))
        self.assertNotIn("private.example", json.dumps(safe))

    def test_marketplace_live_cannot_run_without_exact_owner_approval(self):
        self.assertEqual(compare_main(["--live"]), 2)
        self.assertEqual(compare_main([
            "--live", "--owner-approval", "UNKNOWN"]), 2)

    def test_robots_allow_only_exact_public_page(self):
        self.assertTrue(check_public_robots(
            getter=lambda *args, **kwargs: FakeRequestResponse()))

    def test_robots_http_error_and_exception_fail_closed(self):
        class Denied(FakeRequestResponse):
            status = 403
        self.assertFalse(check_public_robots(
            getter=lambda *args, **kwargs: Denied()))

        def fail(*args, **kwargs):
            raise TimeoutError("PRIVATE_URL")

        self.assertFalse(check_public_robots(getter=fail))


class FakeLocator:
    def __init__(self):
        self.clicks = 0
        self.sequential = 0
        self.fills = 0
        self.text = ""

    @property
    def first(self):
        return self

    def filter(self, **kwargs):
        return self

    async def count(self):
        return 1

    async def is_visible(self):
        return True

    async def input_value(self):
        return self.text

    async def press_sequentially(self, value, **kwargs):
        self.sequential += 1
        self.text += value

    async def fill(self, value, **kwargs):
        self.fills += 1
        self.text = value

    async def click(self, **kwargs):
        self.clicks += 1

    async def evaluate(self, *args):
        return {"option_metadata": "OBSERVED",
                "option_city_hint": True,
                "option_tag": "BUTTON"}


class FakePage:
    url = "https://www.daangn.com/kr/search/buy-sell/?q=HDD"

    def __init__(self):
        self.top = FakeLocator()
        self.box = FakeLocator()
        self.option = FakeLocator()

    def get_by_role(self, *args, **kwargs):
        return self.top

    def locator(self, selector):
        return self.box if "input[placeholder" in selector else self.option

    async def wait_for_timeout(self, ms):
        pass


class AsyncBeforeInputTests(unittest.IsolatedAsyncioTestCase):
    async def test_awaits_instrumentation_before_actual_input_each_mode(self):
        for mode in ("FILL", "SEQUENTIAL_KEYS"):
            with self.subTest(mode=mode):
                page = FakePage()
                order = []

                async def arm():
                    order.append(("ARM", page.box.text, page.option.clicks))
                    await asyncio.sleep(0)

                async def ready():
                    order.append(("READY", page.box.text, page.option.clicks))
                    return {"state": "READY"}

                r = await ui_select_region(
                    page, BY_KEY["cheonan"], on_before_search=arm,
                    on_after_search_fill=ready,
                    search_input_mode=mode, first_activation_mode="POINTER_CLICK")
                self.assertTrue(r["selected_suggestion"])
                self.assertEqual(order, [
                    ("ARM", "", 0),
                    ("READY", BY_KEY["cheonan"]["term"], 0),
                ])
                self.assertEqual(page.option.clicks, 1)
                self.assertEqual(page.box.sequential, 1 if mode == "SEQUENTIAL_KEYS" else 0)
                self.assertEqual(page.box.fills, 1 if mode == "FILL" else 0)


if __name__ == "__main__":
    unittest.main()
