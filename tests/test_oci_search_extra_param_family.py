# -*- coding: utf-8 -*-
"""Offline-only, privacy-bounded additional URL-key family classification."""
from __future__ import annotations

import json
import unittest
from urllib.parse import urlencode

import daangn_v4_1_core as core
from app_v5.precollection_filter_gate import (
    PassiveFilteredRoute, classify_extra_query_family,
    sanitize_apply_request_diagnostics, sanitize_precollection,
)

PAGE=("https://www.daangn.com/kr/search/buy-sell/"
      "?q=HDD&category_id=1&price=__50000&only_on_sale=true")


class TestFiniteExtraKeyFamily(unittest.TestCase):
    def test_legacy_remix_route_is_exact_only(self):
        route=PAGE+"&"+urlencode({"_data":core.ROUTE_ID})
        self.assertEqual(classify_extra_query_family(route),"EXACT_REMIX_DATA")
        self.assertEqual(classify_extra_query_family(
            PAGE+"&"+urlencode({"_data":"routes/other.route"})),
            "OTHER_REMIX_DATA_ID")

    def test_only_explicit_known_framework_key_names_classified(self):
        self.assertEqual(classify_extra_query_family(PAGE+"&_routes=anything"),
                         "ROUTES_KEY")
        self.assertEqual(classify_extra_query_family(PAGE+"&index="),
                         "INDEX_KEY")
        self.assertEqual(classify_extra_query_family(PAGE+"&build_id=PRIVATE"),
                         "OTHER_SINGLE_KEY")
        self.assertEqual(classify_extra_query_family(PAGE),"NONE")

    def test_unknown_key_values_and_names_are_not_emitted(self):
        a=classify_extra_query_family(
            PAGE+"&private_mobile_number=01012345678")
        b=classify_extra_query_family(
            PAGE+"&private_session_token=MY_SECRET")
        self.assertEqual(a,"OTHER_SINGLE_KEY")
        self.assertEqual(b,"OTHER_SINGLE_KEY")
        self.assertNotIn("PRIVATE",json.dumps([a,b]))
        self.assertNotIn("010",json.dumps([a,b]))

    def test_duplicate_values_and_multiple_keys_are_distinct(self):
        self.assertEqual(classify_extra_query_family(
            PAGE+"&_data=a&_data=b"),"DUPLICATE_EXTRA_VALUE")
        self.assertEqual(classify_extra_query_family(
            PAGE+"&_data=a&index="),"MULTIPLE_EXTRA_KEYS")

    def test_mismatched_fixed_fields_or_region_in_are_rejected(self):
        bad=(
            PAGE.replace("q=HDD","q=SSD")+"&_data=something",
            PAGE.replace("price=__50000","price=__100000")+"&_data=x",
            PAGE.replace("only_on_sale=true","only_on_sale=false")+"&index",
            PAGE+"&in=%EB%B6%88%EB%8B%B9%EB%8F%99-2292&_data=x",
            PAGE+"&q=HDD&_data=x",
            PAGE.replace("category_id=1","category_id=2")+"&_data=x",
            PAGE.replace("www.daangn.com","private.invalid")+"&_data=x",
        )
        for url in bad:
            with self.subTest(url=url):
                self.assertEqual(classify_extra_query_family(url),
                                 "FILTER_QUERY_MISMATCH")

    def test_invalid_input_is_never_exposed(self):
        for input_data in (None,{},42,"X"*5000):
            self.assertEqual(classify_extra_query_family(input_data),
                             "UNOBSERVABLE")


class Request:
    method="GET"
    resource_type="fetch"
    def __init__(self,url):self.url=url


class Response:
    status=200
    headers={"content-type":"application/json"}
    def __init__(self,request,url=None):
        self.request=request
        self.url=url if url is not None else request.url
        self.calls=0
    async def body(self):
        self.calls+=1
        raise AssertionError("No unknown-key response body may be read")


class TestNoBodyReads(unittest.IsolatedAsyncioTestCase):
    async def test_extra_unrecognized_key_is_diagnostic_only(self):
        req=Request(PAGE+"&sensitive=DO_NOT_EXPORT")
        response=Response(req)
        watcher=PassiveFilteredRoute()
        watcher.on_request(req)
        watcher.on_response(response)
        await watcher.drain()
        out=watcher.summarize_request_verdicts(PAGE)
        self.assertEqual(out["observation"],"ONE_OBSERVED")
        self.assertEqual(out["request_extra_query_family"],"OTHER_SINGLE_KEY")
        self.assertEqual(out["response_extra_query_family"],"OTHER_SINGLE_KEY")
        self.assertEqual(out["request_route_selector"],"OTHER_EXTRA")
        self.assertEqual(out["request_url"]["fields"]["region"],"MISSING")
        self.assertEqual(out["request_url"]["unexpected_keys"],1)
        self.assertEqual(out["outcome"],"HTTP_200")
        self.assertFalse(out["authorizes_listings"])
        self.assertEqual(watcher.remix_regionless_observed,0)
        self.assertEqual(watcher.regionless_observed,0)
        self.assertEqual(watcher.observed,0)
        self.assertEqual(response.calls,0)
        self.assertNotIn("DO_NOT_EXPORT",json.dumps(out))

    async def test_routes_key_may_be_named_but_never_accepted(self):
        req=Request(PAGE+"&_routes=private_route_id")
        resp=Response(req)
        watcher=PassiveFilteredRoute()
        watcher.on_request(req)
        watcher.on_response(resp)
        await watcher.drain()
        out=watcher.summarize_request_verdicts(PAGE)
        self.assertEqual(out["request_extra_query_family"],"ROUTES_KEY")
        self.assertEqual(watcher.remix_regionless_observed,0)
        self.assertEqual(resp.calls,0)
        self.assertFalse(out["authorizes_listings"])

    async def test_request_and_response_family_can_differ_without_body_read(self):
        req=Request(PAGE+"&index")
        resp=Response(req,url=PAGE+"&abc=PRIVATE")
        watcher=PassiveFilteredRoute()
        watcher.on_request(req)
        watcher.on_response(resp)
        await watcher.drain()
        out=watcher.summarize_request_verdicts(PAGE)
        self.assertEqual(out["request_extra_query_family"],"INDEX_KEY")
        self.assertEqual(out["response_extra_query_family"],"OTHER_SINGLE_KEY")
        self.assertEqual(resp.calls,0)
        self.assertFalse(out["authorizes_listings"])

    async def test_multiple_requests_do_not_select_preferred_key(self):
        watcher=PassiveFilteredRoute()
        for key in ("index", "private"):
            req=Request(PAGE+"&"+key)
            watcher.on_request(req)
            watcher.on_response(Response(req))
        out=watcher.summarize_request_verdicts(PAGE)
        self.assertEqual(out["observation"],"MULTIPLE_OBSERVED")
        self.assertEqual(out["request_extra_query_family"],"UNOBSERVABLE")


class TestSanitization(unittest.TestCase):
    def test_precollection_drops_private_strings_and_injected_approval(self):
        source={
            "apply_search_request_diagnostics":{
                "observation":"ONE_OBSERVED",
                "request_extra_query_family":"OTHER_SINGLE_KEY",
                "response_extra_query_family":"PRIVATE_SESSION_ID",
                "raw_query":"PRIVATE_QUERY",
                "seller":"PRIVATE_SELLER",
                "authorizes_listings":True,
            },
            "authorizes_listings":True,"collection_started":True,
            "raw_body":"PRIVATE_LISTING",
        }
        safe=sanitize_precollection(source)
        self.assertEqual(sanitize_precollection(safe),safe)
        self.assertEqual(safe["apply_search_request_diagnostics"][
            "request_extra_query_family"],"OTHER_SINGLE_KEY")
        self.assertEqual(safe["apply_search_request_diagnostics"][
            "response_extra_query_family"],"UNOBSERVABLE")
        self.assertFalse(safe["authorizes_listings"])
        self.assertFalse(safe["collection_started"])
        self.assertFalse(safe["database_written"])
        self.assertNotIn("PRIVATE",json.dumps(safe))

    def test_sanitizer_is_idempotent_on_known_extra_class(self):
        for value in ("ROUTES_KEY","INDEX_KEY","OTHER_REMIX_DATA_ID",
                      "EXACT_REMIX_DATA","OTHER_SINGLE_KEY",
                      "DUPLICATE_EXTRA_VALUE","MULTIPLE_EXTRA_KEYS",
                      "FILTER_QUERY_MISMATCH","NONE","UNOBSERVABLE"):
            safe=sanitize_apply_request_diagnostics({
                "request_extra_query_family":value})
            self.assertEqual(safe["request_extra_query_family"],value)
            self.assertEqual(sanitize_apply_request_diagnostics(safe),safe)


if __name__ == "__main__":
    unittest.main()
