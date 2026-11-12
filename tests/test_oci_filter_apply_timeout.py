# -*- coding: utf-8 -*-
"""Offline-only Playwright Apply-click timeout and strict no-retry regressions."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app_v5.filter_apply_activation import (
    FilterApplyActivationWitness, sanitize_apply_activation,
)
from app_v5.precollection_filter_gate import (
    verify_filter_before_collection, sanitize_precollection,
    classify_filter_url,
)

URL=("https://www.daangn.com/kr/search/buy-sell/"
     "?q=HDD&in=%EB%B6%88%EB%8B%B9%EB%8F%99-2292"
     "&category_id=1&price=__50000&only_on_sale=true")
WRONG_URL=URL.replace("price=__50000","price=__45000")
EVENTS=("POINTERDOWN","POINTERUP","MOUSEDOWN","MOUSEUP","CLICK")
BEFORE={"complete":True,"category":True,"available":True,
        "maximum":50000,"minimum":0}


class Request:
    method="GET"
    resource_type="fetch"
    def __init__(self,url):
        self.url=url


class Response:
    def __init__(self,req):
        self.request=req
        self.url=req.url
        self.status=200
        self.headers={"content-type":"application/json"}
        self.body_calls=0
    async def body(self):
        self.body_calls+=1
        raise AssertionError("Never read a nonmatching Route response")


class Page:
    def __init__(self,*,witness_count=1, response_url=WRONG_URL):
        self.url="https://www.daangn.com/kr/search/buy-sell/?q=HDD"
        self.hooks={}
        self.witness_count=witness_count
        self.response_url=response_url
        self.witness_evaluations=0
    def on(self,key,callback):
        self.hooks.setdefault(key,[]).append(callback)
    def remove_listener(self,key,callback):
        self.hooks[key].remove(callback)
    async def evaluate(self,script):
        self.witness_evaluations+=1
        return {
            "armed":True,
            "counts":{k:self.witness_count for k in EVENTS},
            "trusted":{k:self.witness_count for k in EVENTS},
            "private_raw_title":"PRIVATE_SELLER_NAME",
        }
    async def wait_for_timeout(self,ms):
        return None
    def delivered_request(self):
        self.url=self.response_url
        req=Request(self.response_url)
        resp=Response(req)
        for cb in self.hooks.get("request",[]):
            cb(req)
        for cb in self.hooks.get("response",[]):
            cb(resp)
        return resp


class Button:
    def __init__(self,page,*,err="timeout",delivered=True):
        self.page=page
        self.err=err
        self.delivered=delivered
        self.clicks=0
    async def is_enabled(self):
        return True
    async def evaluate(self,script):
        return True
    async def click(self,**kwargs):
        self.clicks+=1
        if self.delivered:
            self.page.delivered_request()
        if self.err=="timeout":
            raise PlaywrightTimeoutError("PRIVATE_POST_NAVIGATION_WAIT")
        if self.err=="other":
            raise RuntimeError("PRIVATE_JS_ERROR")
        return None


class TimeoutDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self,*,count=1,error="timeout",delivered=True):
        page=Page(witness_count=count)
        button=Button(page,err=error,delivered=delivered)
        async def select(*args):
            return button,BEFORE
        async def forbidden_recheck(*args):
            raise AssertionError("No UI-recheck or second click on Apply timeout")
        with patch("app_v5.precollection_filter_gate.v46.set_filter",select),\
             patch("app_v5.precollection_filter_gate.v46.check_after",
                   forbidden_recheck):
            result=await verify_filter_before_collection(page)
        return result,page,button

    async def test_delivered_apply_click_timeout_retains_transport_and_url(self):
        result,page,button=await self._run()
        self.assertEqual(result["status"],"BLOCKED_APPLY_ACTION")
        self.assertFalse(result["filter_apply_returned"])
        self.assertEqual(result["apply_action_stage"],"BEFORE_APPLY_CLICK")
        self.assertEqual(result["apply_action_exception_kind"],"PLAYWRIGHT_TIMEOUT")
        self.assertTrue(result["apply_activation"]["one_trusted_click"])
        self.assertEqual(result["apply_activation"]["trusted"]["CLICK"],1)
        self.assertEqual(result["filter_transport_diagnostics"]["search_requests"],1)
        self.assertEqual(result["filter_transport_diagnostics"]["search_response_200"],1)
        self.assertEqual(result["filtered_url_diagnostics"]["fields"]["price_max"],"OTHER")
        self.assertEqual(result["filtered_route_count"],0)
        self.assertTrue(result["apply_request_listener_armed"])
        self.assertEqual(button.clicks,1)
        self.assertEqual(page.hooks["request"],[])
        self.assertEqual(page.hooks["response"],[])
        self.assertEqual(page.hooks["requestfailed"],[])
        self.assertFalse(result["authorizes_listings"])
        self.assertFalse(result["collection_started"])
        self.assertFalse(result["database_written"])
        self.assertNotIn("PRIVATE",json.dumps(result))

    async def test_click_timeout_without_delivered_browser_event_fails_closed(self):
        result,page,button=await self._run(count=0,delivered=False)
        self.assertEqual(result["status"],"BLOCKED_APPLY_ACTION")
        self.assertEqual(result["filter_transport_diagnostics"]["search_requests"],0)
        self.assertEqual(result["apply_activation"]["trusted"]["CLICK"],0)
        self.assertFalse(result["apply_activation"]["one_trusted_click"])
        self.assertEqual(button.clicks,1)

    async def test_untrusted_or_duplicated_browser_event_never_passes(self):
        for count in (0,2):
            result,page,button=await self._run(count=count)
            self.assertEqual(result["status"],"BLOCKED_APPLY_ACTION")
            self.assertFalse(result["apply_activation"]["one_trusted_click"])
            self.assertEqual(button.clicks,1)

    async def test_non_timeout_exception_is_classified_not_leaked(self):
        result,page,button=await self._run(error="other")
        self.assertEqual(result["status"],"BLOCKED_APPLY_ACTION")
        self.assertEqual(result["apply_action_exception_kind"],"OTHER_EXCEPTION")
        self.assertTrue(result["apply_activation"]["one_trusted_click"])
        self.assertEqual(button.clicks,1)

    async def test_successful_click_with_wrong_url_still_blocks(self):
        result,page,button=await self._run(error=None)
        self.assertEqual(result["status"],"BLOCKED_FILTER_URL")
        self.assertTrue(result["filter_apply_returned"])
        self.assertEqual(result["apply_action_exception_kind"],"NONE")
        self.assertEqual(result["apply_action_stage"],"AFTER_TRANSPORT_DRAIN")
        self.assertEqual(result["filtered_url_diagnostics"]["fields"]["price_max"],"OTHER")
        self.assertEqual(button.clicks,1)
        self.assertFalse(result["authorizes_listings"])


class SanitizerTests(unittest.TestCase):
    def test_apply_activation_is_strictly_numeric_boolean_idempotent(self):
        raw={"armed":True,"counts":{n:1 for n in EVENTS},
             "trusted":{n:1 for n in EVENTS},
             "url":"https://private.invalid/SECRET"}
        safe=sanitize_apply_activation(raw)
        self.assertTrue(safe["one_trusted_click"])
        self.assertEqual(sanitize_apply_activation(safe),safe)
        self.assertNotIn("SECRET",json.dumps(safe))

    def test_invalid_and_missing_events_cannot_be_approved(self):
        for value in (
            {"armed":True,"counts":{n:True for n in EVENTS},
             "trusted":{n:True for n in EVENTS}},
            {"armed":True,"counts":{"CLICK":1},"trusted":{"CLICK":1}},
            {"armed":False,"counts":{n:1 for n in EVENTS},
             "trusted":{n:1 for n in EVENTS}},
            {"armed":True,"counts":{n:1 for n in EVENTS},
             "trusted":{n:0 for n in EVENTS}},
        ):
            out=sanitize_apply_activation(value)
            self.assertFalse(out["one_trusted_click"])

    def test_nested_output_drops_raw_exception_and_listing_values(self):
        raw={
            "status":"BLOCKED_APPLY_ACTION",
            "apply_action_stage":"BEFORE_APPLY_CLICK",
            "apply_action_exception_kind":"PRIVATE_ERROR",
            "apply_activation":{"armed":True,
                                "cookie":"PRIVATE_COOKIE",
                                "counts":{"CLICK":1},
                                "trusted":{"CLICK":1}},
            "raw_exception":"PRIVATE_SECRET",
            "price":1234,
            "authorizes_listings":True,
        }
        safe=sanitize_precollection(raw)
        self.assertEqual(safe["apply_action_exception_kind"],"NONE")
        self.assertEqual(sanitize_precollection(safe),safe)
        self.assertFalse(safe["authorizes_listings"])
        self.assertNotIn("PRIVATE",json.dumps(safe))


if __name__=="__main__":
    unittest.main()
