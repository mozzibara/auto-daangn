# -*- coding: utf-8 -*-
"""Price echo versus server-declared maximum are distinct evidence tiers.

No live site calls and no listing fields retained or exported.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from daangn_v4_5_evidence import parse_observed_max_only_price
from app_v5.precollection_filter_gate import (
    _price_echo_state, inspect_dynamic_filtered_response,
    inspect_dynamic_filtered_response_details,
    PassiveFilteredRoute, sanitize_precollection,
    verify_filter_before_collection,
)

ROOT = "https://www.daangn.com/kr/search/buy-sell/"
PAGE = ROOT + "?q=HDD&category_id=1&price=__50000&only_on_sale=true"
DYNAMIC = PAGE + "&" + urlencode({"_data": "routes/v2.kr.search.buy-sell._index"})
EVENTS = ("POINTERDOWN", "POINTERUP", "MOUSEDOWN", "MOUSEUP", "CLICK")
UI = {"complete": True, "category": True, "available": True,
      "maximum": 50000, "minimum": 0}


def payload(filters):
    return json.dumps({"data": {"routes/anything": {
        "searchRegion": {"id": 2292},
        "currentFilters": {
            "regionId": 2292, "categoryId": 1, "onlyOnSale": True, **filters,
        },
        "buySellArticles": [{
            "seller": "PRIVATE_SELLER", "title": "PRIVATE_ITEM",
            "href": "https://private.invalid/PRIVATE_LINK",
        }],
    }}}).encode("utf-8")


class EchoClassifierTests(unittest.TestCase):
    def test_historical_max_only_syntax_is_reused(self):
        for encoded, expected in (
            ("__50000", 50000),
            ("__60000", 60000),
            ("__999999999", 999999999),
            ("__0", None),
            ("__50000__0", None),
            ("_50000", None),
            ("__abc", None),
        ):
            with self.subTest(encoded=encoded):
                self.assertEqual(
                    parse_observed_max_only_price(encoded), expected)

    def test_matching_echo_never_upgrades_price_max(self):
        verdict, shape, echo = inspect_dynamic_filtered_response_details(
            payload({"price": "__50000"}))
        self.assertEqual(verdict, {
            "region": "EXPECTED", "category": "EXPECTED",
            "available": "EXPECTED", "price_max": "MISSING"})
        self.assertEqual(shape, "UNTRUSTED_PRICE_ONLY")
        self.assertEqual(echo, "ENCODED_MAX_MATCH")
        self.assertEqual(
            inspect_dynamic_filtered_response(payload({"price": "__50000"})),
            (verdict, shape))

    def test_mismatched_echo_is_explicit_but_not_server_price_proof(self):
        for value in ("__49999", "__75000", "__900000000"):
            with self.subTest(value=value):
                verdict, shape, echo = inspect_dynamic_filtered_response_details(
                    payload({"price": value}))
                self.assertEqual(verdict["price_max"], "MISSING")
                self.assertEqual(shape, "UNTRUSTED_PRICE_ONLY")
                self.assertEqual(echo, "ENCODED_MAX_OTHER")

    def test_unknown_string_and_non_string_never_leak_values(self):
        for value, expected in (
            ("50000", "UNRECOGNIZED_STRING"),
            ("PRIVATE_PRICE_COOKIE", "UNRECOGNIZED_STRING"),
            ("__-50000", "UNRECOGNIZED_STRING"),
            ("", "UNRECOGNIZED_STRING"),
            (50000, "NON_STRING_VALUE"),
            (False, "NON_STRING_VALUE"),
            (None, "NON_STRING_VALUE"),
            ({"min":0,"max":50000}, "NON_STRING_VALUE"),
            (["PRIVATE"], "NON_STRING_VALUE"),
        ):
            with self.subTest(kind=type(value).__name__):
                verdict, shape, echo = inspect_dynamic_filtered_response_details(
                    payload({"price": value}))
                self.assertEqual(verdict["price_max"], "MISSING")
                self.assertEqual(shape, "UNTRUSTED_PRICE_ONLY")
                self.assertEqual(echo, expected)
                self.assertNotIn("PRIVATE", json.dumps([verdict,shape,echo]))

    def test_direct_or_nested_server_max_has_separate_authority(self):
        for fields, shape in (
            ({"maxPrice": 50000, "price": "__50000"}, "DIRECT_ALIAS"),
            ({"priceRange": {"max":50000}, "price":"__50000"},
             "NESTED_PRICE_RANGE_MAX"),
        ):
            with self.subTest(shape=shape):
                verdict, got_shape, echo = inspect_dynamic_filtered_response_details(
                    payload(fields))
                self.assertEqual(verdict["price_max"], "EXPECTED")
                self.assertEqual(got_shape, shape)
                self.assertEqual(echo, "ENCODED_MAX_MATCH")

    def test_direct_server_max_conflict_is_not_rescued_by_echo(self):
        verdict, shape, echo = inspect_dynamic_filtered_response_details(
            payload({"maxPrice": 90000, "price": "__50000"}))
        self.assertEqual(verdict["price_max"], "OTHER")
        self.assertEqual(shape, "DIRECT_ALIAS")
        self.assertEqual(echo, "ENCODED_MAX_MATCH")

    def test_no_price_field_and_missing_model(self):
        verdict, shape, echo = inspect_dynamic_filtered_response_details(
            payload({}))
        self.assertEqual(verdict["price_max"], "MISSING")
        self.assertEqual((shape, echo), ("ABSENT", "ABSENT"))
        verdict, shape, echo = inspect_dynamic_filtered_response_details(b"no json")
        self.assertEqual(verdict["price_max"], "MISSING")
        self.assertEqual((shape, echo), ("NO_SEARCH_MODEL", "NO_SEARCH_MODEL"))
        self.assertEqual(_price_echo_state(None), "NO_SEARCH_MODEL")

    def test_no_raw_strings_or_unlisted_price_values_in_report(self):
        row = sanitize_precollection({
            "dynamic_loader_price_echo": "ENCODED_MAX_MATCH",
            "dynamic_loader_server_filters":{"price_max":"MISSING"},
            "raw_response": "PRIVATE_BODY",
            "authorizes_listings": True,
            "collection_started": True,
            "database_written": True,
        })
        self.assertEqual(row["dynamic_loader_price_echo"], "ENCODED_MAX_MATCH")
        self.assertEqual(row["dynamic_loader_server_filters"]["price_max"],
                         "MISSING")
        self.assertFalse(row["authorizes_listings"])
        self.assertFalse(row["database_written"])
        self.assertEqual(sanitize_precollection(row), row)
        self.assertNotIn("PRIVATE", json.dumps(row))

    def test_malicious_echo_is_unobservable(self):
        row = sanitize_precollection({
            "dynamic_loader_price_echo": "PRIVATE_QUERY_KEY",
            "raw_slug": "PRIVATE_REGION",
            "authorizes_listings": True,
        })
        self.assertEqual(row["dynamic_loader_price_echo"], "UNOBSERVABLE")
        self.assertFalse(row["authorizes_listings"])
        self.assertNotIn("PRIVATE", json.dumps(row))


class Request:
    method = "GET"
    resource_type = "fetch"
    url = DYNAMIC


class Response:
    status = 200
    headers = {"content-type": "application/json"}
    def __init__(self, request, source):
        self.request = request
        self.url = request.url
        self.source = source
        self.reads = 0
    async def body(self):
        self.reads += 1
        return self.source


class Page:
    def __init__(self, source):
        self.url = ROOT + "?q=HDD"
        self.source = source
        self.hooks = {}
        self.click_count = 0
        self.responses = []
    def on(self, name, callback):
        self.hooks.setdefault(name, []).append(callback)
    def remove_listener(self, name, callback):
        self.hooks[name].remove(callback)
    async def evaluate(self, script):
        return {"armed": True,
                "counts": {name:1 for name in EVENTS},
                "trusted": {name:1 for name in EVENTS}}
    async def wait_for_timeout(self, ms):
        return


class Button:
    def __init__(self, page):
        self.page = page
    async def is_enabled(self):
        return True
    async def evaluate(self, script):
        return True
    async def click(self, **kwargs):
        self.page.click_count += 1
        self.page.url = PAGE
        request = Request()
        self.page.hooks["request"][0](request)
        response = Response(request, self.page.source)
        self.page.responses.append(response)
        self.page.hooks["response"][0](response)


class PassiveOperatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_owner_v2_echo_match_still_does_not_authorize_collection(self):
        page = Page(payload({"price": "__50000"}))
        button = Button(page)
        async def select(*args, **kwargs):
            return button, UI
        async def no_recheck(*args):
            raise AssertionError("post-Apply UI was not authorized or observed")
        with (
            patch("app_v5.precollection_filter_gate.v46.set_filter", select),
            patch("app_v5.precollection_filter_gate.v46.check_after", no_recheck),
        ):
            result = await verify_filter_before_collection(
                page, passive_dynamic_loader=True)
        self.assertEqual(page.click_count, 1)
        self.assertEqual(page.responses[0].reads, 1)
        self.assertEqual(result["dynamic_loader_metadata_status"], "ONE_PARSED")
        self.assertEqual(result["dynamic_loader_price_shape"],
                         "UNTRUSTED_PRICE_ONLY")
        self.assertEqual(result["dynamic_loader_price_echo"],
                         "ENCODED_MAX_MATCH")
        self.assertEqual(result["dynamic_loader_server_filters"]["price_max"],
                         "MISSING")
        self.assertEqual(result["status"], "BLOCKED_FILTER_URL")
        self.assertFalse(result["strict_filter_evidence"])
        self.assertFalse(result["ui_selected_after_apply"])
        self.assertFalse(result["authorizes_listings"])
        self.assertFalse(result["collection_started"])
        self.assertFalse(result["database_written"])
        self.assertFalse(result["listing_fields_read_or_exported"])
        self.assertNotIn("PRIVATE", json.dumps(result))

    async def test_default_mode_does_not_read_unknown_dynamic_body(self):
        page = Page(payload({"price": "__50000"}))
        button = Button(page)
        async def select(*args, **kwargs):
            return button, UI
        with patch("app_v5.precollection_filter_gate.v46.set_filter", select):
            result = await verify_filter_before_collection(page)
        self.assertEqual(page.responses[0].reads, 0)
        self.assertEqual(result["dynamic_loader_price_echo"], "UNOBSERVABLE")
        self.assertFalse(result["authorizes_listings"])


if __name__ == "__main__":
    unittest.main()
