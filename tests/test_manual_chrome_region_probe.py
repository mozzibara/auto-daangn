# -*- coding: utf-8 -*-
"""All synthetic: manual Chrome region comparison, no browser or web access."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import time
import unittest

from daangn_v4_1_core import BY_KEY
from app_v5.manual_chrome_region import (
    SEARCH_URL, ManualSearchResponses, extract_route_summary,
    is_public_search, make_manual_report, sanitize_manual_report,
    classify_manual_observation, observe_manual_page,
)
from scripts.manual_chrome_region_probe import (
    chrome_args, read_debug_port, save_report, find_chrome,
)

REGION = BY_KEY["cheonan"]
REGION_URL = SEARCH_URL + "&in=" + REGION["slug"]


def route_payload(*, sid="2292", fid="2292", name="불당동"):
    return json.dumps({
        "data": {"routes": {"search": {
            "searchRegion": {"id": sid, "name": name},
            "currentFilters": {"regionId": fid},
            "buySellArticles": [{
                "href": "https://www.daangn.com/kr/buy-sell/PRIVATE_ID",
                "title": "PRIVATE_SELLER_LISTING", "description": "SECRET",
            }],
        }}},
    }, ensure_ascii=False).encode("utf-8")


class FakeResolver:
    def __init__(self, *, events=None, responses=1, blocked=False):
        self.events = events if events is not None else [
            {"state": "OBSERVED", "matches": ["2292"], "count": 15}
        ]
        self.responses = responses
        self.blocked = blocked


class FakeRoutes:
    def __init__(self, rows=None, blocked=False):
        self.rows = rows if rows is not None else [{
            "started_ms": 1001, "state": "OBSERVED",
            "request_region": "MISSING",
            "model": {
                "search_region": "EXPECTED", "filter_region": "EXPECTED",
                "name_state": "EXACT", "ids_agree": "YES",
            },
        }]
        self.blocked = blocked

    def after_click(self, epoch):
        return [e for e in self.rows if e["started_ms"] >= epoch]


def all_stages(last="EXPECTED"):
    return {
        "BEFORE": {"state": "REGION_INPUT_ONLY",
                   "selected_control": "OTHER"},
        "AT_CLICK": {"state": "TARGET_DIALOG_CHOICE",
                     "selected_control": "OTHER"},
        "AFTER_4000MS": {
            "state": "DIALOG_WITHOUT_CONTROLS",
            "selected_control": last,
        },
    }


def clicked(*, count=1, trusted=1, at=1000):
    return {"count": count, "trusted": trusted, "unique": True,
            "city": True, "at_ms": at}


class PublicUrlAndRouteTests(unittest.TestCase):
    def test_exact_public_url_only(self):
        self.assertTrue(is_public_search(SEARCH_URL))
        self.assertTrue(is_public_search(REGION_URL))
        for bad in (
            "https://evil.example/kr/search/buy-sell/?q=HDD",
            "http://www.daangn.com/kr/search/buy-sell/?q=HDD",
            "https://www.daangn.com/kr/buy-sell/a-abcdefghijk/?q=HDD",
            "https://www.daangn.com/kr/search/buy-sell/?q=SSD",
            "https://www.daangn.com/kr/search/buy-sell/?q=HDD&q=SSD",
            "https://www.daangn.com:9000/kr/search/buy-sell/?q=HDD",
            "INVALID_STRING",
        ):
            with self.subTest(url=bad):
                self.assertFalse(is_public_search(bad))

    def test_known_nested_route_schema_extracts_only_enums(self):
        x = extract_route_summary(route_payload(), REGION)
        self.assertEqual(x, {
            "search_region": "EXPECTED", "filter_region": "EXPECTED",
            "name_state": "EXACT", "ids_agree": "YES",
        })
        self.assertNotIn("PRIVATE", str(x))
        self.assertNotIn("2292", str(x))
        self.assertNotIn("불당동", str(x))

    def test_other_region_and_historical_drift_not_authorized(self):
        x = extract_route_summary(
            route_payload(sid="99999", fid="99999"), REGION)
        self.assertEqual(x["search_region"], "OTHER")
        self.assertEqual(x["filter_region"], "OTHER")
        self.assertEqual(x["name_state"], "EXACT")
        self.assertEqual(x["ids_agree"], "YES")
        self.assertNotIn("99999", str(x))

    def test_conflicting_missing_and_unknown_schemas_fail_closed(self):
        x = extract_route_summary(
            route_payload(sid="2292", fid="99999", name="다른지역"), REGION)
        self.assertEqual(x["filter_region"], "OTHER")
        self.assertEqual(x["ids_agree"], "NO")
        self.assertEqual(x["name_state"], "OTHER")
        self.assertIsNone(extract_route_summary(b'{"data":{}}', REGION))
        self.assertIsNone(extract_route_summary(b'not json', REGION))
        self.assertIsNone(extract_route_summary(b' ' * 2_000_001, REGION))
        self.assertIsNone(extract_route_summary(
            json.dumps({"both": [json.loads(route_payload()),
                                 json.loads(route_payload())]}).encode(), REGION))


class ComparisonAndPrivacyTests(unittest.TestCase):
    def report(self, **changes):
        args = {
            "status": "MANUAL_CLICK_OBSERVED",
            "click": clicked(), "resolver": FakeResolver(),
            "routes": FakeRoutes(), "page_url": REGION_URL,
            "stages": all_stages(),
        }
        args.update(changes)
        return make_manual_report(REGION, **args)

    def test_corroborated_manual_comparison_does_not_authorize_listings(self):
        a = self.report()
        self.assertEqual(a["comparison"], "UI_AND_ROUTE_EXPECTED_DIAGNOSTIC")
        self.assertEqual(a["route"]["status"], "UNIQUE_POSTCLICK_ROUTE")
        self.assertEqual(a["region_api"]["state"],
                         "UNIQUE_EXPECTED_API_CANDIDATE")
        self.assertTrue(a["region_api"]["preset_id_match"])
        self.assertFalse(a["authorizes_listings"])
        self.assertEqual(sanitize_manual_report(a), a)
        self.assertNotIn("2292", json.dumps(a))
        self.assertNotIn("PRIVATE", json.dumps(a))

    def test_missing_api_or_wrong_request_prevents_success(self):
        no_api = self.report(resolver=FakeResolver(events=[], responses=0))
        self.assertEqual(no_api["comparison"], "INCONCLUSIVE")
        wrong_query_region = self.report(routes=FakeRoutes(rows=[{
            **FakeRoutes().rows[0], "request_region": "OTHER"
        }]))
        self.assertEqual(wrong_query_region["comparison"], "INCONCLUSIVE")

    def test_well_proven_other_region_is_diagnostic_mismatch(self):
        other = FakeRoutes(rows=[{
            "started_ms": 1001, "state": "OBSERVED",
            "request_region": "MISSING",
            "model": {"search_region": "OTHER", "filter_region": "OTHER",
                      "name_state": "OTHER", "ids_agree": "YES"},
        }])
        result = self.report(routes=other, stages=all_stages(last="OTHER"))
        self.assertEqual(result["comparison"], "UI_AND_ROUTE_OTHER")
        self.assertFalse(result["authorizes_listings"])

    def test_route_response_predating_click_is_not_causal_evidence(self):
        x = FakeRoutes(rows=[{**FakeRoutes().rows[0], "started_ms": 999}])
        report = self.report(routes=x)
        self.assertEqual(report["route"]["status"], "NO_POSTCLICK_ROUTE")
        self.assertEqual(report["comparison"], "INCONCLUSIVE")

    def test_multiple_responses_or_clicks_are_not_strict_match(self):
        events = FakeRoutes().rows * 2
        r = self.report(routes=FakeRoutes(rows=events))
        self.assertEqual(r["route"]["status"], "MULTIPLE_POSTCLICK_ROUTES")
        self.assertEqual(r["comparison"], "INCONCLUSIVE")
        r = self.report(status="MULTIPLE_TARGET_CLICKS",
                        click=clicked(count=2, trusted=2))
        self.assertEqual(r["comparison"], "INCONCLUSIVE")

    def test_malicious_strings_and_nested_unknowns_never_leave_report(self):
        data = {
            "status": "PRIVATE_PERSON_URL",
            "manual_click": {"count": 900, "trusted_count": "PRIVATE",
                             "url": "https://secret.example"},
            "region_api": {"response_count": 999,
                           "state": "SECRET", "match_id": "2292"},
            "route": {"status": "MY_PRIVATE_REGION",
                      "name_state": "UNTRUSTED_ADDRESS",
                      "response_count": 400,
                      "listing": "PRIVATE_SELLER"},
            "page_region": "https://private.example/",
            "comparison": "PRIVATE",
            "stages": {"AFTER_4000MS": {
                "state": "PRIVATE", "selected_control": "PRIVATE",
                "raw_html": "<SECRET_HTML>", "visible_dialog_buttons": 300}},
            "access_token": "MY_SECRET_TOKEN", "authorizes_listings": True,
        }
        safe = sanitize_manual_report(data)
        self.assertEqual(sanitize_manual_report(safe), safe)
        self.assertFalse(safe["authorizes_listings"])
        self.assertEqual(safe["status"], "OBSERVATION_ERROR")
        self.assertEqual(safe["manual_click"]["count"], -1)
        self.assertEqual(safe["route"]["response_count"], -1)
        self.assertEqual(safe["stages"]["AFTER_4000MS"]["state"], "UNOBSERVABLE")
        for substring in ("PRIVATE", "SECRET", "2292", "MY_", "http", "access_token"):
            self.assertNotIn(substring, json.dumps(safe))



class MissingClickWitnessDiagnostics(unittest.TestCase):
    def test_zero_events_are_indeterminate_not_website_failure(self):
        x = classify_manual_observation(
            "NO_TARGET_CLICK",
            {"count": 0, "document_clicks": 0, "input_events": 0})
        self.assertEqual(x, "NO_DOCUMENT_ACTIVITY")
        r = make_manual_report(
            REGION, status="NO_TARGET_CLICK", click={
                "count": 0, "trusted": 0, "unique": False,
                "city": False, "at_ms": 0,
                "document_clicks": 0, "dialog_clicks": 0,
                "button_clicks": 0, "target_outside_dialog": 0,
                "input_events": 0, "region_input_events": 0,
                "focused": False,
            }, resolver=FakeResolver(events=[], responses=0),
            routes=FakeRoutes(rows=[]), page_url=SEARCH_URL,
            stages=all_stages(last="OTHER"), open_tab_count=2)
        self.assertEqual(r["status"], "NO_TARGET_CLICK")
        self.assertEqual(r["comparison"], "INCONCLUSIVE")
        self.assertEqual(r["observer_diagnostics"]["classification"],
                         "NO_DOCUMENT_ACTIVITY")
        self.assertEqual(r["observer_diagnostics"]["open_tab_count"], 2)
        self.assertEqual(r["observer_diagnostics"]["tracked_tab_focused"], "NO")
        self.assertFalse(r["authorizes_listings"])
        self.assertEqual(sanitize_manual_report(r), r)

    def test_click_activity_classes_distinguish_selector_vs_wrong_window(self):
        cases = (
            ({"document_clicks": 3, "dialog_clicks": 1,
              "input_events": 5}, "DIALOG_CLICK_WITHOUT_TARGET"),
            ({"document_clicks": 3, "dialog_clicks": 0,
              "input_events": 5}, "DOCUMENT_ACTIVITY_NO_DIALOG_CLICK"),
            ({"document_clicks": 1, "target_outside_dialog": 1},
             "TARGET_CLICK_OUTSIDE_DIALOG"),
            ({"count": 1, "document_clicks": 1},
             "TARGET_CLICK_OBSERVED"),
        )
        for data, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(
                    classify_manual_observation("NO_TARGET_CLICK", data),
                    expected)
        self.assertEqual(classify_manual_observation(
            "OBSERVER_LOST", {"document_clicks": 2}), "OBSERVER_LOST")

    def test_telemetry_sanitization_rejects_raw_strings_and_overflow(self):
        contaminated = {
            "status": "OBSERVER_LOST",
            "observer_diagnostics": {
                "classification": "DIALOG_CLICK_WITHOUT_TARGET",
                "document_clicks": 20, "dialog_clicks": "PRIVATE",
                "input_events": 9999, "region_input_events": 3,
                "tracked_tab_focused": "YES", "open_tab_count": 2,
                "cookies": "SECRET_TOKEN", "raw_target": "MY_PRIVATE_ADDRESS",
            },
        }
        once = sanitize_manual_report(contaminated)
        twice = sanitize_manual_report(once)
        self.assertEqual(once, twice)
        obs = once["observer_diagnostics"]
        self.assertEqual(obs["dialog_clicks"], -1)
        self.assertEqual(obs["input_events"], -1)
        self.assertEqual(obs["document_clicks"], 20)
        self.assertEqual(obs["region_input_events"], 3)
        self.assertEqual(obs["tracked_tab_focused"], "YES")
        for forbidden in ("PRIVATE", "SECRET", "cookies", "raw_target"):
            self.assertNotIn(forbidden, json.dumps(once))


class FakePageWithMissingClick:
    url = SEARCH_URL

    class Context:
        pages = [object()]

    context = Context()

    def __init__(self):
        self.callbacks = {}
        self.armed = False
        self.armed_at_instruction = False

    def on(self, name, cb):
        self.callbacks.setdefault(name, []).append(cb)

    def remove_listener(self, name, cb):
        self.callbacks[name].remove(cb)

    async def evaluate(self, script, arg=None):
        if "addEventListener('click'" in script:
            self.armed = True
            return True
        if "removeEventListener('click'" in script:
            self.armed = False
            return True
        if "auto_daangn_manual_chrome_v1" in script:
            return None
        return {"state": "REGION_INPUT_ONLY", "selected_control": "OTHER"}


class ArmingOrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_ready_message_callback_only_after_click_listener_installed(self):
        page = FakePageWithMissingClick()
        called = []

        def on_armed():
            called.append((
                page.armed,
                len(page.callbacks.get("request", [])),
                len(page.callbacks.get("response", [])),
            ))

        data = await observe_manual_page(
            page, REGION, timeout_sec=1, on_armed=on_armed)
        self.assertEqual(called, [(True, 1, 2)])
        self.assertEqual(data["status"], "OBSERVER_LOST")
        self.assertEqual(data["observer_diagnostics"]["classification"],
                         "OBSERVER_LOST")
        self.assertFalse(page.armed)
        self.assertFalse(page.callbacks["request"])
        self.assertFalse(page.callbacks["response"])
        self.assertFalse(data["authorizes_listings"])


class FakeRequest:
    def __init__(self, url=SEARCH_URL + "&_data=routes/kr.search.buy-sell._index",
                 *, method="GET", resource_type="fetch"):
        self.url = url
        self.method = method
        self.resource_type = resource_type


class FakeResponse:
    def __init__(self, request, *, status=200, body=None, headers=None):
        self.request = request
        self.url = request.url
        self.status = status
        self.headers = headers or {"content-type": "application/json"}
        self._body = body if body is not None else route_payload()
        self.calls = 0

    async def body(self):
        self.calls += 1
        return self._body


class BrowserEventsTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_browser_started_request_and_known_route_parsed(self):
        watcher = ManualSearchResponses(REGION)
        request = FakeRequest()
        response = FakeResponse(request)
        watcher.on_response(response)  # Not preobserved: ignore completely.
        self.assertEqual(response.calls, 0)
        watcher.on_request(request)
        watcher.on_response(response)
        await watcher.drain()
        self.assertEqual(response.calls, 1)
        self.assertEqual(len(watcher.events), 1)
        self.assertEqual(watcher.events[0]["state"], "OBSERVED")
        self.assertEqual(watcher.events[0]["model"]["search_region"], "EXPECTED")
        self.assertNotIn("PRIVATE", str(watcher.events))
        self.assertNotIn("2292", str(watcher.events))
        self.assertEqual(len(watcher.after_click(0)), 1)
        self.assertEqual(len(watcher.after_click(int(time()*1000)+1000)), 0)

    async def test_offsite_detail_post_and_unauthorized_body_never_read(self):
        watcher = ManualSearchResponses(REGION)
        for req in (
            FakeRequest("https://evil.example/kr/search/buy-sell/?q=HDD"),
            FakeRequest("https://www.daangn.com/kr/buy-sell/PRIVATE"),
            FakeRequest(method="POST"),
            FakeRequest(resource_type="document"),
        ):
            watcher.on_request(req)
            response = FakeResponse(req)
            watcher.on_response(response)
            self.assertEqual(response.calls, 0)
        allowed = FakeRequest()
        watcher.on_request(allowed)
        blocked = FakeResponse(allowed, status=403)
        watcher.on_response(blocked)
        self.assertTrue(watcher.blocked)
        self.assertEqual(blocked.calls, 0)

    async def test_oversize_body_header_skipped(self):
        watcher = ManualSearchResponses(REGION)
        req = FakeRequest()
        watcher.on_request(req)
        resp = FakeResponse(req, headers={
            "content-type": "application/json", "content-length": "99999999"})
        watcher.on_response(resp)
        await watcher.drain()
        self.assertEqual(resp.calls, 0)
        self.assertEqual(watcher.skipped, 1)


class IsolatedChromeCliTests(unittest.TestCase):
    def test_flags_only_loopback_ephemeral_port_with_disposable_profile(self):
        with TemporaryDirectory() as td:
            profile = Path(td) / "clean"
            profile.mkdir()
            args = chrome_args(Path("chrome.exe"), profile)
            self.assertIn("--remote-debugging-address=127.0.0.1", args)
            self.assertIn("--remote-debugging-port=0", args)
            self.assertIn("--disable-sync", args)
            self.assertIn("--new-window", args)
            self.assertIn(SEARCH_URL, args)
            self.assertIn(f"--user-data-dir={profile}", args)
            self.assertNotIn("--user-data-dir=Default", args)
            (profile / "Cookies").touch()
            with self.assertRaises(ValueError):
                chrome_args(Path("chrome.exe"), profile)

    def test_ephemeral_debug_port_accepts_only_valid_values(self):
        with TemporaryDirectory() as td:
            root=Path(td)
            self.assertIsNone(read_debug_port(root))
            marker=root/"DevToolsActivePort"
            marker.write_text("51234\n/devtools/browser/uuid", encoding="ascii")
            self.assertEqual(read_debug_port(root), 51234)
            for value in ("0", "65536", "abcdef", "22x\n", ""):
                marker.write_text(value, encoding="ascii")
                self.assertIsNone(read_debug_port(root))
            self.assertIsNone(find_chrome("/private/nonexistent/chrome.exe"))

    def test_optional_redacted_report_never_overwrites_old_file(self):
        with TemporaryDirectory() as td:
            output=Path(td)/"manual.json"
            safe=sanitize_manual_report({
                "status":"NO_TARGET_CLICK",
                "raw_secret":"PRIVATE LISTING URL",
            })
            save_report(output, safe)
            text=output.read_text(encoding="utf-8")
            self.assertNotIn("PRIVATE", text)
            self.assertFalse(json.loads(text)["authorizes_listings"])
            with self.assertRaises(FileExistsError):
                save_report(output, safe)
            self.assertEqual(output.read_text(encoding="utf-8"), text)


if __name__ == "__main__":
    unittest.main()
