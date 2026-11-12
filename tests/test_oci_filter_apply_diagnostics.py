# -*- coding: utf-8 -*-
"""Offline-only URL/transport diagnostics after one approved visible Filter Apply."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from app_v5.precollection_filter_gate import (
    _unique_query, classify_filter_url, sanitize_filter_url_diagnostic,
    sanitize_filter_transport_diagnostic, sanitize_precollection,
    PassiveFilteredRoute, verify_filter_before_collection,
)
from ops.oci.precollection import final_report
from tests.test_oci_precollection_gate import TARGET_URL, BEFORE, Request, Response


class UrlDifferenceTests(unittest.TestCase):
    def test_exact_url_shows_all_expected(self):
        result=classify_filter_url(TARGET_URL)
        self.assertEqual(result["shape"],"FIRST_PARTY_SEARCH")
        self.assertEqual(result["unexpected_keys"],0)
        self.assertTrue(all(v=="EXPECTED" for v in result["fields"].values()))
        self.assertTrue(_unique_query(TARGET_URL))
        self.assertEqual(sanitize_filter_url_diagnostic(result),result)

    def test_missing_each_field_and_wrong_value_do_not_leak(self):
        for query_part,expected_key in (
            ("q=HDD&","keyword"),
            ("in=%EB%B6%88%EB%8B%B9%EB%8F%99-2292&","region"),
            ("category_id=1&","category"),
            ("price=__50000&","price_max"),
            ("&only_on_sale=true","available"),
        ):
            url=TARGET_URL.replace(query_part,"")
            state=classify_filter_url(url)
            self.assertEqual(state["fields"][expected_key],"MISSING")
            self.assertFalse(_unique_query(url))
        changed=TARGET_URL.replace("price=__50000","price=__75000")
        self.assertEqual(classify_filter_url(changed)["fields"]["price_max"],"OTHER")
        self.assertFalse(_unique_query(changed))
        self.assertNotIn("75000",json.dumps(classify_filter_url(changed)))

    def test_duplicate_and_unexpected_param_only_report_counts(self):
        src=TARGET_URL+"&price=__50000&session_token=PRIVATE_COOKIE&sort=latest"
        safe=classify_filter_url(src)
        self.assertEqual(safe["fields"]["price_max"],"DUPLICATE")
        self.assertEqual(safe["unexpected_keys"],2)
        self.assertFalse(_unique_query(src))
        self.assertNotIn("PRIVATE",json.dumps(safe))
        self.assertNotIn("sort",json.dumps(safe))
        self.assertEqual(sanitize_filter_url_diagnostic(safe),safe)

    def test_wrong_origin_and_unreadable_are_not_interpreted(self):
        for url in ("https://example.com/kr/search/buy-sell/?q=HDD",
                    "https://www.daangn.com/kr/search/other?secret=PRIVATE",
                    "http://www.daangn.com/kr/search/buy-sell/",
                    "https://www.daangn.com:443/kr/search/buy-sell/"):
            out=classify_filter_url(url)
            self.assertEqual(out["shape"],"OTHER_PATH_OR_ORIGIN")
            self.assertEqual(out["unexpected_keys"],-1)
            self.assertTrue(all(v=="UNOBSERVABLE" for v in out["fields"].values()))
        out=classify_filter_url("a"*4097)
        self.assertEqual(out["shape"],"UNOBSERVABLE")

    def test_malformed_output_sanitizer_does_not_leak(self):
        safe=sanitize_filter_url_diagnostic({
            "shape":"PRIVATE_COOKIE",
            "fields":{"keyword":"PRIVATE_LOCATION","price_max":"OTHER",
                      "raw":"PRIVATE_RAW"},
            "unexpected_keys":True,"raw_url":"https://secret.invalid",
        })
        self.assertEqual(safe["shape"],"UNOBSERVABLE")
        self.assertEqual(safe["fields"]["price_max"],"OTHER")
        self.assertEqual(safe["fields"]["keyword"],"UNOBSERVABLE")
        self.assertEqual(safe["unexpected_keys"],-1)
        self.assertNotIn("PRIVATE",json.dumps(safe))
        self.assertEqual(sanitize_filter_url_diagnostic(safe),safe)


class Req:
    method="GET"
    resource_type="fetch"
    def __init__(self,url):
        self.url=url


class Res:
    def __init__(self,req,status=200):
        self.request=req
        self.url=req.url
        self.status=status
        self.headers={"content-type":"application/json"}
        self.body_calls=0
    async def body(self):
        self.body_calls+=1
        raise AssertionError("Must never read mismatched Route body")


class BroadTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_mismatched_filter_search_request_observed_without_body(self):
        watcher=PassiveFilteredRoute()
        req=Req(TARGET_URL.replace("price=__50000","price=__45000"))
        res=Res(req)
        watcher.on_request(req)
        watcher.on_response(res)
        await watcher.drain()
        self.assertEqual(res.body_calls,0)
        self.assertEqual(watcher.observed,0)
        self.assertEqual(watcher.events,[])
        diag=sanitize_filter_transport_diagnostic(watcher.diagnostics)
        self.assertEqual(diag["search_requests"],1)
        self.assertEqual(diag["search_different_query_requests"],1)
        self.assertEqual(diag["search_responses"],1)
        self.assertEqual(diag["search_response_200"],1)
        self.assertEqual(diag["search_exact_query_requests"],0)

    async def test_document_navigation_counted_without_becoming_valid_route(self):
        watcher=PassiveFilteredRoute()
        req=Req(TARGET_URL)
        req.resource_type="document"
        res=Res(req)
        watcher.on_request(req)
        watcher.on_response(res)
        await watcher.drain()
        diag=sanitize_filter_transport_diagnostic(watcher.diagnostics)
        self.assertEqual(diag["search_document_requests"],1)
        self.assertEqual(diag["search_exact_query_requests"],1)
        self.assertEqual(diag["search_response_200"],1)
        self.assertEqual(watcher.observed,0)
        self.assertEqual(res.body_calls,0)

    async def test_http_403_on_wrong_query_still_stops(self):
        watcher=PassiveFilteredRoute()
        req=Req(TARGET_URL.replace("price=__50000","price=__50001"))
        watcher.on_request(req)
        watcher.on_response(Res(req,403))
        self.assertTrue(watcher.restricted)
        self.assertEqual(watcher.diagnostics["search_response_restricted"],1)
        self.assertEqual(watcher.observed,0)

    async def test_failed_request_reported_without_body(self):
        watcher=PassiveFilteredRoute()
        req=Req(TARGET_URL.replace("category_id=1","category_id=7"))
        watcher.on_request(req)
        watcher.on_requestfailed(req)
        self.assertEqual(watcher.diagnostics["search_request_failures"],1)
        self.assertEqual(watcher.diagnostics["search_responses"],0)

    async def test_non_search_urls_not_observed_even_if_content_sensitive(self):
        watcher=PassiveFilteredRoute()
        req=Req("https://www.daangn.com/kr/buy-sell/PRIVATE_LISTING")
        watcher.on_request(req)
        watcher.on_response(Res(req))
        self.assertEqual(watcher.diagnostics["search_requests"],0)

    async def test_counts_and_unknowns_strictly_sanitized(self):
        raw={"search_requests":True,"search_response_200":2,
             "raw_url":"https://private.invalid/SECRET",
             "search_document_requests":999}
        out=sanitize_filter_transport_diagnostic(raw)
        self.assertEqual(out["search_requests"],-1)
        self.assertEqual(out["search_response_200"],2)
        self.assertEqual(out["search_document_requests"],-1)
        self.assertEqual(sanitize_filter_transport_diagnostic(out),out)
        self.assertNotIn("SECRET",json.dumps(out))


class BlockingOutputTests(unittest.IsolatedAsyncioTestCase):
    async def test_url_diff_after_one_apply_is_reported_without_ui_reopen(self):
        class Page:
            def __init__(self):
                self.url="https://www.daangn.com/kr/search/buy-sell/?q=HDD"
                self.hooks={}
            def on(self,key,fn):
                self.hooks.setdefault(key,[]).append(fn)
            def remove_listener(self,key,fn):
                self.hooks[key].remove(fn)
            async def wait_for_timeout(self,ms):
                return None
        page=Page()
        class Button:
            async def is_enabled(self):
                return True
            async def click(self,**kw):
                page.url=TARGET_URL.replace("price=__50000","price=__45000")
                request=Req(page.url)
                for fn in page.hooks.get("request",[]):
                    fn(request)
                response=Res(request)
                for fn in page.hooks.get("response",[]):
                    fn(response)
        async def set_filter(*args):
            return Button(),BEFORE
        async def must_not_recheck(*args):
            raise AssertionError("Should not reopen Filter on URL block")
        with patch("app_v5.precollection_filter_gate.v46.set_filter",set_filter),\
             patch("app_v5.precollection_filter_gate.v46.check_after",must_not_recheck):
            result=await verify_filter_before_collection(page)
        self.assertEqual(result["status"],"BLOCKED_FILTER_URL")
        self.assertTrue(result["filter_apply_returned"])
        self.assertFalse(result["filtered_url_matches"])
        self.assertEqual(result["ui_after_apply_recheck_state"],"NOT_RUN")
        self.assertEqual(result["filtered_url_diagnostics"]["fields"]["price_max"],"OTHER")
        self.assertEqual(result["filter_transport_diagnostics"]["search_response_200"],1)
        self.assertEqual(result["filtered_route_count"],0)
        self.assertFalse(result["authorizes_listings"])
        self.assertEqual(page.hooks["request"],[])
        self.assertEqual(page.hooks["response"],[])
        self.assertEqual(page.hooks["requestfailed"],[])

    async def test_operator_resanitizes_nested_url_transport_metadata(self):
        malicious={
            "status":"BLOCKED_FILTER_URL",
            "filtered_url_diagnostics":{
                "shape":"FIRST_PARTY_SEARCH",
                "unexpected_keys":1,
                "fields":{"price_max":"OTHER"},
                "raw_url":"https://private.invalid/SECRET"},
            "filter_transport_diagnostics":{
                "search_responses":1,
                "raw_response":"PRIVATE_LISTING"},
            "raw_prices":[300],
            "authorizes_listings":True,
        }
        safe=sanitize_precollection(malicious)
        self.assertEqual(sanitize_precollection(safe),safe)
        self.assertNotIn("PRIVATE",json.dumps(safe))
        self.assertNotIn("private.invalid",json.dumps(safe))
        self.assertFalse(safe["collection_started"])
        self.assertFalse(safe["authorizes_listings"])


if __name__=="__main__":
    unittest.main()
