# -*- coding: utf-8 -*-
"""Offline server price metadata path tests for owner-approved V2 probe.

The native web search response is represented by synthetic fixtures only.
Unknown article fields are not traversed or published, and missing
response price metadata cannot be substituted by price=__50000 in the URL.
"""
from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from app_v5.precollection_filter_gate import (
    PassiveFilteredRoute, _price_value_and_shape,
    inspect_dynamic_filtered_response, inspect_filtered_response,
    sanitize_precollection, verify_filter_before_collection,
)

PAGE = (
    "https://www.daangn.com/kr/search/buy-sell/"
    "?q=HDD&category_id=1&price=__50000&only_on_sale=true"
)
ROUTE = PAGE + "&" + urlencode({"_data": "routes/v2.kr.search.buy-sell._index"})
_EVENTS = ("POINTERDOWN", "POINTERUP", "MOUSEDOWN", "MOUSEUP", "CLICK")
_SELECTED = {
    "complete": True, "category": True,
    "available": True, "maximum": 50000, "minimum": 0,
}


def make_payload(filters, *, duplicate_search_models=False):
    """Fake response includes private article data to prove redaction."""
    model = {
        "searchRegion": {"id": 2292},
        "currentFilters": {
            "regionId": 2292,
            "categoryId": 1,
            "onlyOnSale": True,
            **filters,
        },
        "buySellArticles": [{
            "href": "https://private.invalid/PRIVATE_ITEM_URL",
            "seller": "PRIVATE_SELLER_NAME",
            "title": "PRIVATE_LISTING_TITLE",
        }],
    }
    return json.dumps({
        "state": {"loaderData": {
            "routes/v2.kr.search.buy-sell._index": model,
            **({"routes/duplicate.search": model}
               if duplicate_search_models else {}),
        }}
    }).encode("utf-8")


class PriceShapeTests(unittest.TestCase):
    def assert_filters(self, fields, expected, shape):
        blob = make_payload(fields)
        verdicts, observed_shape = inspect_dynamic_filtered_response(blob)
        self.assertEqual((verdicts["price_max"], observed_shape),
                         (expected, shape))
        self.assertEqual(verdicts["region"], "EXPECTED")
        self.assertEqual(verdicts["category"], "EXPECTED")
        self.assertEqual(verdicts["available"], "EXPECTED")
        self.assertNotIn("PRIVATE", json.dumps(verdicts))
        self.assertNotIn("PRIVATE", observed_shape)
        return blob

    def test_historical_response_price_range_max_proves_requested_cap(self):
        payload = self.assert_filters(
            {"priceRange": {"min": 0, "max": 50000}},
            "EXPECTED", "NESTED_PRICE_RANGE_MAX")
        # The old inspector's exact direct-field semantics remain unchanged:
        self.assertEqual(inspect_filtered_response(payload)["price_max"],
                         "MISSING")

    def test_direct_alias_still_accepted(self):
        for key in ("maxPrice", "max_price", "priceMax",
                    "priceTo", "price_to", "maximumPrice"):
            with self.subTest(alias=key):
                self.assert_filters({key: 50000}, "EXPECTED",
                                    "DIRECT_ALIAS")

    def test_nested_price_range_wrong_cap_is_explicit_other(self):
        for cap in (49999, 75000, 0, "40000", False, 50000.0):
            with self.subTest(value=repr(cap)):
                self.assert_filters(
                    {"priceRange": {"max": cap}}, "OTHER",
                    "NESTED_PRICE_RANGE_MAX")

    def test_missing_range_max_not_inferred_from_min(self):
        self.assert_filters({"priceRange": {"min": 0}},
                            "MISSING", "RANGE_WITHOUT_MAX")

    def test_malformed_range_is_ambiguous_not_success(self):
        for value in (None, "0__50000", 50000, ["0", 50000]):
            with self.subTest(value=repr(value)):
                self.assert_filters({"priceRange": value},
                                    "AMBIGUOUS", "MALFORMED_RANGE")

    def test_both_direct_and_nested_are_not_promoted(self):
        for direct, nested in ((50000, 50000), (50000, 90000),
                               (90000, 50000)):
            with self.subTest(direct=direct, nested=nested):
                self.assert_filters({
                    "maxPrice": direct,
                    "priceRange": {"max": nested},
                }, "AMBIGUOUS", "MULTIPLE_PRICE_SOURCES")

    def test_multiple_direct_aliases_are_ambiguous(self):
        self.assert_filters({"maxPrice": 50000, "priceMax": 50000},
                            "AMBIGUOUS", "MULTIPLE_PRICE_SOURCES")

    def test_only_price_string_is_untrusted_even_when_matches_url(self):
        for value in ("__50000", "50000", {"min": 0, "max": 50000}):
            with self.subTest(value=repr(value)):
                self.assert_filters({"price": value},
                                    "MISSING", "UNTRUSTED_PRICE_ONLY")

    def test_absent_or_unknown_price_field_is_missing(self):
        self.assert_filters({}, "MISSING", "ABSENT")
        self.assert_filters({"someUnknownPriceCap": 50000},
                            "MISSING", "ABSENT")

    def test_no_unique_model_never_reports_price_success(self):
        for payload in (b"not json", b"[]",
                        make_payload({"priceRange": {"max": 50000}},
                                     duplicate_search_models=True)):
            with self.subTest(payload=payload[:18]):
                verdicts, shape = inspect_dynamic_filtered_response(payload)
                self.assertEqual(verdicts["price_max"], "MISSING")
                self.assertEqual(shape, "NO_SEARCH_MODEL")

    def test_scalar_sources_only_no_article_projection(self):
        doc = make_payload({"priceRange": {"max": "50000"}})
        states, shape = inspect_dynamic_filtered_response(doc)
        self.assertEqual(states["price_max"], "EXPECTED")
        self.assertEqual(shape, "NESTED_PRICE_RANGE_MAX")
        for secret in ("PRIVATE", "href", "seller", "title", "priceRange"):
            self.assertNotIn(secret, json.dumps(states))
        self.assertFalse(any(key not in (
            "region", "category", "price_max", "available")
            for key in states))

    def test_helper_rejects_fake_price_proof(self):
        self.assertEqual(_price_value_and_shape(None),
                         ("MISSING", "NO_SEARCH_MODEL"))


class Request:
    method = "GET"
    resource_type = "fetch"
    url = ROUTE


class Response:
    status = 200
    headers = {"content-type": "application/json"}
    def __init__(self, req, payload):
        self.request = req
        self.url = req.url
        self._payload = payload
        self.reads = 0
    async def body(self):
        self.reads += 1
        return self._payload


class Page:
    def __init__(self, payload):
        self.url = "https://www.daangn.com/kr/search/buy-sell/?q=HDD"
        self.payload = payload
        self.hooks = {}
        self.buttons = []
        self.click_count = 0
    def on(self, name, fn):
        self.hooks.setdefault(name, []).append(fn)
    def remove_listener(self, name, fn):
        self.hooks[name].remove(fn)
    async def evaluate(self, script):
        return {
            "armed": True,
            "counts": {k: 1 for k in _EVENTS},
            "trusted": {k: 1 for k in _EVENTS},
        }
    async def wait_for_timeout(self, ms):
        return


class Button:
    def __init__(self, page):
        self.page = page
        self.responses = []
    async def is_enabled(self):
        return True
    async def evaluate(self, script):
        return True
    async def click(self, **kwargs):
        self.page.click_count += 1
        self.page.url = PAGE
        req = Request()
        self.page.hooks["request"][0](req)
        response = Response(req, self.page.payload)
        self.responses.append(response)
        self.page.hooks["response"][0](response)


class V2WatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_v2_single_body_read_yields_nested_provenance(self):
        w = PassiveFilteredRoute(passive_dynamic_loader=True)
        req = Request()
        rsp = Response(req, make_payload({"priceRange": {"max": 50000}}))
        w.on_request(req)
        w.on_response(rsp)
        await w.drain()
        self.assertEqual(rsp.reads, 1)
        self.assertEqual(w.dynamic_events[0]["price_max"], "EXPECTED")
        self.assertEqual(w.dynamic_price_shapes,
                         ["NESTED_PRICE_RANGE_MAX"])
        self.assertEqual(w.observed, 0)

    async def test_default_mode_still_does_not_read_body(self):
        w = PassiveFilteredRoute()
        req = Request()
        rsp = Response(req, make_payload({"priceRange": {"max": 50000}}))
        w.on_request(req)
        w.on_response(rsp)
        await w.drain()
        self.assertEqual(rsp.reads, 0)
        self.assertEqual(w.dynamic_price_shapes, [])

    async def test_v2_full_operator_still_blocks_even_if_range_expected(self):
        page = Page(make_payload({"priceRange": {"max": 50000}}))
        btn = Button(page)
        async def select(*args, **kwargs):
            return btn, _SELECTED
        async def no_ui_recheck(*args):
            raise AssertionError("URL region absent: no new UI action")
        with (
            patch("app_v5.precollection_filter_gate.v46.set_filter", select),
            patch("app_v5.precollection_filter_gate.v46.check_after",
                  no_ui_recheck),
        ):
            out = await verify_filter_before_collection(
                page, passive_dynamic_loader=True)
        self.assertEqual(page.click_count, 1)
        self.assertEqual(btn.responses[0].reads, 1)
        self.assertEqual(out["dynamic_loader_metadata_status"], "ONE_PARSED")
        self.assertEqual(out["dynamic_loader_price_shape"],
                         "NESTED_PRICE_RANGE_MAX")
        self.assertEqual(out["dynamic_loader_server_filters"], {
            "region": "EXPECTED", "category": "EXPECTED",
            "price_max": "EXPECTED", "available": "EXPECTED",
        })
        self.assertEqual(out["status"], "BLOCKED_FILTER_URL")
        self.assertFalse(out["strict_filter_evidence"])
        self.assertFalse(out["ui_selected_after_apply"])
        self.assertFalse(out["collection_started"])
        self.assertFalse(out["listing_fields_read_or_exported"])
        self.assertFalse(out["database_written"])
        self.assertFalse(out["authorizes_listings"])
        self.assertEqual(page.hooks["response"], [])
        self.assertNotIn("PRIVATE", json.dumps(out))

    async def test_legacy_v2_direct_price_diagnostic_unchanged(self):
        page = Page(make_payload({"maxPrice": 50000}))
        btn = Button(page)
        async def select(*args, **kwargs):
            return btn, _SELECTED
        with patch("app_v5.precollection_filter_gate.v46.set_filter",
                   select):
            out = await verify_filter_before_collection(
                page, passive_dynamic_loader=True)
        self.assertEqual(out["dynamic_loader_server_filters"]["price_max"],
                         "EXPECTED")
        self.assertEqual(out["dynamic_loader_price_shape"], "DIRECT_ALIAS")
        self.assertFalse(out["authorizes_listings"])

    async def test_multiple_requests_do_not_select_price_shape_success(self):
        w = PassiveFilteredRoute(passive_dynamic_loader=True)
        for _ in range(2):
            req = Request()
            w.on_request(req)
            w.on_response(Response(
                req, make_payload({"priceRange": {"max": 50000}})))
        await w.drain()
        self.assertEqual(w.diagnostics["search_requests"], 2)
        self.assertEqual(w.observed, 0)


class SanitizerTests(unittest.TestCase):
    def test_price_shape_is_fixed_enum_and_idempotent(self):
        for shape in (
            "DIRECT_ALIAS", "NESTED_PRICE_RANGE_MAX",
            "RANGE_WITHOUT_MAX", "MALFORMED_RANGE",
            "MULTIPLE_PRICE_SOURCES", "UNTRUSTED_PRICE_ONLY",
            "ABSENT", "NO_SEARCH_MODEL", "UNOBSERVABLE",
        ):
            row = sanitize_precollection({
                "dynamic_loader_price_shape": shape,
                "authorizes_listings": True,
                "raw_body": "PRIVATE_SELLER",
            })
            self.assertEqual(row["dynamic_loader_price_shape"], shape)
            self.assertEqual(sanitize_precollection(row), row)
            self.assertFalse(row["authorizes_listings"])
            self.assertNotIn("PRIVATE", json.dumps(row))

    def test_unknown_shape_and_injected_secrets_never_exported(self):
        row = sanitize_precollection({
            "dynamic_loader_price_shape": "PRIVATE_ROUTE_ID",
            "query": "PRIVATE_URL",
            "database_written": True,
        })
        self.assertEqual(row["dynamic_loader_price_shape"], "UNOBSERVABLE")
        self.assertNotIn("PRIVATE", json.dumps(row))
        self.assertFalse(row["database_written"])


if __name__ == "__main__":
    unittest.main()
