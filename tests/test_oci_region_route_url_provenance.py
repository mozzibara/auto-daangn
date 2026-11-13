# -*- coding: utf-8 -*-
"""Offline-only region selection URL and correlated server Route provenance."""
from __future__ import annotations

import json
import unittest

import daangn_v4_1_core as core
from app_v5.manual_chrome_region import ManualSearchResponses
from app_v5.region_url_provenance import (
    RegionURLProvenance, classify_page_region,
    sanitize_region_url_provenance,
)
from scripts.chrome_stable_input_compare import sanitize_attempt
from ops.oci.precollection import final_report

REGION=core.BY_KEY["cheonan"]
URL=("https://www.daangn.com/kr/search/buy-sell/?q=HDD")
WITH_REGION=URL+"&in=%EB%B6%88%EB%8B%B9%EB%8F%99-2292"
BAD_REGION=URL+"&in=%EB%B0%B0%EB%B0%A9%EC%9D%8D-2333"
_PRIVATE=("https://private.invalid/token?pass=PRIVATE_SECRET")


class URLClassificationTests(unittest.TestCase):
    def test_exact_public_search_missing_region(self):
        self.assertEqual(classify_page_region(URL,REGION),"MISSING")
        self.assertEqual(classify_page_region(WITH_REGION,REGION),"EXPECTED")
        self.assertEqual(classify_page_region(BAD_REGION,REGION),"OTHER")

    def test_duplicate_region_is_not_accepted_as_expected(self):
        self.assertEqual(classify_page_region(
            WITH_REGION+"&in=%EB%B6%88%EB%8B%B9%EB%8F%99-2292",REGION),
            "INVALID")

    def test_foreign_origin_wrong_path_and_keyword_invalid(self):
        for url in (
            _PRIVATE,
            URL.replace("www.daangn.com","private.invalid"),
            URL.replace("/kr/search/buy-sell/","/kr/buy-sell/"),
            URL.replace("q=HDD","q=SSD"),
            URL.replace("q=HDD","q="),
        ):
            with self.subTest(url=url):
                self.assertEqual(classify_page_region(url,REGION),"INVALID")


class ChronologyTests(unittest.TestCase):
    def test_region_stays_missing_from_pre_option_through_pre_filter(self):
        trace=RegionURLProvenance(REGION)
        for stage in (
            "BEFORE_OPTION_CLICK", "AFTER_OPTION_CLICK",
            "AFTER_CORE_RETURN", "AFTER_SETTLE", "BEFORE_FILTER",
        ):
            trace.checkpoint(stage,URL)
        out=trace.export(
            route_status="ONE_FRESH",
            postclick_route={"request_region":"MISSING",
                             "model":{"search_region":"EXPECTED",
                                      "filter_region":"EXPECTED",
                                      "private_listing":"PRIVATE_TITLE"}})
        self.assertEqual(out["first_observed_missing_stage"],
                         "BEFORE_OPTION_CLICK")
        self.assertEqual(out["fresh_route_request_region"],"MISSING")
        self.assertTrue(all(
            x=="MISSING" for x in out["checkpoints"].values()))
        self.assertFalse(out["authorizes_listings"])
        self.assertEqual(sanitize_region_url_provenance(out),out)
        self.assertNotIn("PRIVATE",json.dumps(out))

    def test_region_added_after_click_then_lost_at_settle(self):
        trace=RegionURLProvenance(REGION)
        trace.checkpoint("BEFORE_OPTION_CLICK",URL)
        trace.checkpoint("AFTER_OPTION_CLICK",WITH_REGION)
        trace.checkpoint("AFTER_CORE_RETURN",WITH_REGION)
        trace.checkpoint("AFTER_SETTLE",URL)
        trace.checkpoint("BEFORE_FILTER",URL)
        out=trace.export(route_status="ONE_FRESH",
                         postclick_route={"request_region":"EXPECTED"})
        self.assertEqual(out["first_observed_missing_stage"],
                         "BEFORE_OPTION_CLICK")
        self.assertEqual(out["checkpoints"]["AFTER_OPTION_CLICK"],"EXPECTED")
        self.assertEqual(out["checkpoints"]["AFTER_SETTLE"],"MISSING")
        self.assertEqual(out["fresh_route_request_region"],"EXPECTED")

    def test_missing_only_after_click(self):
        trace=RegionURLProvenance(REGION)
        trace.checkpoint("BEFORE_OPTION_CLICK",WITH_REGION)
        trace.checkpoint("AFTER_OPTION_CLICK",URL)
        trace.checkpoint("AFTER_CORE_RETURN",URL)
        out=trace.export()
        self.assertEqual(out["first_observed_missing_stage"],
                         "AFTER_OPTION_CLICK")
        self.assertEqual(out["fresh_route_request_region"],"UNOBSERVABLE")

    def test_incomplete_checkpoints_must_be_inconclusive(self):
        trace=RegionURLProvenance(REGION)
        trace.checkpoint("BEFORE_FILTER",URL)
        out=trace.export(route_status="NONE_FRESH",
                         postclick_route={"request_region":"EXPECTED"})
        self.assertEqual(out["first_observed_missing_stage"],"INCONCLUSIVE")
        self.assertEqual(out["fresh_route_request_region"],"UNOBSERVABLE")
        self.assertEqual(out["checkpoints"]["BEFORE_OPTION_CLICK"],
                         "UNOBSERVABLE")

    def test_exact_one_route_is_required_to_reveal_request_region(self):
        for status in ("NONE_FRESH","MULTIPLE_FRESH","UNREADABLE_FRESH"):
            t=RegionURLProvenance(REGION)
            self.assertEqual(
                t.export(route_status=status,
                         postclick_route={"request_region":"EXPECTED"})[
                    "fresh_route_request_region"],
                "UNOBSERVABLE")
        t=RegionURLProvenance(REGION)
        self.assertEqual(t.export(
            route_status="ONE_FRESH",
            postclick_route={"request_region":"OTHER"})[
                "fresh_route_request_region"],"OTHER")


class ExistingBrowserRouteRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_region_comes_from_initiating_browser_request_not_response_url(self):
        """Redirects cannot silently mislabel a response URL as request."""
        class Request:
            resource_type="fetch"
            method="GET"
            def __init__(self,url):self.url=url

        class Response:
            headers={"content-type":"application/json"}
            status=200
            def __init__(self,request,url):
                self.request=request
                self.url=url
                self.body_read_count=0
            async def body(self):
                self.body_read_count+=1
                return json.dumps({
                    "route":{
                        "buySellArticles":[{"title":"PRIVATE_SELLER_TITLE"}],
                        "searchRegion":{"id":"2292","name":"불당동"},
                        "currentFilters":{"regionId":"2292"},
                    }
                }).encode()

        for request_url,response_url,expected in (
            (WITH_REGION,URL,"EXPECTED"),
            (URL,WITH_REGION,"MISSING"),
        ):
            observer=ManualSearchResponses(REGION)
            request=Request(request_url)
            response=Response(request,response_url)
            observer.on_request(request)
            observer.on_response(response)
            await observer.drain()
            self.assertEqual(len(observer.events),1)
            self.assertEqual(observer.events[0]["request_region"],expected)
            self.assertEqual(observer.events[0]["state"],"OBSERVED")
            self.assertEqual(observer.events[0]["model"]["search_region"],
                             "EXPECTED")
            self.assertEqual(response.body_read_count,1)
            self.assertNotIn("PRIVATE",json.dumps(observer.events))

class PrivacyAndOperatorTests(unittest.TestCase):
    def test_sanitizer_drops_extra_unknown_fields_and_injected_approval(self):
        source={
            "checkpoints":{
                "BEFORE_OPTION_CLICK":"EXPECTED",
                "AFTER_OPTION_CLICK":"MISSING",
                "SECRET_CHECKPOINT":"PRIVATE_SECRET",
            },
            "fresh_route_request_region":"PRIVATE_ID",
            "first_observed_missing_stage":"AFTER_OPTION_CLICK",
            "raw_url":_PRIVATE,
            "authorizes_listings":True,
        }
        safe=sanitize_region_url_provenance(source)
        self.assertEqual(safe["fresh_route_request_region"],"UNOBSERVABLE")
        self.assertEqual(safe["first_observed_missing_stage"],
                         "AFTER_OPTION_CLICK")
        self.assertFalse(safe["authorizes_listings"])
        self.assertEqual(sanitize_region_url_provenance(safe),safe)
        self.assertNotIn("PRIVATE",json.dumps(safe))

    def test_nested_attempt_sanitizes_lifecycle(self):
        row=sanitize_attempt({
            "status":"TARGET_REGION_CONFIRMED_DIAGNOSTIC",
            "mode":"FILL",
            "route_status":"ONE_FRESH",
            "server_search":"EXPECTED",
            "server_filter":"EXPECTED",
            "selected_ui":"EXPECTED",
            "region_url_provenance":{
                "checkpoints":{"BEFORE_FILTER":"MISSING"},
                "fresh_route_request_region":"MISSING",
                "raw_url":_PRIVATE,
            },
            "authorizes_listings":True,
            "seller":"PRIVATE_SELLER",
        })
        self.assertEqual(sanitize_attempt(row),row)
        self.assertEqual(row["region_url_provenance"][
            "checkpoints"]["BEFORE_FILTER"],"MISSING")
        self.assertEqual(row["region_url_provenance"][
            "fresh_route_request_region"],"MISSING")
        self.assertFalse(row["authorizes_listings"])
        self.assertNotIn("PRIVATE",json.dumps(row))

    def test_oci_operator_reports_region_route_url_mismatch_no_collection(self):
        row={
            "status":"TARGET_REGION_CONFIRMED_DIAGNOSTIC",
            "mode":"FILL",
            "route_status":"ONE_FRESH",
            "server_search":"EXPECTED",
            "server_filter":"EXPECTED",
            "selected_ui":"EXPECTED",
            "region_url_provenance":{
                "checkpoints":{
                    "BEFORE_OPTION_CLICK":"MISSING",
                    "AFTER_OPTION_CLICK":"MISSING",
                    "AFTER_CORE_RETURN":"MISSING",
                    "AFTER_SETTLE":"MISSING",
                    "BEFORE_FILTER":"MISSING",
                },
                "first_observed_missing_stage":"BEFORE_OPTION_CLICK",
                "fresh_route_request_region":"MISSING",
            },
        }
        out=final_report(row)
        self.assertEqual(out["status"],"STOP_FILTERS_NOT_VERIFIED")
        diag=out["region_diagnostics"]["region_url_provenance"]
        self.assertEqual(diag["first_observed_missing_stage"],
                         "BEFORE_OPTION_CLICK")
        self.assertEqual(diag["fresh_route_request_region"],"MISSING")
        self.assertFalse(out["authorizes_listings"])
        self.assertFalse(out["collection_started"])
        self.assertFalse(out["database_written"])
        # A successful region gate with no supplied filter report retains
        # an empty sanitized precollection dict; it is not approval.
        self.assertEqual(out["precollection"],{})
        self.assertNotIn("PRIVATE",json.dumps(out))

    def test_checkpoint_does_not_retain_raw_url_in_python_state(self):
        t=RegionURLProvenance(REGION)
        t.checkpoint("BEFORE_OPTION_CLICK", URL+"&PRIVATE_PASSWORD=SECRET")
        t.checkpoint("SECRET_CHECKPOINT",_PRIVATE)
        self.assertEqual(t.observations,{"BEFORE_OPTION_CLICK":"MISSING"})
        self.assertNotIn("PRIVATE",json.dumps(t.export()))


if __name__=="__main__":
    unittest.main()
