# -*- coding: utf-8 -*-
"""Offline-only comparison of browser Apply request and page URL verdicts."""
from __future__ import annotations

import json
import unittest

from app_v5.precollection_filter_gate import (
    PassiveFilteredRoute, _unique_query, _exact_except_missing_region,
    sanitize_apply_request_diagnostics, sanitize_precollection,
)

ROOT="https://www.daangn.com/kr/search/buy-sell/"
FILTER_PAGE=ROOT+"?q=HDD&category_id=1&price=__50000&only_on_sale=true"
FULL=ROOT+(
    "?q=HDD&in=%EB%B6%88%EB%8B%B9%EB%8F%99-2292"
    "&category_id=1&price=__50000&only_on_sale=true"
)
FIELDS=("keyword","region","category","price_max","available")


class Request:
    method="GET"
    resource_type="fetch"
    def __init__(self,url):self.url=url


class Response:
    status=200
    headers={"content-type":"application/json"}
    def __init__(self,req,*,url=None,status=200):
        self.request=req
        self.url=url if url is not None else req.url
        self.status=status
        self.calls=0
    async def body(self):
        self.calls+=1
        return b'{"PRIVATE_LISTING_TITLE":"SECRET"}'


class RequestShapeTests(unittest.IsolatedAsyncioTestCase):
    async def report(self,request_url,page_url=FILTER_PAGE,response_url=None):
        watcher=PassiveFilteredRoute()
        req=Request(request_url)
        resp=Response(req,url=response_url)
        watcher.on_request(req)
        watcher.on_response(resp)
        await watcher.drain()
        return watcher,resp,watcher.summarize_request_verdicts(page_url)

    async def test_single_request_missing_region_but_extra_key_is_distinguished(self):
        url=FILTER_PAGE+"&sort=latest&private=MY_SECRET"
        watcher,resp,result=await self.report(url)
        self.assertEqual(result["observation"],"ONE_OBSERVED")
        self.assertEqual(result["request_url"]["fields"]["region"],"MISSING")
        self.assertEqual(result["request_url"]["unexpected_keys"],2)
        self.assertEqual(result["outcome"],"HTTP_200")
        self.assertEqual(result["method"],"GET")
        self.assertEqual(result["transport"],"FETCH_OR_XHR")
        self.assertEqual(result["field_verdict_relationship"]["region"],"SAME")
        self.assertEqual(watcher.regionless_observed,0)
        self.assertEqual(watcher.observed,0)
        self.assertEqual(resp.calls,0)
        self.assertNotIn("SECRET",json.dumps(result))
        self.assertNotIn("sort",json.dumps(result))
        self.assertEqual(sanitize_apply_request_diagnostics(result),result)

    async def test_network_request_region_expected_but_price_missing_differs_from_page(self):
        url=FULL.replace("&price=__50000","")
        watcher,resp,result=await self.report(url)
        self.assertEqual(result["request_url"]["fields"]["region"],"EXPECTED")
        self.assertEqual(result["request_url"]["fields"]["price_max"],"MISSING")
        self.assertEqual(result["field_verdict_relationship"]["region"],"DIFFERENT")
        self.assertEqual(result["field_verdict_relationship"]["price_max"],"DIFFERENT")
        self.assertEqual(result["request_url"]["fields"]["category"],"EXPECTED")
        self.assertEqual(watcher.regionless_observed,0)
        self.assertEqual(watcher.observed,0)
        self.assertEqual(resp.calls,0)

    async def test_single_request_with_wrong_region_does_not_count_as_regionless(self):
        url=FILTER_PAGE+"&in=other-private-neighborhood"
        watcher,resp,result=await self.report(url)
        self.assertEqual(result["request_url"]["fields"]["region"],"OTHER")
        self.assertEqual(result["field_verdict_relationship"]["region"],"DIFFERENT")
        self.assertEqual(resp.calls,0)
        self.assertEqual(watcher.regionless_observed,0)

    async def test_duplicate_price_can_explain_regionless_count_zero(self):
        url=FILTER_PAGE+"&price=__50000"
        watcher,resp,result=await self.report(url)
        self.assertEqual(result["request_url"]["fields"]["price_max"],"DUPLICATE")
        self.assertEqual(result["field_verdict_relationship"]["price_max"],"DIFFERENT")
        self.assertEqual(watcher.regionless_observed,0)
        self.assertEqual(resp.calls,0)

    async def test_exact_four_parameter_regionless_request_is_only_diagnostic(self):
        watcher,resp,result=await self.report(FILTER_PAGE)
        self.assertTrue(_exact_except_missing_region(FILTER_PAGE))
        self.assertFalse(_unique_query(FILTER_PAGE))
        self.assertEqual(watcher.regionless_observed,1)
        self.assertEqual(watcher.observed,0)
        self.assertEqual(result["request_url"]["fields"]["region"],"MISSING")
        self.assertEqual(result["request_url"]["unexpected_keys"],0)
        self.assertEqual(result["outcome"],"HTTP_200")
        self.assertFalse(result["authorizes_listings"])

    async def test_mismatched_redirect_response_not_read_even_if_request_exact(self):
        watcher,resp,result=await self.report(
            FILTER_PAGE,response_url="https://private.invalid/SECRET")
        self.assertEqual(watcher.regionless_observed,1)
        self.assertEqual(resp.calls,0)
        self.assertEqual(result["response_url"]["shape"],"OTHER_PATH_OR_ORIGIN")
        self.assertEqual(result["outcome"],"HTTP_200")
        self.assertNotIn("private.invalid",json.dumps(result))
        self.assertFalse(result["authorizes_listings"])

    async def test_request_and_response_url_classes_are_independent(self):
        url=FILTER_PAGE+"&sort=recent"
        watcher,resp,result=await self.report(url,response_url=FILTER_PAGE)
        self.assertEqual(result["request_url"]["unexpected_keys"],1)
        self.assertEqual(result["response_url"]["unexpected_keys"],0)
        self.assertEqual(watcher.regionless_observed,0)
        self.assertEqual(resp.calls,0)

    async def test_multiple_browser_requests_never_select_best_looking_one(self):
        watcher=PassiveFilteredRoute()
        for url in (FULL,FILTER_PAGE+"&sort=latest"):
            req=Request(url)
            watcher.on_request(req)
            watcher.on_response(Response(req))
        await watcher.drain()
        out=watcher.summarize_request_verdicts(FILTER_PAGE)
        self.assertEqual(out["observation"],"MULTIPLE_OBSERVED")
        self.assertEqual(out["request_url"]["shape"],"UNOBSERVABLE")
        self.assertFalse(out["authorizes_listings"])

    async def test_zero_request_is_distinct_from_missing_observer(self):
        watcher=PassiveFilteredRoute()
        out=watcher.summarize_request_verdicts(FILTER_PAGE)
        self.assertEqual(out["observation"],"NOT_OBSERVED")
        self.assertEqual(out["request_url"]["shape"],"UNOBSERVABLE")
        self.assertFalse(out["authorizes_listings"])

    async def test_restricted_response_and_failed_request_are_distinguished(self):
        watcher=PassiveFilteredRoute()
        req=Request(FILTER_PAGE+"&unknown=1")
        watcher.on_request(req)
        watcher.on_response(Response(req,status=403))
        one=watcher.summarize_request_verdicts(FILTER_PAGE)
        self.assertEqual(one["outcome"],"ACCESS_RESTRICTED")
        self.assertTrue(watcher.restricted)
        other=PassiveFilteredRoute()
        req2=Request(FILTER_PAGE+"&unknown=2")
        other.on_request(req2)
        other.on_requestfailed(req2)
        self.assertEqual(other.summarize_request_verdicts(FILTER_PAGE)[
            "outcome"],"REQUEST_FAILED")


class SanitizerTests(unittest.TestCase):
    def test_strict_sanitize_precollection_has_only_bounded_enums(self):
        malicious={
            "apply_search_request_diagnostics":{
                "observation":"ONE_OBSERVED",
                "request_url":{
                    "shape":"FIRST_PARTY_SEARCH",
                    "unexpected_keys":2,
                    "fields":{"price_max":"OTHER","region":"MISSING",
                              "untrusted":"MY_SECRET"},
                    "raw_url":"https://private.invalid/PRIVATE_URL",
                },
                "response_url":{"shape":"FIRST_PARTY_SEARCH"},
                "transport":"FETCH_OR_XHR",
                "method":"GET",
                "outcome":"HTTP_200",
                "field_verdict_relationship":{"region":"DIFFERENT",
                                             "raw":"MY_PRIVATE_ID"},
                "raw_cookie":"PRIVATE_COOKIE",
            },
            "status":"BLOCKED_FILTER_URL",
            "authorizes_listings":True,
            "listing_data_exported":True,
        }
        safe=sanitize_precollection(malicious)
        self.assertEqual(sanitize_precollection(safe),safe)
        self.assertEqual(safe["apply_search_request_diagnostics"][
            "request_url"]["fields"]["price_max"],"OTHER")
        self.assertEqual(safe["apply_search_request_diagnostics"][
            "field_verdict_relationship"]["region"],"DIFFERENT")
        self.assertNotIn("PRIVATE",json.dumps(safe))
        self.assertNotIn("MY_SECRET",json.dumps(safe))
        self.assertFalse(safe["authorizes_listings"])
        self.assertFalse(safe["collection_started"])
        self.assertFalse(safe["database_written"])

    def test_malformed_inputs_default_to_unobservable(self):
        data=sanitize_apply_request_diagnostics({
            "observation":"SECRET", "transport":"UNKNOWN",
            "outcome":"COOKIE", "request_url":"SECRET",
            "field_verdict_relationship":{"region":True},
        })
        self.assertEqual(data["observation"],"UNOBSERVABLE")
        self.assertEqual(data["transport"],"UNOBSERVABLE")
        self.assertEqual(data["outcome"],"NOT_OBSERVED")
        self.assertEqual(data["field_verdict_relationship"]["region"],
                         "UNOBSERVABLE")
        self.assertEqual(sanitize_apply_request_diagnostics(data),data)


if __name__=="__main__":
    unittest.main()
