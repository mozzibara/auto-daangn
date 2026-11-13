# -*- coding: utf-8 -*-
"""Offline-only approval boundary for dynamic Remix _data route metadata.

No live site calls. No listing body fields exported. No admission changes.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import unittest
from urllib.parse import urlencode
from unittest.mock import patch

from app_v5.precollection_filter_gate import (
    _changed_search_remix_loader, _dynamic_browser_search_loader,
    classify_dynamic_data_route, PassiveFilteredRoute,
    sanitize_apply_request_diagnostics, sanitize_precollection,
    verify_filter_before_collection,
)
from ops.oci.precollection import (
    _APPROVAL, _PASSIVE_METADATA_APPROVAL, _DYNAMIC_METADATA_APPROVAL,
    main, run,
)

PAGE=("https://www.daangn.com/kr/search/buy-sell/"
      "?q=HDD&category_id=1&price=__50000&only_on_sale=true")
NEW=PAGE+"&"+urlencode({"_data":"routes/v2.kr.search.buy-sell._index"})
V1=PAGE+"&"+urlencode({"_data":"routes/kr.search.buy-sell.new_v2"})
OLD=PAGE+"&"+urlencode({"_data":"routes/kr.search.buy-sell._index"})
NON_ROUTES=PAGE+"&_data=app%2FsearchModule"
FIELDS=("region","category","price_max","available")
EVENTS=("POINTERDOWN","POINTERUP","MOUSEDOWN","MOUSEUP","CLICK")
UI={"complete":True,"category":True,"available":True,
    "maximum":50000,"minimum":0}


def model(region=2292,category=1,price=50000,available=True,missing=None):
    filters={"regionId":region,"categoryId":category,
             "maxPrice":price,"onlyOnSale":available}
    if missing:filters.pop(missing,None)
    return json.dumps({"data":{
        "loaderData":{
            "routes/v2.kr.search.buy-sell._index":{
                "searchRegion":{"id":region},
                "currentFilters":filters,
                "buySellArticles":[{"href":"PRIVATE_LISTING_LINK",
                                    "seller":"PRIVATE_SELLER_SECRET"}],
            },
        },
    }}).encode()


class FakeRequest:
    method="GET"
    resource_type="fetch"
    def __init__(self,url=NEW):self.url=url


class FakeResponse:
    status=200
    headers={"content-type":"application/json"}
    def __init__(self,req,*,url=None,code=200,ct="application/json",data=None):
        self.request=req
        self.url=req.url if url is None else url
        self.status=code
        self.headers={"content-type":ct}
        self.payload=model() if data is None else data
        self.body_reads=0
    async def body(self):
        self.body_reads+=1
        return self.payload


class Page:
    def __init__(self):
        self.url="https://www.daangn.com/kr/search/buy-sell/?q=HDD"
        self.hooks={}
        self.clicks=0
    def on(self,kind,fn):self.hooks.setdefault(kind,[]).append(fn)
    def remove_listener(self,kind,fn):self.hooks[kind].remove(fn)
    async def evaluate(self,script):
        return {"armed":True,"counts":{x:1 for x in EVENTS},
                "trusted":{x:1 for x in EVENTS}}
    async def wait_for_timeout(self,ms):pass


class Button:
    def __init__(self,page,url=NEW,body=None):
        self.page=page
        self.url=url
        self.body=body
        self.responses=[]
    async def is_enabled(self):return True
    async def evaluate(self,script):return True
    async def click(self,**kwargs):
        self.page.clicks+=1
        self.page.url=PAGE
        req=FakeRequest(self.url)
        self.page.hooks["request"][0](req)
        rsp=FakeResponse(req,data=self.body)
        self.responses.append(rsp)
        self.page.hooks["response"][0](rsp)


class SelectorTests(unittest.TestCase):
    def test_existing_v1_rejected_but_v2_bounded_routes_detected(self):
        self.assertFalse(_changed_search_remix_loader(NEW))
        self.assertTrue(_dynamic_browser_search_loader(NEW))
        self.assertEqual(classify_dynamic_data_route(NEW),
                         "OTHER_ROUTES_NAMESPACE")
        self.assertEqual(classify_dynamic_data_route(V1),"SEARCH_PREFIX")
        self.assertEqual(classify_dynamic_data_route(OLD),"LEGACY_EXACT")
        self.assertFalse(_dynamic_browser_search_loader(OLD))

    def test_non_route_classified_but_not_read(self):
        self.assertEqual(classify_dynamic_data_route(NON_ROUTES),
                         "NOT_ROUTES_NAMESPACE")
        self.assertFalse(_dynamic_browser_search_loader(NON_ROUTES))

    def test_unexpected_values_and_urls_fail_closed(self):
        invalid=(
            NEW+"&index", NEW+"&_data=another", NEW+"&in=불당동-2292",
            NEW.replace("q=HDD","q=SSD"),
            NEW.replace("category_id=1","category_id=2"),
            NEW.replace("price=__50000","price=__45000"),
            NEW.replace("only_on_sale=true","only_on_sale=false"),
            NEW.replace("www.daangn.com","private.invalid"),
            NEW.replace("https://","https://user:private@"),
            NEW+"#fragment",
            PAGE+"&_data=routes%2F..%2Fsearch",
            PAGE+"&_data=routes%2Ffoo%2F%2Fbar",
            PAGE+"&_data=routes%2Fsearch%20private",
            PAGE+"&_data=",
        )
        for value in invalid:
            with self.subTest(value=value):
                self.assertFalse(_dynamic_browser_search_loader(value))
        self.assertEqual(classify_dynamic_data_route(None),"UNOBSERVABLE")

    def test_no_unknown_route_id_or_keys_escape_sanitization(self):
        v=sanitize_apply_request_diagnostics({
            "request_data_route_family":"OTHER_ROUTES_NAMESPACE",
            "response_data_route_family":"PRIVATE_URL_VALUE",
            "raw_selector":"PRIVATE_ACCESS_TOKEN"})
        self.assertEqual(v["request_data_route_family"],
                         "OTHER_ROUTES_NAMESPACE")
        self.assertEqual(v["response_data_route_family"],"UNOBSERVABLE")
        self.assertNotIn("PRIVATE",json.dumps(v))
        self.assertEqual(sanitize_apply_request_diagnostics(v),v)


class WatcherTests(unittest.IsolatedAsyncioTestCase):
    async def observe(self,*,mode=False,request=NEW,response=None,code=200,
                      ctype="application/json",data=None):
        watcher=PassiveFilteredRoute(passive_dynamic_loader=mode)
        req=FakeRequest(request)
        rsp=FakeResponse(req,url=response,code=code,ct=ctype,data=data)
        watcher.on_request(req)
        watcher.on_response(rsp)
        await watcher.drain()
        return watcher,rsp

    async def test_separate_v2_mode_reads_only_search_scalar_metadata(self):
        w,r=await self.observe(mode=True)
        self.assertEqual(w.dynamic_observed,1)
        self.assertEqual(r.body_reads,1)
        self.assertEqual(w.dynamic_events,[{
            "region":"EXPECTED","category":"EXPECTED",
            "price_max":"EXPECTED","available":"EXPECTED"}])
        self.assertEqual(w.observed,0)
        self.assertEqual(w.summarize_request_verdicts(PAGE)[
            "request_data_route_family"],"OTHER_ROUTES_NAMESPACE")
        self.assertNotIn("PRIVATE",json.dumps(w.dynamic_events))

    async def test_default_and_v1_do_not_read_v2_route_body(self):
        for kwargs in ({},{ "passive_changed_loader":True}):
            w=PassiveFilteredRoute(**kwargs)
            req=FakeRequest()
            rsp=FakeResponse(req)
            w.on_request(req)
            w.on_response(rsp)
            await w.drain()
            self.assertEqual(rsp.body_reads,0)
            self.assertEqual(w.dynamic_observed,0)

    async def test_server_mismatch_is_not_inferred_from_expected_query(self):
        for data,key,expected in (
            (model(region=2333),"region","OTHER"),
            (model(category=2),"category","OTHER"),
            (model(price=40000),"price_max","OTHER"),
            (model(available=False),"available","OTHER"),
            (model(missing="maxPrice"),"price_max","MISSING"),
        ):
            w,r=await self.observe(mode=True,data=data)
            self.assertEqual(r.body_reads,1)
            self.assertEqual(w.dynamic_events[0][key],expected)

    async def test_restricted_redirect_unknown_response_type_not_read(self):
        for kw in (
            {"code":403},{"code":429},{"code":401},
            {"response":PAGE},
            {"response":PAGE+"&_data=routes%2Fother"},
            {"response":"https://private.invalid/SECRET"},
            {"ctype":"text/html"},
            {"request":NON_ROUTES},
        ):
            with self.subTest(kw=kw):
                w,r=await self.observe(mode=True,**kw)
                self.assertEqual(r.body_reads,0)
                self.assertEqual(w.dynamic_events,[])

    async def test_size_limit_blocks_body_read(self):
        w=PassiveFilteredRoute(passive_dynamic_loader=True)
        req=FakeRequest()
        rsp=FakeResponse(req)
        rsp.headers["content-length"]="2000001"
        w.on_request(req);w.on_response(rsp)
        await w.drain()
        self.assertEqual(rsp.body_reads,0)

    async def test_multiple_browser_requests_never_select_best(self):
        w=PassiveFilteredRoute(passive_dynamic_loader=True)
        for _ in range(2):
            req=FakeRequest()
            rsp=FakeResponse(req)
            w.on_request(req)
            w.on_response(rsp)
        await w.drain()
        self.assertEqual(w.diagnostics["search_requests"],2)
        self.assertEqual(w.summarize_request_verdicts(PAGE)[
            "observation"],"MULTIPLE_OBSERVED")
        self.assertEqual(w.observed,0)


class EndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self,*,mode=True,payload=None):
        page=Page()
        btn=Button(page,body=payload)
        async def select(*args,**kwargs):return btn,UI
        async def no_recheck(*args):
            raise AssertionError("Missing in must still block before recheck")
        with (patch("app_v5.precollection_filter_gate.v46.set_filter",select),
              patch("app_v5.precollection_filter_gate.v46.check_after",
                    no_recheck)):
            row=await verify_filter_before_collection(
                page, passive_dynamic_loader=mode)
        return btn,row

    async def test_even_all_expected_is_still_not_collection_approval(self):
        btn,row=await self._run()
        self.assertEqual(row["status"],"BLOCKED_FILTER_URL")
        self.assertTrue(row["dynamic_loader_metadata_mode"])
        self.assertEqual(row["dynamic_loader_metadata_count"],1)
        self.assertEqual(row["dynamic_loader_metadata_status"],"ONE_PARSED")
        self.assertEqual(row["dynamic_loader_server_filters"],{
            "region":"EXPECTED","category":"EXPECTED",
            "price_max":"EXPECTED","available":"EXPECTED"})
        self.assertEqual(btn.page.clicks,1)
        self.assertEqual(btn.responses[0].body_reads,1)
        self.assertEqual(row["filtered_route_count"],0)
        self.assertFalse(row["filtered_url_matches"])
        self.assertFalse(row["ui_selected_after_apply"])
        self.assertFalse(row["strict_filter_evidence"])
        self.assertFalse(row["collection_started"])
        self.assertFalse(row["listing_fields_read_or_exported"])
        self.assertFalse(row["database_written"])
        self.assertFalse(row["authorizes_listings"])
        self.assertNotIn("PRIVATE",json.dumps(row))
        self.assertEqual(btn.page.hooks["request"],[])
        self.assertEqual(btn.page.hooks["response"],[])

    async def test_missing_price_data_is_not_approved(self):
        btn,row=await self._run(payload=model(missing="maxPrice"))
        self.assertEqual(row["dynamic_loader_server_filters"]["price_max"],
                         "MISSING")
        self.assertFalse(row["strict_filter_evidence"])

    async def test_without_v2_mode_body_remains_unread(self):
        btn,row=await self._run(mode=False)
        self.assertFalse(row["dynamic_loader_metadata_mode"])
        self.assertEqual(btn.responses[0].body_reads,0)


class ApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_incompatible_flags_and_tokens_reject_before_browser(self):
        combos=(
            (True,False,_DYNAMIC_METADATA_APPROVAL),
            (False,True,_PASSIVE_METADATA_APPROVAL),
            (False,False,_DYNAMIC_METADATA_APPROVAL),
            (True,True,_DYNAMIC_METADATA_APPROVAL),
            (False,True,_APPROVAL),
        )
        for old,new,token in combos:
            called=False
            async def diagnostic():
                nonlocal called
                called=True
                return {"status":"INCONCLUSIVE","mode":"FILL"}
            answer=await run(
                approve=token,live=True,headed=True,
                passive_changed_loader=old,passive_dynamic_loader=new,
                directory_check=lambda:True,robots=lambda:True,
                picker_robots=lambda q:{"allowed":True},
                diagnostic=diagnostic)
            self.assertEqual(answer["status"],"OWNER_APPROVAL_REQUIRED")
            self.assertFalse(called)

    async def test_v2_matching_token_still_requires_robots_approval(self):
        called=False
        async def diagnostic():
            nonlocal called
            called=True
            return {"status":"INCONCLUSIVE","mode":"FILL"}
        answer=await run(
            approve=_DYNAMIC_METADATA_APPROVAL,live=True,headed=True,
            passive_dynamic_loader=True,
            directory_check=lambda:True,robots=lambda:False,
            picker_robots=lambda q:{"allowed":True},diagnostic=diagnostic)
        self.assertEqual(answer["status"],"ROBOTS_NOT_ALLOWED")
        self.assertFalse(called)

    async def test_matching_token_runs_single_diagnostic_no_collection(self):
        calls=0
        async def diagnostic():
            nonlocal calls
            calls+=1
            return {"status":"INCONCLUSIVE","mode":"FILL"}
        answer=await run(
            approve=_DYNAMIC_METADATA_APPROVAL,live=True,headed=True,
            passive_dynamic_loader=True,
            directory_check=lambda:True,robots=lambda:True,
            picker_robots=lambda q:{"allowed":True},diagnostic=diagnostic)
        self.assertEqual(calls,1)
        self.assertEqual(answer["status"],"STOP_REGION_NOT_VERIFIED")
        self.assertFalse(answer["collection_started"])
        self.assertFalse(answer["authorizes_listings"])

    async def test_cli_v2_old_approval_rejected_before_browser(self):
        target=io.StringIO()
        with contextlib.redirect_stdout(target):
            exitcode=main(["--live","--headed","--passive-dynamic-loader-metadata",
                "--owner-approval",_PASSIVE_METADATA_APPROVAL])
        self.assertEqual(exitcode,2)
        self.assertEqual(json.loads(target.getvalue())["status"],
                         "OWNER_APPROVAL_REQUIRED")


class SanitizerTests(unittest.TestCase):
    def test_dynamic_fields_are_all_fixed_and_idempotent(self):
        row={
            "dynamic_loader_metadata_mode":True,
            "dynamic_loader_metadata_count":1,
            "dynamic_loader_metadata_status":"ONE_PARSED",
            "dynamic_loader_server_filters":{
                "region":"EXPECTED","category":"EXPECTED",
                "price_max":"EXPECTED","available":"EXPECTED",
                "SELLER":"PRIVATE_SELLER"},
            "raw_body":"PRIVATE_SELLER",
            "database_written":True,"authorizes_listings":True,
        }
        safe=sanitize_precollection(row)
        self.assertEqual(safe["dynamic_loader_metadata_count"],1)
        self.assertEqual(safe["dynamic_loader_server_filters"]["region"],
                         "EXPECTED")
        self.assertFalse(safe["authorizes_listings"])
        self.assertFalse(safe["database_written"])
        self.assertNotIn("PRIVATE",json.dumps(safe))
        self.assertEqual(sanitize_precollection(safe),safe)


if __name__=="__main__":
    unittest.main()
