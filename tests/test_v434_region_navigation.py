# -*- coding: utf-8 -*-
"""All synthetic: browser-navigation classification and privacy boundary tests."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app_v5.region_navigation import (
    RegionNavigationTrace, classify_browser_url, classify_commit_trace,
    sanitize_navigation_trace,
)
from daangn_v4_1_core import BY_KEY
from scripts.report_v434_failure import classify

REGION = BY_KEY["cheonan"]
URL = "https://www.daangn.com/kr/search/buy-sell/?q=HDD"


class FakeRequest:
    def __init__(self, url, resource_type="fetch", navigation=False):
        self.url = url
        self.resource_type = resource_type
        self._navigation = navigation

    def is_navigation_request(self):
        return self._navigation


class FakeFrame:
    def __init__(self, url):
        self.url = url


class FakePage:
    def __init__(self):
        self.url = URL
        self.main_frame = FakeFrame(URL)
        self.callbacks = {"request": [], "framenavigated": []}
        self.states = []

    def on(self, name, callback):
        self.callbacks[name].append(callback)

    def remove_listener(self, name, callback):
        self.callbacks[name].remove(callback)

    def emit(self, name, obj):
        for cb in list(self.callbacks[name]):
            cb(obj)

    async def evaluate(self, script, arg):
        self._last_script = script
        self._last_arg = arg
        return self.states.pop(0)


def snap(control, dialog="CLOSED", typed="MISSING"):
    return {"control": control, "dialog": dialog, "input": typed,
            "visible_controls": 1 if control != "NOT_VISIBLE" else 0,
            "visible_dialogs": 1 if dialog == "OPEN" else 0,
            "visible_inputs": 1 if typed != "MISSING" else 0}


class NavigationUrlTests(unittest.TestCase):
    def test_correct_target_vs_missing_vs_other_and_bad_host(self):
        expected = URL + "&in=%EB%B6%88%EB%8B%B9%EB%8F%99-2292"
        self.assertEqual(classify_browser_url(expected, REGION)["region"], "EXPECTED")
        self.assertEqual(classify_browser_url(URL, REGION)["region"], "MISSING")
        self.assertEqual(classify_browser_url(URL + "&in=elsewhere-999", REGION)["region"], "OTHER")
        self.assertEqual(classify_browser_url(expected + "&in=elsewhere-999", REGION)["region"], "INVALID")
        self.assertEqual(classify_browser_url("https://evil.example/?q=HDD&in=secret", REGION)["host"], "INVALID")
        self.assertEqual(classify_browser_url(URL + "&q=NOT-HDD", REGION)["keyword"], "OTHER")

    def test_visible_target_does_not_override_wrong_server(self):
        trace = {"checkpoints": {"AFTER_CLICK": snap("TARGET_VISIBLE"),
                                 "AFTER_SETTLE": snap("TARGET_VISIBLE")}}
        self.assertEqual(classify_commit_trace(trace, post_click_region="OTHER"),
                         "UI_TARGET_SERVER_OTHER")

    def test_reversion_is_distinct_from_no_witness(self):
        trace = {"checkpoints": {"AFTER_CLICK": snap("TARGET_VISIBLE"),
                                 "AFTER_SETTLE": snap("OTHER_VISIBLE")}}
        self.assertEqual(classify_commit_trace(trace, post_click_region="OTHER"),
                         "VISIBLE_TARGET_REVERTED_TO_OTHER")
        trace["checkpoints"]["AFTER_CLICK"] = snap("NOT_VISIBLE")
        trace["checkpoints"]["AFTER_SETTLE"] = snap("NOT_VISIBLE")
        self.assertEqual(classify_commit_trace(trace, post_click_region="OTHER"),
                         "NO_VISIBLE_COMMIT_SERVER_OTHER")

    def test_second_sanitizer_does_not_lose_url_classes(self):
        raw = {"checkpoints": {"AFTER_SETTLE": {**snap("OTHER_VISIBLE"),
                  "url": {"region": "MISSING", "path": "EXPECTED",
                          "keyword": "EXPECTED"}}},
               "events": [{"kind": "SEARCH_FETCH", "url": {
                   "region": "MISSING", "path": "EXPECTED",
                   "keyword": "EXPECTED"}}],
               "event_count": 1, "commit_class": "UI_OTHER_AND_SERVER_OTHER"}
        first = sanitize_navigation_trace(raw)
        second = sanitize_navigation_trace(first)
        self.assertEqual(second["checkpoints"]["AFTER_SETTLE"]["url_region"], "MISSING")
        self.assertEqual(second["events"][0]["url_path"], "EXPECTED")
        self.assertFalse(second["authorizes_listings"])

    def test_malicious_raw_content_is_always_discarded(self):
        injected = {"commit_class": "https://secret.example/cookie=SECRET",
                    "events": [{"kind": "SEARCH_FETCH", "url_region": "MY_PASSWORD",
                                "url_path": "EXPECTED",
                                "listing": "PRIVATE-SELLER-URL"}],
                    "checkpoints": {"AFTER_CLICK": {
                        "control": "private-token", "url_region": "SECRET",
                        "dialog": "HIDDEN-TEXT"}},
                    "other": "MY_PASSWORD", "event_count": 99999,
                    "authorizes_listings": True}
        result = sanitize_navigation_trace(injected)
        blob = json.dumps(result)
        for needle in ("SECRET", "PASSWORD", "PRIVATE", "token", "cookie"):
            self.assertNotIn(needle, blob)
        self.assertEqual(result["commit_class"], "NOT_OBSERVABLE")
        self.assertFalse(result["authorizes_listings"])
        self.assertEqual(result["event_count"], -1)


class NavigationCaptureTests(unittest.IsolatedAsyncioTestCase):
    async def test_three_real_checkpoint_order_and_passive_events(self):
        page = FakePage()
        page.states = [
            snap("OTHER_VISIBLE", "OPEN", "EXPECTED"),
            snap("OTHER_VISIBLE", "CLOSED", "MISSING"),
            snap("OTHER_VISIBLE", "CLOSED", "MISSING"),
        ]
        watcher = RegionNavigationTrace(REGION)
        watcher.arm(page)
        await watcher.checkpoint(page, "BEFORE_CLICK")
        page.emit("request", FakeRequest(URL))
        page.emit("framenavigated", page.main_frame)
        await watcher.checkpoint(page, "AFTER_CLICK")
        await watcher.checkpoint(page, "AFTER_SETTLE")
        watcher.stop()
        page.emit("request", FakeRequest(URL + "&secret=LEAK"))
        result = watcher.export(post_click_region="OTHER")
        self.assertEqual(result["event_count"], 2)
        self.assertEqual([x["kind"] for x in result["events"]],
                         ["SEARCH_FETCH", "MAIN_FRAME_NAVIGATED"])
        self.assertEqual(result["checkpoints"]["BEFORE_CLICK"]["dialog"], "OPEN")
        self.assertEqual(result["checkpoints"]["AFTER_SETTLE"]["control"], "OTHER_VISIBLE")
        self.assertEqual(result["commit_class"], "UI_OTHER_AND_SERVER_OTHER")
        self.assertEqual(page.callbacks["request"], [])
        self.assertFalse(result["authorizes_listings"])
        self.assertNotIn("secret", json.dumps(result).lower())
        self.assertNotIn("불당동", json.dumps(result, ensure_ascii=False))

    async def test_navigation_capture_cannot_treat_other_host_as_first_party(self):
        page = FakePage()
        watcher = RegionNavigationTrace(REGION)
        watcher.arm(page)
        page.emit("request", FakeRequest("https://another.example/kr/search/buy-sell/?q=HDD"))
        page.emit("request", FakeRequest(URL, resource_type="document", navigation=True))
        watcher.stop()
        result = watcher.export()
        self.assertEqual(result["event_count"], 1)
        self.assertEqual(result["events"][0]["kind"], "DOCUMENT_REQUEST")


class PublicReportTests(unittest.TestCase):
    def test_public_report_keeps_only_navigation_classes_and_no_listing(self):
        with TemporaryDirectory() as td:
            folder = Path(td)
            watcher = sanitize_navigation_trace({
                "commit_class": "NO_VISIBLE_COMMIT_SERVER_OTHER",
                "event_count": 1, "events": [{"kind": "SEARCH_FETCH",
                   "url": {"region": "MISSING", "path": "EXPECTED",
                           "keyword": "EXPECTED"}}],
                "checkpoints": {
                    "AFTER_CLICK": {**snap("NOT_VISIBLE"),
                                    "url": {"region": "MISSING", "path": "EXPECTED",
                                            "keyword": "EXPECTED"}},
                    "AFTER_SETTLE": {**snap("NOT_VISIBLE"),
                                    "url": {"region": "MISSING", "path": "EXPECTED",
                                            "keyword": "EXPECTED"}},
                }})
            payload = {"evaluation": {"contexts": [{
                "context": "cheonan_a",
                "capture_failure_code": "FRESH_REGION_PROOF_MISSING",
                "region_picker": {"navigation_trace": {
                    **watcher, "listing_url": "SECRET-LISTING",
                    "checkpoints": {**watcher["checkpoints"],
                       "BEFORE_CLICK": {"control": "secret-region-123"}}}}
            }]}}
            (folder / "v423_public_controls_results.json").write_text(
                json.dumps(payload), encoding="utf-8")
            reported = classify(folder)
            self.assertEqual(reported["NAV_TRACE_COMMIT_CLASS"],
                             "NO_VISIBLE_COMMIT_SERVER_OTHER")
            self.assertEqual(reported["NAV_AFTER_SETTLE_URL_REGION"], "MISSING")
            self.assertEqual(reported["NAV_TRACE_EVENT_SEQUENCE"],
                             "SEARCH_FETCH:MISSING:EXPECTED")
            self.assertEqual(reported["NAV_TRACE_AUTHORIZES_LISTINGS"], "NO")
            self.assertNotIn("SECRET-LISTING", str(reported))
            self.assertNotIn("secret-region", str(reported))


if __name__ == "__main__":
    unittest.main()
