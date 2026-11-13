# -*- coding: utf-8 -*-
"""Separate owner approval for metadata-only inspection of a changed
first-party public Remix _data search response. Offline synthetic tests.
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
    PassiveFilteredRoute, _changed_search_remix_loader,
    inspect_filtered_response, regionless_route_summary,
    sanitize_precollection, verify_filter_before_collection,
)
from ops.oci.precollection import (
    _APPROVAL, _PASSIVE_METADATA_APPROVAL, main, run,
)

PAGE=("https://www.daangn.com/kr/search/buy-sell/"
      "?q=HDD&category_id=1&price=__50000&only_on_sale=true")
NEW=PAGE+"&"+urlencode({"_data":"routes/kr.search.buy-sell.new_v2"})
OLD=PAGE+"&"+urlencode({"_data":"routes/kr.search.buy-sell._index"})
EVENTS=("POINTERDOWN","POINTERUP","MOUSEDOWN","MOUSEUP","CLICK")
UI={"complete":True,"category":True,"available":True,
    "maximum":50000,"minimum":0}


def body(region=2292,category=1,price=50000,available=True,*,price_present=True):
    filters={"regionId":region,"categoryId":category,"onlyOnSale":available}
    if price_present:filters["maxPrice"]=price
    return json.dumps({
        "route":{
            "searchRegion":{"id":region},
            "currentFilters":filters,
            # The parser must not traverse/project any of this payload.
            "buySellArticles":[{
                "title":"PRIVATE_SELLER_SECRET", "url":"https://private.invalid/CREDENTIAL",
                "seller_id":"PERSONAL_SECRET",
            }]
        }
    }).encode("utf-8")


class Request:
    method="GET"
    resource_type="fetch"
    def __init__(self,url=NEW):
        self.url=url


class Response:
    status=200
    headers={"content-type":"application/json"}
    def __init__(self,req,*,url=None,status=200,ct="application/json",data=None):
        self.request=req
        self.url=req.url if url is None else url
        self.status=status
        self.headers={"content-type":ct}
        self.data=body() if data is None else data
        self.body_calls=0
    async def body(self):
        self.body_calls+=1
        return self.data


class Page:
    def __init__(self):
        self.url="https://www.daangn.com/kr/search/buy-sell/?q=HDD"
        self.hooks={}
        self.clicks=0
    def on(self,name,fn):self.hooks.setdefault(name,[]).append(fn)
    def remove_listener(self,name,fn):self.hooks[name].remove(fn)
    async def evaluate(self,script):
        return {"armed":True,"counts":{k:1 for k in EVENTS},
                "trusted":{k:1 for k in EVENTS}}
    async def wait_for_timeout(self,ms):pass


class Button:
    def __init__(self,page):
        self.page=page
        self.responses=[]
    async def is_enabled(self):return True
    async def evaluate(self,script):return True
    async def click(self,**kwargs):
        self.page.clicks+=1
        self.page.url=PAGE
        req=Request()
        self.page.hooks["request"][0](req)
        response=Response(req)
        self.responses.append(response)
        self.page.hooks["response"][0](response)


class SelectorTests(unittest.TestCase):
    def test_accepted_only_explicit_search_prefix_new_route(self):
        self.assertTrue(_changed_search_remix_loader(NEW))
        self.assertFalse(_changed_search_remix_loader(OLD))
        self.assertFalse(_changed_search_remix_loader(PAGE))
        self.assertFalse(_changed_search_remix_loader(
            PAGE+"&_data=routes%2Fkr.search.other"))
        self.assertFalse(_changed_search_remix_loader(
            PAGE+"&_data=private.UNKNOWN"))
    def test_other_keys_redirect_userinfo_duplicate_region_and_bad_filters_reject(self):
        for url in (
            NEW+"&private=SECRET",
            NEW+"&_data=second",
            NEW+"&in=%EB%B6%88%EB%8B%B9%EB%8F%99-2292",
            NEW.replace("q=HDD","q=SSD"),
            NEW.replace("category_id=1","category_id=2"),
            NEW.replace("price=__50000","price=__90000"),
            NEW.replace("only_on_sale=true","only_on_sale=false"),
            NEW.replace("www.daangn.com","private.invalid"),
            NEW.replace("https://","https://account:private@"),
            NEW+"#PRIVATE_SECRET",
            PAGE+"&_data=",
        ):
            with self.subTest(url=url):
                self.assertFalse(_changed_search_remix_loader(url))
    def test_schema_reducer_never_projects_listing_details(self):
        x=inspect_filtered_response(body())
        self.assertEqual(x,{
            "region":"EXPECTED","category":"EXPECTED",
            "price_max":"EXPECTED","available":"EXPECTED"})
        self.assertNotIn("PRIVATE",json.dumps(x))


class PassiveWatcherTests(unittest.IsolatedAsyncioTestCase):
    async def invoke(self,*,enabled=False,request_url=NEW,response_url=None,
                     status=200,ct="application/json",data=None):
        watcher=PassiveFilteredRoute(passive_changed_loader=enabled)
        req=Request(request_url)
        response=Response(req,url=response_url,status=status,ct=ct,data=data)
        watcher.on_request(req)
        watcher.on_response(response)
        await watcher.drain()
        return watcher,response

    async def test_optin_known_fields_are_read_once_not_listings(self):
        watcher,response=await self.invoke(enabled=True)
        self.assertEqual(watcher.changed_observed,1)
        self.assertEqual(response.body_calls,1)
        self.assertEqual(watcher.observed,0)
        self.assertEqual(watcher.changed_events,[{
            "region":"EXPECTED","category":"EXPECTED",
            "price_max":"EXPECTED","available":"EXPECTED"}])
        self.assertEqual(watcher.summarize_request_verdicts(PAGE)[
            "request_extra_query_family"],"OTHER_REMIX_DATA_ID")
        self.assertNotIn("PRIVATE",json.dumps(watcher.changed_events))

    async def test_without_separate_approval_never_reads_unknown_body(self):
        watcher,response=await self.invoke(enabled=False)
        self.assertEqual(watcher.changed_observed,0)
        self.assertEqual(watcher.changed_events,[])
        self.assertEqual(response.body_calls,0)

    async def test_missing_or_wrong_server_fields_not_inferred_from_query(self):
        for data,want in (
            (body(region=2333),("region","OTHER")),
            (body(price_present=False),("price_max","MISSING")),
            (body(available=False),("available","OTHER")),
            (body(category=2),("category","OTHER")),
        ):
            watcher,response=await self.invoke(enabled=True,data=data)
            key,state=want
            self.assertEqual(response.body_calls,1)
            self.assertEqual(watcher.changed_events[0][key],state)

    async def test_unknown_nonfirstparty_or_mismatched_response_url_unread(self):
        for kwargs in (
            {"request_url":PAGE+"&index=abc"},
            {"request_url":PAGE+"&_data=private"},
            {"response_url":PAGE},
            {"response_url":PAGE+"&_data=routes%2Fkr.search.buy-sell.other"},
            {"response_url":"https://private.invalid/SECRET"},
            {"status":403},
            {"ct":"text/html"},
        ):
            with self.subTest(kwargs=kwargs):
                watcher,response=await self.invoke(enabled=True,**kwargs)
                self.assertEqual(response.body_calls,0)
                self.assertEqual(watcher.changed_events,[])

    async def test_oversize_content_length_never_reads_body(self):
        watcher=PassiveFilteredRoute(passive_changed_loader=True)
        req=Request()
        response=Response(req)
        response.headers["content-length"]="2500000"
        watcher.on_request(req)
        watcher.on_response(response)
        await watcher.drain()
        self.assertEqual(response.body_calls,0)

    async def test_multiple_requests_never_authorize_or_pick_best(self):
        watcher=PassiveFilteredRoute(passive_changed_loader=True)
        for _ in range(2):
            req=Request()
            watcher.on_request(req)
            watcher.on_response(Response(req))
        await watcher.drain()
        self.assertEqual(watcher.diagnostics["search_requests"],2)
        self.assertEqual(watcher.summarize_request_verdicts(PAGE)[
            "observation"],"MULTIPLE_OBSERVED")
        self.assertEqual(watcher.observed,0)


class FullOperatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_even_all_server_filters_expected_still_strictly_blocked(self):
        page=Page()
        button=Button(page)
        async def select(*args,**kwargs):
            return button,UI
        async def forbidden(*args):
            raise AssertionError("No after-Apply UI recheck on missing 'in'")
        with (
            patch("app_v5.precollection_filter_gate.v46.set_filter",select),
            patch("app_v5.precollection_filter_gate.v46.check_after",forbidden),
        ):
            row=await verify_filter_before_collection(
                page, passive_changed_loader=True)
        self.assertEqual(page.clicks,1)
        self.assertEqual(row["status"],"BLOCKED_FILTER_URL")
        self.assertTrue(row["changed_loader_metadata_mode"])
        self.assertEqual(row["changed_loader_metadata_count"],1)
        self.assertEqual(row["changed_loader_metadata_status"],"ONE_PARSED")
        self.assertEqual(row["changed_loader_server_filters"],{
            "region":"EXPECTED","category":"EXPECTED",
            "price_max":"EXPECTED","available":"EXPECTED"})
        self.assertFalse(row["authorizes_listings"])
        self.assertFalse(row["strict_filter_evidence"])
        self.assertFalse(row["collection_started"])
        self.assertFalse(row["listing_fields_read_or_exported"])
        self.assertFalse(row["database_written"])
        self.assertEqual(button.responses[0].body_calls,1)
        self.assertNotIn("PRIVATE",json.dumps(row))
        self.assertEqual(page.hooks["request"],[])
        self.assertEqual(page.hooks["response"],[])

    async def test_legacy_mode_remains_no_body_read(self):
        page=Page()
        button=Button(page)
        async def select(*args,**kwargs):return button,UI
        with patch("app_v5.precollection_filter_gate.v46.set_filter",select):
            row=await verify_filter_before_collection(page)
        self.assertEqual(row["status"],"BLOCKED_FILTER_URL")
        self.assertFalse(row["changed_loader_metadata_mode"])
        self.assertEqual(row["changed_loader_metadata_count"],0)
        self.assertEqual(button.responses[0].body_calls,0)


class ApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_approval_not_enough_for_new_probe(self):
        for flag,approval in (
            (True,_APPROVAL),
            (False,_PASSIVE_METADATA_APPROVAL),
            (True,"INVALID"),
        ):
            called=False
            async def fake_diagnostic():
                nonlocal called
                called=True
                return {"status":"INCONCLUSIVE","mode":"FILL"}
            result=await run(
                approve=approval,live=True,headed=True,
                passive_changed_loader=flag,
                directory_check=lambda:True,
                robots=lambda:True,
                picker_robots=lambda term:{"allowed":True},
                diagnostic=fake_diagnostic)
            self.assertEqual(result["status"],"OWNER_APPROVAL_REQUIRED")
            self.assertFalse(called)

    async def test_matching_new_approval_only_one_passive_attempt(self):
        calls=0
        async def fake_diagnostic():
            nonlocal calls
            calls+=1
            return {"status":"INCONCLUSIVE","mode":"FILL"}
        report=await run(
            approve=_PASSIVE_METADATA_APPROVAL,live=True,headed=True,
            passive_changed_loader=True,
            directory_check=lambda:True,
            robots=lambda:True,
            picker_robots=lambda term:{"allowed":True},
            diagnostic=fake_diagnostic)
        self.assertEqual(calls,1)
        self.assertEqual(report["status"],"STOP_REGION_NOT_VERIFIED")
        self.assertFalse(report["collection_started"])
        self.assertFalse(report["authorizes_listings"])

    async def test_both_tokens_still_require_robots_check(self):
        called=False
        async def fake_diagnostic():
            nonlocal called
            called=True
            return {"status":"INCONCLUSIVE","mode":"FILL"}
        report=await run(
            approve=_PASSIVE_METADATA_APPROVAL,live=True,headed=True,
            passive_changed_loader=True,
            directory_check=lambda:True,
            robots=lambda:False,
            picker_robots=lambda term:{"allowed":True},
            diagnostic=fake_diagnostic)
        self.assertEqual(report["status"],"ROBOTS_NOT_ALLOWED")
        self.assertFalse(called)


class SanitizeTests(unittest.TestCase):
    def test_injected_listing_and_approval_cannot_escape_report(self):
        raw={
            "changed_loader_metadata_mode":True,
            "changed_loader_metadata_count":1,
            "changed_loader_metadata_status":"ONE_PARSED",
            "changed_loader_server_filters":{
                "region":"EXPECTED","category":"EXPECTED",
                "price_max":"EXPECTED","available":"EXPECTED",
                "PRIVATE_PERSON":"SECRET"},
            "raw_body":"PRIVATE_SELLER",
            "authorizes_listings":True,"database_written":True,
        }
        safe=sanitize_precollection(raw)
        self.assertEqual(sanitize_precollection(safe),safe)
        self.assertTrue(safe["changed_loader_metadata_mode"])
        self.assertEqual(safe["changed_loader_server_filters"]["region"],
                         "EXPECTED")
        self.assertNotIn("PRIVATE",json.dumps(safe))
        self.assertFalse(safe["authorizes_listings"])
        self.assertFalse(safe["database_written"])

    def test_cli_new_mode_old_token_rejected_before_any_browser(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            code=main([
                "--live","--headed","--passive-new-loader-metadata",
                "--owner-approval",_APPROVAL,
            ])
        self.assertEqual(code,2)
        data=json.loads(output.getvalue())
        self.assertEqual(data["status"],"OWNER_APPROVAL_REQUIRED")
        self.assertFalse(data["authorizes_listings"])


if __name__=="__main__":
    unittest.main()
