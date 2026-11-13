# -*- coding: utf-8 -*-
"""Offline-only causal boundary for when the public region URL loses 'in'.

No live site calls; testing one native Apply action using synthetic event data.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

import daangn_browser_v4_6 as v46
from app_v5.precollection_filter_gate import (
    classify_filter_url, sanitize_region_url_timeline,
    summarize_region_url_timeline, sanitize_precollection,
    verify_filter_before_collection, _REGION_URL_TIMELINE_STAGES,
)

ROOT="https://www.daangn.com/kr/search/buy-sell/"
REGION_QUERY="q=HDD&in=%EB%B6%88%EB%8B%B9%EB%8F%99-2292"
WITHOUT_REGION_QUERY="q=HDD"
WITH_REGION=ROOT+"?"+REGION_QUERY
WITHOUT_REGION=ROOT+"?"+WITHOUT_REGION_QUERY
ALL_FILTERS="&category_id=1&price=__50000&only_on_sale=true"
FULL=WITH_REGION+ALL_FILTERS
REGIONLESS=WITHOUT_REGION+ALL_FILTERS
BEFORE={"complete":True,"category":True,"available":True,
        "maximum":50000,"minimum":0}
EVENTS=("POINTERDOWN","POINTERUP","MOUSEDOWN","MOUSEUP","CLICK")


class SyntheticPage:
    def __init__(self,initial=WITH_REGION):
        self.url=initial
        self.hooks={}
        self.clicks=0
    def on(self,event,cb):
        self.hooks.setdefault(event,[]).append(cb)
    def remove_listener(self,event,cb):
        self.hooks[event].remove(cb)
    async def evaluate(self,script):
        return {"armed":True,
                "counts":{k:1 for k in EVENTS},
                "trusted":{k:1 for k in EVENTS}}
    async def wait_for_timeout(self,ms):
        return None


class SyntheticButton:
    def __init__(self,page,*,url_after=REGIONLESS,throw=False):
        self.page=page
        self.url_after=url_after
        self.throw=throw
        self.calls=0
    async def is_enabled(self):
        return True
    async def evaluate(self,script):
        return True
    async def click(self,**kw):
        self.calls+=1
        self.page.clicks+=1
        self.page.url=self.url_after
        if self.throw:
            raise PlaywrightTimeoutError("PRIVATE_ACTION_ERROR")


class TimelineTests(unittest.TestCase):
    def test_first_missing_exact_stage_and_enums_only(self):
        values={
            "BEFORE_OPEN_FILTER":classify_filter_url(WITH_REGION),
            "AFTER_OPEN_FILTER":classify_filter_url(WITH_REGION),
            "AFTER_CATEGORY":classify_filter_url(WITHOUT_REGION),
            "AFTER_AVAILABLE":classify_filter_url(WITHOUT_REGION),
        }
        safe=summarize_region_url_timeline(values)
        self.assertEqual(safe["first_missing_stage"],"AFTER_CATEGORY")
        self.assertEqual(safe["stage_region"]["AFTER_OPEN_FILTER"],"EXPECTED")
        self.assertEqual(safe["stage_region"]["AFTER_CATEGORY"],"MISSING")
        self.assertFalse(safe["authorizes_listings"])
        self.assertEqual(sanitize_region_url_timeline(safe),safe)

    def test_missing_at_entry_is_not_blindly_attributed_to_apply(self):
        v=summarize_region_url_timeline({
            "BEFORE_OPEN_FILTER":classify_filter_url(WITHOUT_REGION),
            "AT_REPORT_SNAPSHOT":classify_filter_url(REGIONLESS),
        })
        self.assertEqual(v["first_missing_stage"],"BEFORE_OPEN_FILTER")

    def test_no_missing_observed_does_not_mean_server_filters_verified(self):
        v=summarize_region_url_timeline({
            stage:classify_filter_url(WITH_REGION)
            for stage in _REGION_URL_TIMELINE_STAGES
        })
        self.assertEqual(v["first_missing_stage"],"NOT_OBSERVED")
        self.assertTrue(all(
            state=="EXPECTED" for state in v["stage_region"].values()))
        self.assertFalse(v["authorizes_listings"])

    def test_ambiguous_before_missing_does_not_claim_causal_stage(self):
        bad=WITH_REGION+"&in=PRIVATE_REGION"
        v=summarize_region_url_timeline({
            "BEFORE_OPEN_FILTER":classify_filter_url(WITH_REGION),
            "AFTER_OPEN_FILTER":classify_filter_url(bad),
            "AFTER_CATEGORY":classify_filter_url(WITHOUT_REGION),
        })
        self.assertEqual(v["first_missing_stage"],"INCONCLUSIVE")

    def test_missing_observation_cannot_infer_when_it_was_lost(self):
        v=summarize_region_url_timeline({
            "AFTER_CATEGORY":classify_filter_url(WITHOUT_REGION)
        })
        self.assertEqual(v["first_missing_stage"],"INCONCLUSIVE")

    def test_sanitizer_never_copies_url_raw_fields_or_private_keys(self):
        raw={
            "stage_region":{
                "BEFORE_OPEN_FILTER":"EXPECTED",
                "AFTER_CATEGORY":"MISSING",
                "PRIVATE_TIMING":"PRIVATE_123",
            },
            "first_missing_stage":"AFTER_CATEGORY",
            "raw_url":"https://private.invalid/SECRET",
            "authorizes_listings":True,
        }
        safe=sanitize_region_url_timeline(raw)
        self.assertEqual(sanitize_region_url_timeline(safe),safe)
        self.assertFalse(safe["authorizes_listings"])
        self.assertNotIn("PRIVATE",json.dumps(safe))
        self.assertNotIn("SECRET",json.dumps(safe))


class FullOperatorTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self,*,first_missing="AFTER_OPEN_FILTER",
                   initial=WITH_REGION,timeout=False):
        page=SyntheticPage(initial)
        btn=SyntheticButton(page,url_after=REGIONLESS,throw=timeout)

        async def select(*a,**kw):
            callback=kw["on_diagnostic_checkpoint"]
            for stage in (
                "BEFORE_OPEN_FILTER","AFTER_OPEN_FILTER",
                "AFTER_CATEGORY","AFTER_AVAILABLE",
                "AFTER_MAX_FILL","AFTER_MAX_TAB","BEFORE_APPLY",
            ):
                if stage==first_missing:
                    page.url=WITHOUT_REGION
                callback(stage,page)
            return btn,BEFORE

        async def forbidden_check(*a):
            raise AssertionError("Never reopen UI when strict URL is missing")
        with (
            patch("app_v5.precollection_filter_gate.v46.set_filter",select),
            patch("app_v5.precollection_filter_gate.v46.check_after",
                  forbidden_check),
        ):
            row=await verify_filter_before_collection(page)
        return page,btn,row

    async def test_loss_at_filter_open_is_retained_without_retries(self):
        page,btn,row=await self._run(first_missing="AFTER_OPEN_FILTER")
        self.assertEqual(row["status"],"BLOCKED_FILTER_URL")
        self.assertEqual(row["region_url_timeline"]["first_missing_stage"],
                         "AFTER_OPEN_FILTER")
        self.assertEqual(row["region_url_timeline"]["stage_region"][
            "BEFORE_OPEN_FILTER"],"EXPECTED")
        self.assertEqual(row["region_url_timeline"]["stage_region"][
            "AFTER_OPEN_FILTER"],"MISSING")
        self.assertEqual(btn.calls,1)
        self.assertFalse(row["authorizes_listings"])
        self.assertFalse(row["collection_started"])
        self.assertFalse(row["database_written"])

    async def test_loss_at_apply_return_is_precisely_attributed(self):
        page,btn,row=await self._run(first_missing=None)
        self.assertEqual(row["status"],"BLOCKED_FILTER_URL")
        self.assertEqual(row["region_url_timeline"]["first_missing_stage"],
                         "AFTER_CLICK_RETURN")
        self.assertEqual(row["region_url_timeline"]["stage_region"][
            "BEFORE_APPLY"],"EXPECTED")
        self.assertEqual(row["region_url_timeline"]["stage_region"][
            "AFTER_CLICK_RETURN"],"MISSING")
        self.assertEqual(btn.calls,1)

    async def test_region_missing_even_before_filter_open(self):
        page,btn,row=await self._run(initial=WITHOUT_REGION,
                                     first_missing=None)
        self.assertEqual(row["region_url_timeline"]["first_missing_stage"],
                         "BEFORE_OPEN_FILTER")
        self.assertEqual(btn.calls,1)
        self.assertFalse(row["strict_filter_evidence"])

    async def test_timeout_does_not_infer_completed_apply(self):
        page,btn,row=await self._run(first_missing=None,timeout=True)
        self.assertEqual(row["status"],"BLOCKED_APPLY_ACTION")
        self.assertEqual(row["apply_action_exception_kind"],
                         "PLAYWRIGHT_TIMEOUT")
        self.assertEqual(row["region_url_timeline"]["first_missing_stage"],
                         "AT_REPORT_SNAPSHOT")
        self.assertEqual(row["region_url_timeline"]["stage_region"][
            "AFTER_CLICK_RETURN"],"UNOBSERVABLE")
        self.assertEqual(btn.calls,1)
        self.assertFalse(row["filter_apply_returned"])
        self.assertFalse(row["authorizes_listings"])

    async def test_producer_sanitizer_prevents_fake_listing_admission(self):
        safe=sanitize_precollection({
            "region_url_timeline":{
                "first_missing_stage":"AFTER_AVAILABLE",
                "stage_region":{
                    "AFTER_AVAILABLE":"MISSING",
                    "raw_url":"https://private.invalid/COOKIE",
                },
            },
            "raw_listing":{"title":"PRIVATE_SELLER"},
            "authorizes_listings":True,
            "collection_started":True,
        })
        self.assertEqual(sanitize_precollection(safe),safe)
        self.assertEqual(safe["region_url_timeline"][
            "first_missing_stage"],"AFTER_AVAILABLE")
        self.assertNotIn("PRIVATE",json.dumps(safe))
        self.assertFalse(safe["authorizes_listings"])
        self.assertFalse(safe["collection_started"])


class NativeFilterHookTests(unittest.IsolatedAsyncioTestCase):
    async def test_hook_called_in_order_without_extra_click(self):
        urlpage=SyntheticPage()
        calls=[]
        class Locator:
            def __init__(self):
                self.press_count=0
                self.fill_count=0
                self.first=self
            async def count(self):return 1
            async def is_enabled(self):return True
            async def fill(self,value,**kw):self.fill_count+=1
            async def press(self,key,**kw):self.press_count+=1
        max_price=Locator()
        class FilterPage(SyntheticPage):
            def get_by_role(self,role,name,exact=False):
                return Locator()
        page=FilterPage()
        async def noop_open(page):return None
        async def fake_controls(page,args):
            return object(),object(),max_price,None
        async def set_label(page,field,label,steps,desired=True):
            return None
        async def fake_state(page,args):
            return BEFORE
        async def witness(stage,page):
            calls.append(stage)
        with (
            patch("daangn_browser_v4_6.open_filter",noop_open),
            patch("daangn_browser_v4_6.controls",fake_controls),
            patch("daangn_browser_v4_6.set_checked_by_label",set_label),
            patch("daangn_browser_v4_6.ui_state",fake_state),
        ):
            button,state=await v46.set_filter(
                page,SimpleNamespace(
                    category_name="디지털기기", category_id=1,
                    available_only=True,max_price=50000,min_price=0
                ),[],on_diagnostic_checkpoint=witness)
        self.assertEqual(calls,[
            "BEFORE_OPEN_FILTER","AFTER_OPEN_FILTER","AFTER_CATEGORY",
            "AFTER_AVAILABLE","AFTER_MAX_FILL","AFTER_MAX_TAB",
            "BEFORE_APPLY"])
        self.assertEqual(max_price.fill_count,1)
        self.assertEqual(max_price.press_count,1)
        self.assertEqual(page.clicks,0)
        self.assertTrue(state["complete"])


if __name__=="__main__":
    unittest.main()
