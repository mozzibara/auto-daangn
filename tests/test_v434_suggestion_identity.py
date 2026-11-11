# -*- coding: utf-8 -*-
"""Offline-only region resolver evidence and no-leakage regression."""
from __future__ import annotations

import json
from types import SimpleNamespace
import unittest

import daangn_v4_1_core as core
from app_v5.region_suggestion import (
    inspect_locations, classify_suggestion_identity,
    sanitize_suggestion_identity, RegionSuggestionObserver,
)
from app_v5.region_transition import sanitize_picker_transition

REGION = core.BY_KEY["cheonan"]


def api(rid="2292", name="불당동", city="천안시 서북구"):
    return {"locations": [{"id": rid, "name1": "충청남도",
                           "name2": city, "name3": name}]}


def search(sid="2292", fid="2292", name="불당동"):
    return {"model": {"region_id": sid, "filter_region_id": fid,
                      "search_region_name": name}}


class FakeResponse:
    def __init__(self, body: bytes, *, url=None, status=200):
        self.url = (url or "https://www.daangn.com/kr/api/v1/regions/"
                    "keyword?keyword=%EB%B6%88%EB%8B%B9%EB%8F%99")
        self.request = SimpleNamespace(resource_type="fetch")
        self.headers = {"content-type": "application/json"}
        self.status = status
        self.payload = body

    async def body(self):
        return self.payload


class ResolverTests(unittest.TestCase):
    def test_unique_exact_city_term_can_be_compared_in_ram(self):
        observed = inspect_locations(api("900001"), REGION)
        self.assertEqual(observed["matches"], ["900001"])
        result = classify_suggestion_identity(REGION, [observed],
                                              [search("900001", "900001")])
        self.assertEqual(result["state"], "UNIQUE_API_CANDIDATE_CORRELATED")
        self.assertFalse(result["preset_id_matches_candidate"])
        self.assertTrue(result["candidate_matches_post_click_search_ids"])
        self.assertTrue(result["post_click_name_matches_target"])
        self.assertNotIn("900001", str(sanitize_suggestion_identity(result)))

    def test_default_location_after_click_is_not_considered_preset_drift(self):
        observed = inspect_locations(api("900001"), REGION)
        result = classify_suggestion_identity(
            REGION, [observed], [search("800000", "800000", "다른동네")])
        self.assertFalse(result["preset_id_matches_candidate"])
        self.assertFalse(result["candidate_matches_post_click_search_ids"])
        self.assertFalse(result["post_click_name_matches_target"])

    def test_exact_dong_but_wrong_city_not_matching(self):
        observed = inspect_locations(api("900001", city="다른 시"), REGION)
        self.assertEqual(observed["matches"], [])
        self.assertEqual(classify_suggestion_identity(
            REGION, [observed], [search()])["state"],
            "NO_EXACT_CITY_TERM_MATCH")

    def test_duplicate_resolver_response_fails_closed(self):
        observed = inspect_locations(api(), REGION)
        result = classify_suggestion_identity(REGION, [observed, observed],
                                              [search()])
        self.assertEqual(result["state"], "AMBIGUOUS_RESOLVER_RESPONSES")

    def test_unsupported_schema_stays_unknown(self):
        observed = inspect_locations({"articles": [{"id":"123"}]}, REGION)
        self.assertEqual(observed["state"], "SCHEMA_NOT_RECOGNIZED")
        self.assertEqual(classify_suggestion_identity(
            REGION, [observed], [])["state"], "RESOLVER_SCHEMA_UNKNOWN")

    def test_injected_unknown_id_and_text_never_leave_sanitizer(self):
        result = sanitize_picker_transition({"suggestion": {
            "state": "https://attacker/SECRET",
            "api_location_count": 400000,
            "raw_user_text": "private seller",
            "candidate_matches_post_click_search_ids": "YES",
        }})
        dumped = json.dumps(result)
        self.assertEqual(result["suggestion"]["state"], "UNKNOWN")
        self.assertEqual(result["suggestion"]["api_location_count"], -1)
        self.assertNotIn("private seller", dumped)
        self.assertNotIn("attacker", dumped)
        self.assertFalse(result["suggestion"][
            "candidate_matches_post_click_search_ids"])


class PassiveNetworkTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_ui_emitted_resolver_response_is_parsed(self):
        observer = RegionSuggestionObserver(REGION)
        observer.on_response(FakeResponse(json.dumps(api()).encode()))
        await observer.drain()
        self.assertEqual(len(observer.events), 1)
        self.assertEqual(observer.events[0]["matches"], ["2292"])

    async def test_never_inspect_unrelated_or_wrong_keyword(self):
        observer = RegionSuggestionObserver(REGION)
        observer.on_response(FakeResponse(
            json.dumps(api()).encode(),
            url="https://www.daangn.com/kr/api/v1/regions/keyword?keyword=SSD"))
        observer.on_response(FakeResponse(
            json.dumps(api()).encode(),
            url="https://example.invalid/kr/api/v1/regions/keyword?keyword=불당동"))
        await observer.drain()
        self.assertEqual(observer.responses, 0)
        self.assertEqual(observer.events, [])

    async def test_access_restrictions_are_flagged(self):
        observer = RegionSuggestionObserver(REGION)
        observer.on_response(FakeResponse(b"", status=429))
        await observer.drain()
        self.assertTrue(observer.blocked)
        self.assertFalse(observer.events)


if __name__ == "__main__":
    unittest.main()
