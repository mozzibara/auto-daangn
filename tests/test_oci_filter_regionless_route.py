# -*- coding: utf-8 -*-
"""Synthetic, zero-marketplace regionless filtered Route diagnostics."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from app_v5.precollection_filter_gate import (
    _exact_except_missing_region, PassiveFilteredRoute,
    regionless_route_summary, sanitize_precollection,
    verify_filter_before_collection,
)

ROOT="https://www.daangn.com/kr/search/buy-sell/"
REGIONLESS=(
    ROOT+"?q=HDD&category_id=1&price=__50000&only_on_sale=true"
)
EXACT=(
    ROOT+"?q=HDD&in=%EB%B6%88%EB%8B%B9%EB%8F%99-2292"
    "&category_id=1&price=__50000&only_on_sale=true"
)
_FIELDS=("region","category","price_max","available")


def body(*, region=2292, category=1, max_price=50000, available=True):
    return json.dumps({
        "route":{
            "searchRegion":{"id":region,"name":"PRIVATE_REGION"},
            "currentFilters":{
                "regionId":region, "categoryId":category,
                "maxPrice":max_price, "onlyOnSale":available,
            },
            "buySellArticles":[{
                "title":"PRIVATE_SELLER_TITLE",
                "url":"https://private.invalid/listings/SECRET",
                "price":100000,
            }],
        }
    },ensure_ascii=False).encode()


class Request:
    method="GET"
    resource_type="fetch"
    def __init__(self,url=REGIONLESS):
        self.url=url


class Response:
    status=200
    headers={"content-type":"application/json"}
    def __init__(self, req, data=None, status=200):
        self.request=req
        self.url=req.url
        self.status=status
        self.data=data if data is not None else body()
        self.body_reads=0
    async def body(self):
        self.body_reads+=1
        return self.data


class ClassifyTests(unittest.TestCase):
    def test_only_missing_region_with_all_four_exact_filters_accepted_for_diagnosis(self):
        self.assertTrue(_exact_except_missing_region(REGIONLESS))
        for bad in (
            EXACT,
            REGIONLESS.replace("q=HDD","q=SSD"),
            REGIONLESS.replace("category_id=1","category_id=2"),
            REGIONLESS.replace("price=__50000","price=__75000"),
            REGIONLESS.replace("only_on_sale=true","only_on_sale=false"),
            REGIONLESS+"&in=other",
            REGIONLESS+"&price=__50000",
            REGIONLESS+"&secret=PRIVATE_TOKEN",
            REGIONLESS.replace("www.daangn.com","evil.invalid"),
        ):
            self.assertFalse(_exact_except_missing_region(bad),bad)

    def test_strict_approved_route_stays_unavailable_if_region_missing(self):
        from app_v5.precollection_filter_gate import _unique_query
        self.assertFalse(_unique_query(REGIONLESS))
        self.assertTrue(_unique_query(EXACT))


class RouteMetadataOnlyTests(unittest.IsolatedAsyncioTestCase):
    async def _witness(self, request=None, response=None):
        watcher=PassiveFilteredRoute()
        request=request or Request()
        response=response or Response(request)
        watcher.on_request(request)
        watcher.on_response(response)
        await watcher.drain()
        return watcher,response

    async def test_region_retained_on_backend_is_diagnostic_only(self):
        watcher,response=await self._witness()
        self.assertEqual(response.body_reads,1)
        self.assertEqual(watcher.observed,0)
        self.assertEqual(watcher.events,[])
        self.assertEqual(watcher.regionless_observed,1)
        status, fields=regionless_route_summary(
            watcher.regionless_observed, watcher.regionless_events)
        self.assertEqual(status,"ONE_PARSED")
        self.assertEqual(fields,{key:"EXPECTED" for key in _FIELDS})
        self.assertNotIn("PRIVATE",json.dumps(fields))
        self.assertEqual(watcher.diagnostics["search_different_query_requests"],1)

    async def test_backend_region_mismatch_is_observed_without_listing_content(self):
        req=Request()
        watcher,_=await self._witness(req,Response(req,body(region=2333)))
        status, fields=regionless_route_summary(
            watcher.regionless_observed, watcher.regionless_events)
        self.assertEqual(status,"ONE_PARSED")
        self.assertEqual(fields["region"],"OTHER")
        self.assertNotIn("PRIVATE",json.dumps(fields))

    async def test_missing_price_is_not_assumed_from_url(self):
        req=Request()
        data=json.loads(body())
        del data["route"]["currentFilters"]["maxPrice"]
        watcher,_=await self._witness(
            req,Response(req,json.dumps(data).encode()))
        status,fields=regionless_route_summary(
            watcher.regionless_observed, watcher.regionless_events)
        self.assertEqual(fields["price_max"],"MISSING")

    async def test_multiple_regionless_responses_remain_ambiguous(self):
        watcher=PassiveFilteredRoute()
        for i in (1,2):
            req=Request()
            watcher.on_request(req)
            watcher.on_response(Response(req))
        await watcher.drain()
        self.assertEqual(watcher.regionless_observed,2)
        status,fields=regionless_route_summary(
            watcher.regionless_observed, watcher.regionless_events)
        self.assertEqual(status,"MULTIPLE_OBSERVED")
        self.assertTrue(all(x=="MISSING" for x in fields.values()))

    async def test_403_blocks_without_reading_body(self):
        req=Request()
        res=Response(req,status=403)
        watcher,_=await self._witness(req,res)
        self.assertTrue(watcher.restricted)
        self.assertEqual(watcher.regionless_observed,1)
        self.assertEqual(res.body_reads,0)
        self.assertEqual(regionless_route_summary(
            watcher.regionless_observed,watcher.regionless_events)[0],
            "ONE_UNREADABLE")

    async def test_non_exact_regionless_query_does_not_read_body(self):
        req=Request(REGIONLESS.replace("price=__50000","price=__49000"))
        res=Response(req)
        watcher,_=await self._witness(req,res)
        self.assertEqual(watcher.regionless_observed,0)
        self.assertEqual(res.body_reads,0)
        self.assertEqual(watcher.observed,0)


class Page:
    def __init__(self):
        self.url=ROOT+"?q=HDD&in=%EB%B6%88%EB%8B%B9%EB%8F%99-2292"
        self.hooks={}
    def on(self,name,callback):
        self.hooks.setdefault(name,[]).append(callback)
    def remove_listener(self,name,callback):
        self.hooks[name].remove(callback)
    async def wait_for_timeout(self,ms):
        return None
    async def evaluate(self,script):
        keys=("CLICK","MOUSEDOWN","MOUSEUP","POINTERDOWN","POINTERUP")
        return {"armed":True,"counts":{k:1 for k in keys},
                "trusted":{k:1 for k in keys}}


class Button:
    def __init__(self,page):
        self.page=page
        self.clicks=0
    async def is_enabled(self):return True
    async def evaluate(self,script):return True
    async def click(self,**kwargs):
        self.clicks+=1
        self.page.url=REGIONLESS
        req=Request(REGIONLESS)
        res=Response(req)
        for f in self.page.hooks.get("request",[]):f(req)
        for f in self.page.hooks.get("response",[]):f(res)


class EndToEndBlockedTests(unittest.IsolatedAsyncioTestCase):
    async def test_expected_regionless_backend_still_does_not_authorize_collection(self):
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
            raise AssertionError("No second UI click after blocked URL")
        with (
            patch("app_v5.precollection_filter_gate.v46.set_filter",select),
            patch("app_v5.precollection_filter_gate.v46.check_after",no_recheck),
            patch("app_v5.precollection_filter_gate.read_region_header_volatile",header),
        ):
            result=await verify_filter_before_collection(page)
        self.assertEqual(button.clicks,1)
        self.assertEqual(result["status"],"BLOCKED_FILTER_URL")
        self.assertFalse(result["filtered_url_matches"])
        self.assertEqual(result["filtered_route_count"],0)
        self.assertEqual(result["regionless_route_count"],1)
        self.assertEqual(result["regionless_route_status"],"ONE_PARSED")
        self.assertEqual(
            result["regionless_server_filters"],
            {key:"EXPECTED" for key in _FIELDS})
        self.assertEqual(result["post_apply_region_header"],"TARGET")
        self.assertFalse(result["strict_filter_evidence"])
        self.assertFalse(result["authorizes_listings"])
        self.assertFalse(result["collection_started"])
        self.assertFalse(result["database_written"])
        self.assertNotIn("PRIVATE",json.dumps(result))
        for handlers in page.hooks.values():
            self.assertEqual(handlers,[])

    async def test_output_sanitizer_cannot_smuggle_raw_listing_or_approval(self):
        row={
            "regionless_route_count":1,
            "regionless_route_status":"ONE_PARSED",
            "regionless_server_filters":{
                "region":"EXPECTED","category":"EXPECTED",
                "available":"EXPECTED","price_max":"EXPECTED",
                "seller":"PRIVATE_SELLER",
            },
            "post_apply_region_header":"PRIVATE_ADDRESS",
            "raw_listing_url":"https://private.invalid",
            "status":"PRECOLLECTION_READY_REVIEW",
            "authorizes_listings":True,
            "collection_started":True,
        }
        result=sanitize_precollection(row)
        self.assertEqual(sanitize_precollection(result),result)
        self.assertEqual(result["post_apply_region_header"],"UNOBSERVABLE")
        self.assertFalse(result["authorizes_listings"])
        self.assertFalse(result["collection_started"])
        self.assertNotIn("PRIVATE",json.dumps(result))
        self.assertEqual(result["regionless_server_filters"]["region"],"EXPECTED")


if __name__=="__main__":
    unittest.main()
