# -*- coding: utf-8 -*-
"""Known first-party Remix loader probe, offline-only, non-admitting."""
from __future__ import annotations

import json
import unittest
from urllib.parse import urlencode
from unittest.mock import patch

import daangn_v4_1_core as core
from app_v5.precollection_filter_gate import (
    PassiveFilteredRoute, _exact_known_remix_regionless_loader,
    classify_remix_loader_selector, sanitize_apply_request_diagnostics,
    sanitize_precollection, verify_filter_before_collection,
)

PAGE=(
    "https://www.daangn.com/kr/search/buy-sell/"
    "?q=HDD&category_id=1&price=__50000&only_on_sale=true"
)
LOADER=PAGE+"&"+urlencode({"_data":core.ROUTE_ID})
FULL=PAGE+"&in=%EB%B6%88%EB%8B%B9%EB%8F%99-2292"
FIELDS=("region","category","price_max","available")


def payload(*,region=2292,category=1,cap=50000,available=True,
            price_present=True):
    filters={"regionId":region,"categoryId":category,"onlyOnSale":available}
    if price_present: filters["maxPrice"]=cap
    return json.dumps({
        "route":{
            "searchRegion":{"id":region, "name":"PRIVATE_REGION_LABEL"},
            "currentFilters":filters,
            "buySellArticles":[{"title":"PRIVATE_TITLE",
                                "url":"https://private.invalid/SECRET",
                                "price":99999}],
        }
    }).encode()


class Request:
    method="GET"
    resource_type="fetch"
    def __init__(self,url=LOADER):self.url=url


class Response:
    status=200
    headers={"content-type":"application/json"}
    def __init__(self,request,*,status=200,url=None,body=None,content_type="application/json"):
        self.request=request
        self.status=status
        self.url=request.url if url is None else url
        self.headers={"content-type":content_type}
        self.bytes=payload() if body is None else body
        self.body_reads=0
    async def body(self):
        self.body_reads+=1
        return self.bytes


class KnownSelectorTests(unittest.TestCase):
    def test_known_remix_selector_is_proven_from_repo_route_id(self):
        self.assertTrue(_exact_known_remix_regionless_loader(LOADER))
        self.assertEqual(
            classify_remix_loader_selector(LOADER),
            "EXPECTED_SEARCH_LOADER")
        self.assertEqual(
            classify_remix_loader_selector(PAGE),"NONE")

    def test_reject_unexpected_extra_or_wrong_data_value(self):
        bad=(
            LOADER+"&private=SECRET",
            LOADER+"&_data="+core.ROUTE_ID,
            PAGE+"&"+urlencode({"_data":"other.route"}),
            PAGE+"&_data=secret_private",
            LOADER.replace("q=HDD","q=SSD"),
            LOADER.replace("category_id=1","category_id=2"),
            LOADER.replace("price=__50000","price=__100000"),
            LOADER.replace("only_on_sale=true","only_on_sale=false"),
            LOADER+"&in=%EB%B6%88%EB%8B%B9%EB%8F%99-2292",
            LOADER.replace("www.daangn.com","private.invalid"),
            PAGE+"&in=%EB%B6%88%EB%8B%B9%EB%8F%99-2292",
        )
        for url in bad:
            with self.subTest(url=url):
                self.assertFalse(_exact_known_remix_regionless_loader(url))

    def test_sanitizer_only_fixed_category_no_raw_value(self):
        raw={
            "request_route_selector":"EXPECTED_SEARCH_LOADER",
            "response_route_selector":"PRIVATE_COOKIE",
            "observation":"ONE_OBSERVED",
            "raw_url":"https://private.invalid/SECRET",
        }
        safe=sanitize_apply_request_diagnostics(raw)
        self.assertEqual(safe["request_route_selector"],
                         "EXPECTED_SEARCH_LOADER")
        self.assertEqual(safe["response_route_selector"],"UNOBSERVABLE")
        self.assertEqual(sanitize_apply_request_diagnostics(safe),safe)
        self.assertNotIn("PRIVATE",json.dumps(safe))


class BrowserRouteTests(unittest.IsolatedAsyncioTestCase):
    async def witness(self,*,url=LOADER,response_url=None,status=200,
                      data=None,ctype="application/json"):
        watcher=PassiveFilteredRoute()
        req=Request(url)
        res=Response(req,status=status,url=response_url,body=data,
                     content_type=ctype)
        watcher.on_request(req)
        watcher.on_response(res)
        await watcher.drain()
        return watcher,res

    async def test_known_loader_reads_metadata_not_listings(self):
        watcher,res=await self.witness()
        self.assertEqual(res.body_reads,1)
        self.assertEqual(watcher.remix_regionless_observed,1)
        self.assertEqual(watcher.observed,0)
        self.assertEqual(watcher.regionless_observed,0)
        self.assertEqual(watcher.remix_regionless_events[0],
                         {key:"EXPECTED" for key in FIELDS})
        info=watcher.summarize_request_verdicts(PAGE)
        self.assertEqual(info["request_route_selector"],
                         "EXPECTED_SEARCH_LOADER")
        self.assertEqual(info["response_route_selector"],
                         "EXPECTED_SEARCH_LOADER")
        self.assertEqual(info["request_url"]["unexpected_keys"],1)
        self.assertEqual(info["request_url"]["fields"]["region"],"MISSING")
        self.assertNotIn("PRIVATE",json.dumps(info))

    async def test_server_region_mismatch_detected_independently(self):
        watcher,res=await self.witness(data=payload(region=2333))
        fields=watcher.remix_regionless_events[0]
        self.assertEqual(fields["region"],"OTHER")
        self.assertEqual(res.body_reads,1)

    async def test_absent_price_field_never_inferred_from_url(self):
        watcher,_=await self.witness(data=payload(price_present=False))
        self.assertEqual(watcher.remix_regionless_events[0]["price_max"],
                         "MISSING")

    async def test_known_request_redirect_to_different_url_never_reads_body(self):
        watcher,res=await self.witness(response_url=PAGE)
        self.assertEqual(res.body_reads,0)
        self.assertEqual(watcher.remix_regionless_events,[])
        self.assertEqual(watcher.remix_regionless_observed,1)
        self.assertEqual(watcher.summarize_request_verdicts(PAGE)[
            "response_route_selector"],"NONE")

    async def test_unknown_framework_selector_never_reads_body(self):
        watcher,res=await self.witness(url=PAGE+"&_data=PRIVATE_UNKNOWN")
        self.assertEqual(res.body_reads,0)
        self.assertEqual(watcher.remix_regionless_observed,0)
        self.assertEqual(watcher.summarize_request_verdicts(PAGE)[
            "request_route_selector"],"OTHER_EXTRA")

    async def test_access_denied_never_reads_body(self):
        watcher,res=await self.witness(status=403)
        self.assertEqual(res.body_reads,0)
        self.assertTrue(watcher.restricted)
        self.assertEqual(watcher.remix_regionless_observed,1)
        self.assertEqual(watcher.remix_regionless_events,[])

    async def test_multiple_loader_responses_are_not_admitted(self):
        watcher=PassiveFilteredRoute()
        for _ in range(2):
            req=Request()
            watcher.on_request(req)
            watcher.on_response(Response(req))
        await watcher.drain()
        self.assertEqual(watcher.remix_regionless_observed,2)
        self.assertEqual(watcher.summarize_request_verdicts(PAGE)[
            "observation"],"MULTIPLE_OBSERVED")

    async def test_oversize_content_length_never_reads_body(self):
        watcher=PassiveFilteredRoute()
        req=Request()
        res=Response(req)
        res.headers["content-length"]="2500000"
        watcher.on_request(req)
        watcher.on_response(res)
        await watcher.drain()
        self.assertEqual(res.body_reads,0)
        self.assertEqual(watcher.remix_regionless_events,[])


class Page:
    def __init__(self):
        self.url="https://www.daangn.com/kr/search/buy-sell/?q=HDD"
        self.hooks={}
    def on(self,name,fn):self.hooks.setdefault(name,[]).append(fn)
    def remove_listener(self,name,fn):self.hooks[name].remove(fn)
    async def wait_for_timeout(self,ms):return None
    async def evaluate(self,script):
        types=("POINTERDOWN","POINTERUP","MOUSEDOWN","MOUSEUP","CLICK")
        return {"armed":True,"counts":{k:1 for k in types},
                "trusted":{k:1 for k in types}}


class Button:
    def __init__(self,page):self.page=page;self.clicks=0
    async def is_enabled(self):return True
    async def evaluate(self,script):return True
    async def click(self,**kwargs):
        self.clicks+=1
        self.page.url=PAGE
        req=Request(LOADER)
        res=Response(req)
        for fn in self.page.hooks.get("request",[]):fn(req)
        for fn in self.page.hooks.get("response",[]):fn(res)


class AdmissibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_known_route_with_all_expected_metadata_still_blocks(self):
        page=Page()
        button=Button(page)
        async def select(*args):
            return button,{
                "complete":True,"category":True,"available":True,
                "maximum":50000,"minimum":0,
            }
        async def header(*args):
            return "지역 선택: 천안시 불당동"
        async def no_recheck(*args):
            raise AssertionError("Must not click UI after strict URL failure")
        with (
            patch("app_v5.precollection_filter_gate.v46.set_filter",select),
            patch("app_v5.precollection_filter_gate.v46.check_after",no_recheck),
            patch("app_v5.precollection_filter_gate.read_region_header_volatile",header),
        ):
            result=await verify_filter_before_collection(page)
        self.assertEqual(button.clicks,1)
        self.assertEqual(result["status"],"BLOCKED_FILTER_URL")
        self.assertEqual(result["remix_regionless_route_count"],1)
        self.assertEqual(result["remix_regionless_route_status"],"ONE_PARSED")
        self.assertEqual(result["remix_regionless_server_filters"],
                         {key:"EXPECTED" for key in FIELDS})
        self.assertEqual(result["post_apply_region_header"],"TARGET")
        self.assertEqual(result["apply_search_request_diagnostics"][
            "request_route_selector"],"EXPECTED_SEARCH_LOADER")
        self.assertFalse(result["strict_filter_evidence"])
        self.assertFalse(result["authorizes_listings"])
        self.assertFalse(result["collection_started"])
        self.assertFalse(result["listing_fields_read_or_exported"])
        self.assertFalse(result["database_written"])
        self.assertNotIn("PRIVATE",json.dumps(result))
        self.assertEqual(page.hooks["request"],[])
        self.assertEqual(page.hooks["response"],[])
        self.assertEqual(page.hooks["requestfailed"],[])

    async def test_output_drops_fake_authorization_and_raw_values(self):
        malicious={
            "remix_regionless_route_count":1,
            "remix_regionless_route_status":"ONE_PARSED",
            "remix_regionless_server_filters":{
                "region":"EXPECTED","category":"EXPECTED",
                "price_max":"EXPECTED","available":"EXPECTED",
                "seller":"PRIVATE_ID",
            },
            "apply_search_request_diagnostics":{
                "request_route_selector":"EXPECTED_SEARCH_LOADER",
                "response_route_selector":"EXPECTED_SEARCH_LOADER",
                "raw_url":"https://private.invalid/SECRET"},
            "status":"BLOCKED_FILTER_URL",
            "raw_article":{"title":"PRIVATE_ITEM"},
            "authorizes_listings":True,
        }
        safe=sanitize_precollection(malicious)
        self.assertEqual(sanitize_precollection(safe),safe)
        self.assertFalse(safe["authorizes_listings"])
        self.assertFalse(safe["collection_started"])
        self.assertEqual(safe["remix_regionless_server_filters"]["region"],
                         "EXPECTED")
        self.assertNotIn("PRIVATE",json.dumps(safe))


if __name__=="__main__":
    unittest.main()
