# -*- coding: utf-8 -*-
"""Passive Apply-click timeout observation of an *already started* request.

All tests simulate browser events. No public website network connections.
"""
from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app_v5.precollection_filter_gate import (
    verify_filter_before_collection, sanitize_precollection,
    passive_posttimeout_request_observation,
)

PAGE_URL="https://www.daangn.com/kr/search/buy-sell/?q=HDD"
FILTER_URL=(
    PAGE_URL+"&category_id=1&price=__50000&only_on_sale=true"
    "&_data=routes%2Fkr.search.buy-sell.new_v2"
)
FIXED_UI={
    "complete":True,"category":True,"available":True,
    "maximum":50000,"minimum":0,
}
EVENTS=("POINTERDOWN","POINTERUP","MOUSEDOWN","MOUSEUP","CLICK")


class Request:
    method="GET"
    resource_type="fetch"
    def __init__(self,url=FILTER_URL):self.url=url


class Response:
    status=200
    headers={"content-type":"application/json"}
    def __init__(self,request,status=200):
        self.request=request
        self.status=status
        self.url=request.url
        self.body_reads=0
    async def body(self):
        self.body_reads+=1
        raise AssertionError("Unknown Remix response body must never be read")


class Page:
    def __init__(self,*,clicks=1):
        self.url=PAGE_URL
        self.clicks=clicks
        self.hooks={}
        self.background=[]
    def on(self,name,fn):
        self.hooks.setdefault(name,[]).append(fn)
    def remove_listener(self,name,fn):
        self.hooks[name].remove(fn)
    async def evaluate(self,script):
        return {
            "armed":True,
            "counts":{k:self.clicks for k in EVENTS},
            "trusted":{k:self.clicks for k in EVENTS},
            "raw_private":"PRIVATE_SELLER_ID",
        }
    async def wait_for_timeout(self,ms):
        return None
    def event(self,name,obj):
        for cb in list(self.hooks.get(name,())):
            cb(obj)


class Button:
    def __init__(self,page,*,scenario):
        self.page=page
        self.scenario=scenario
        self.calls=0
        self.responses=[]
    async def is_enabled(self):return True
    async def evaluate(self,script):return True
    async def click(self,**kwargs):
        self.calls+=1
        if self.scenario != "NO_REQUEST":
            req=Request()
            self.page.event("request",req)
            async def send_later():
                await asyncio.sleep(.012)
                response=Response(req,403 if self.scenario=="LATE_RESTRICTED" else 200)
                self.responses.append(response)
                self.page.event("response",response)
            if self.scenario in ("LATE_RESPONSE","LATE_RESTRICTED"):
                task=asyncio.create_task(send_later())
                self.page.background.append(task)
            elif self.scenario=="EARLY_RESPONSE":
                response=Response(req)
                self.responses.append(response)
                self.page.event("response",response)
            elif self.scenario=="SECOND_REQUEST":
                self.page.event("request",Request())
        raise PlaywrightTimeoutError("PRIVATE_ACTION_WAIT_ERROR")


class OperatorTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def execute(self,scenario,*,clicks=1):
        page=Page(clicks=clicks)
        button=Button(page,scenario=scenario)
        async def select(*args):
            return button,FIXED_UI
        async def never_recheck(*args):
            raise AssertionError("No Apply retry or filter UI recheck after timeout")
        with (
            patch("app_v5.precollection_filter_gate.v46.set_filter",select),
            patch("app_v5.precollection_filter_gate.v46.check_after",never_recheck),
            patch("app_v5.precollection_filter_gate._POST_TIMEOUT_OBSERVATION_SEC",.045),
        ):
            result=await verify_filter_before_collection(page)
        if page.background:
            await asyncio.gather(*page.background)
        return page,button,result

    async def test_late_200_request_is_observed_but_not_admitted(self):
        page,button,row=await self.execute("LATE_RESPONSE")
        self.assertEqual(row["status"],"BLOCKED_APPLY_ACTION")
        self.assertEqual(row["posttimeout_passive_observation"],
                         "OBSERVED_LATE_RESPONSE")
        self.assertEqual(row["apply_action_exception_kind"],"PLAYWRIGHT_TIMEOUT")
        self.assertEqual(row["apply_action_stage"],"BEFORE_APPLY_CLICK")
        self.assertEqual(row["filter_transport_diagnostics"]["search_requests"],1)
        self.assertEqual(row["filter_transport_diagnostics"]["search_responses"],1)
        self.assertEqual(row["filter_transport_diagnostics"]["search_response_200"],1)
        self.assertEqual(row["apply_search_request_diagnostics"][
            "request_extra_query_family"],"OTHER_REMIX_DATA_ID")
        self.assertEqual(row["apply_search_request_diagnostics"][
            "response_extra_query_family"],"OTHER_REMIX_DATA_ID")
        self.assertEqual(button.calls,1)
        self.assertEqual(button.responses[0].body_reads,0)
        self.assertEqual(page.hooks["request"],[])
        self.assertEqual(page.hooks["response"],[])
        self.assertEqual(page.hooks["requestfailed"],[])
        self.assertFalse(row["filter_apply_returned"])
        self.assertFalse(row["strict_filter_evidence"])
        self.assertFalse(row["authorizes_listings"])
        self.assertFalse(row["collection_started"])
        self.assertFalse(row["database_written"])
        self.assertNotIn("PRIVATE",json.dumps(row))

    async def test_request_does_not_complete_in_bounded_window(self):
        page,button,row=await self.execute("NO_RESPONSE")
        self.assertEqual(row["posttimeout_passive_observation"],
                         "NO_RESPONSE_IN_WINDOW")
        self.assertEqual(row["filter_transport_diagnostics"]["search_requests"],1)
        self.assertEqual(row["filter_transport_diagnostics"]["search_responses"],0)
        self.assertEqual(row["apply_search_request_diagnostics"]["outcome"],
                         "NOT_OBSERVED")
        self.assertEqual(button.calls,1)

    async def test_untrusted_or_missing_click_skips_passive_wait(self):
        for clicks in (0,2):
            with self.subTest(clicks=clicks):
                page,button,row=await self.execute("NO_RESPONSE",clicks=clicks)
                self.assertEqual(row["posttimeout_passive_observation"],
                                 "SKIPPED_CLICK_NOT_PROVEN")
                self.assertFalse(row["apply_activation"]["one_trusted_click"])
                self.assertEqual(button.calls,1)

    async def test_zero_request_does_not_trigger_wait(self):
        page,button,row=await self.execute("NO_REQUEST")
        self.assertEqual(row["posttimeout_passive_observation"],
                         "SKIPPED_REQUEST_NOT_UNIQUE")
        self.assertEqual(row["filter_transport_diagnostics"]["search_requests"],0)
        self.assertEqual(button.calls,1)

    async def test_two_requests_are_ambiguous_no_favorable_selection(self):
        page,button,row=await self.execute("SECOND_REQUEST")
        self.assertEqual(row["posttimeout_passive_observation"],
                         "SKIPPED_REQUEST_NOT_UNIQUE")
        self.assertEqual(row["filter_transport_diagnostics"]["search_requests"],2)
        self.assertEqual(row["apply_search_request_diagnostics"]["observation"],
                         "MULTIPLE_OBSERVED")
        self.assertEqual(button.calls,1)

    async def test_early_response_is_not_misclassified_as_late(self):
        page,button,row=await self.execute("EARLY_RESPONSE")
        self.assertEqual(row["posttimeout_passive_observation"],
                         "SKIPPED_ALREADY_RESPONDED")
        self.assertEqual(row["filter_transport_diagnostics"]["search_responses"],1)
        self.assertEqual(button.responses[0].body_reads,0)
        self.assertEqual(button.calls,1)

    async def test_late_access_restriction_stops_passively(self):
        page,button,row=await self.execute("LATE_RESTRICTED")
        self.assertEqual(row["posttimeout_passive_observation"],"SKIPPED_RESTRICTED")
        self.assertEqual(row["filter_transport_diagnostics"]["search_response_restricted"],1)
        self.assertEqual(button.responses[0].body_reads,0)
        self.assertFalse(row["authorizes_listings"])


class SanitizationTests(unittest.TestCase):
    def test_posttimeout_state_is_fixed_and_idempotent(self):
        for value in (
            "NOT_APPLICABLE","OBSERVED_LATE_RESPONSE","NO_RESPONSE_IN_WINDOW",
            "SKIPPED_CLICK_NOT_PROVEN","SKIPPED_REQUEST_NOT_UNIQUE",
            "SKIPPED_ALREADY_RESPONDED","SKIPPED_RESTRICTED","OBSERVER_ERROR",
        ):
            safe=sanitize_precollection({"posttimeout_passive_observation":value})
            self.assertEqual(safe["posttimeout_passive_observation"],value)
            self.assertEqual(sanitize_precollection(safe),safe)
            self.assertFalse(safe["authorizes_listings"])

    def test_malicious_observer_exception_not_exported(self):
        result=sanitize_precollection({
            "posttimeout_passive_observation":"PRIVATE_WEB_TOKEN",
            "raw_response":"PRIVATE_SELLER",
            "status":"PRECOLLECTION_READY_REVIEW",
            "authorizes_listings":True,
        })
        self.assertEqual(result["posttimeout_passive_observation"],
                         "NOT_APPLICABLE")
        self.assertNotIn("PRIVATE",json.dumps(result))
        self.assertFalse(result["authorizes_listings"])


if __name__=="__main__":
    unittest.main()
