# -*- coding: utf-8 -*-
"""No marketplace calls: OCI FILL operational precollection and admission regression."""
from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from app_v5.precollection_filter_gate import (
    REGION, PassiveFilteredRoute, _find_search_model, _unique_query,
    inspect_filtered_response, sanitize_precollection,
    verify_filter_before_collection,
)
from ops.oci.precollection import (
    _APPROVAL, blocked, final_report, isolated_execution_directory, run, main,
)
from scripts.chrome_stable_input_compare import (
    one_public_region, sanitize_attempt,
)

TARGET_URL=(
    "https://www.daangn.com/kr/search/buy-sell/"
    "?q=HDD&in=%EB%B6%88%EB%8B%B9%EB%8F%99-2292"
    "&category_id=1&price=__50000&only_on_sale=true"
)


def payload(*, max_key="maxPrice", price=50000, category=1,
            region="2292", availability=True):
    return json.dumps({
        "route":{"searchRegion":{"id":region},
                 "currentFilters":{
                     "regionId":region,"categoryId":category,
                     "onlyOnSale":availability,max_key:price},
                 "buySellArticles":[
                     {"url":"https://private.invalid/item/PRIVATE_TITLE",
                      "title":"DO_NOT_EXPORT","price":1290000},
                     {"seller_phone":"PRIVATE_PHONE","user_id":"PRIVATE_ID"},
                 ]}},ensure_ascii=False).encode("utf-8")


class Response:
    def __init__(self, request, status=200, body=None):
        self.request=request
        self.url=request.url
        self.status=status
        self.headers={"content-type":"application/json"}
        self._body=body if body is not None else payload()
    async def body(self):
        return self._body


class Request:
    method="GET"
    resource_type="fetch"
    def __init__(self,url=TARGET_URL):
        self.url=url


class GateParsingTests(unittest.TestCase):
    def test_exact_known_query_required_no_duplicates_or_extra_tokens(self):
        self.assertTrue(_unique_query(TARGET_URL))
        for bad in (
            TARGET_URL+"&price=__50000",
            TARGET_URL+"&token=secret",
            TARGET_URL.replace("price=__50000","price=__25000"),
            TARGET_URL.replace("only_on_sale=true","only_on_sale=false"),
            TARGET_URL.replace("category_id=1","category_id=2"),
            TARGET_URL.replace("HDD","SSD"),
            TARGET_URL.replace("2292","2333"),
            TARGET_URL.replace("www.daangn.com","example.com"),
        ):
            self.assertFalse(_unique_query(bad),bad)
    def test_metadata_fields_only_not_any_listing_contents(self):
        raw=payload()
        self.assertEqual(inspect_filtered_response(raw),{
            "region":"EXPECTED","category":"EXPECTED",
            "price_max":"EXPECTED","available":"EXPECTED"})
        self.assertNotIn("PRIVATE",json.dumps(inspect_filtered_response(raw)))
        parsed=_find_search_model(raw)
        self.assertEqual(len(parsed),2)
        self.assertNotIn("buySellArticles",parsed[1])
    def test_missing_price_is_not_url_enforcement(self):
        raw=json.loads(payload())
        raw["route"]["currentFilters"].pop("maxPrice")
        safe=inspect_filtered_response(json.dumps(raw).encode("utf-8"))
        self.assertEqual(safe["price_max"],"MISSING")
    def test_conflicting_or_unknown_metadata_fails_closed(self):
        self.assertEqual(inspect_filtered_response(payload(price=123))["price_max"],"OTHER")
        self.assertEqual(inspect_filtered_response(payload(region="2333"))["region"],"OTHER")
        self.assertEqual(inspect_filtered_response(payload(availability=False))["available"],"OTHER")
        raw=json.loads(payload())
        raw["route"]["currentFilters"]["priceMax"]=50000
        self.assertEqual(inspect_filtered_response(json.dumps(raw).encode())["price_max"],"AMBIGUOUS")
    def test_malformed_and_multiple_models_fail_closed(self):
        for value in (b"",b"{oops}",b"[]" ,b"x"*2_000_001):
            self.assertEqual(inspect_filtered_response(value)["region"],"MISSING")
        raw=json.loads(payload())
        raw["extra"]=raw["route"]
        self.assertEqual(inspect_filtered_response(json.dumps(raw).encode())["region"],"MISSING")
    def test_report_sanitization_idempotent_and_never_exports_listing_fields(self):
        safe=sanitize_precollection({
            "status":"PRECOLLECTION_READY_REVIEW",
            "region_gate_confirmed":True,
            "strict_filter_evidence":True,
            "filtered_route_count":1,
            "server_filters":{"region":"EXPECTED","category":"EXPECTED",
                              "price_max":"EXPECTED","available":"EXPECTED"},
            "raw_listing_url":"https://private.invalid/item",
            "seller":"PRIVATE_SELLER",
            "collection_started":True,
            "authorizes_listings":True,
        })
        self.assertEqual(sanitize_precollection(safe),safe)
        self.assertFalse(safe["collection_started"])
        self.assertFalse(safe["authorizes_listings"])
        self.assertNotIn("PRIVATE",json.dumps(safe))
        self.assertNotIn("private.invalid",json.dumps(safe))


class RouteWitnessTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_request_seen_in_same_apply_window(self):
        witness=PassiveFilteredRoute()
        req=Request()
        witness.on_response(Response(req))
        self.assertEqual(witness.observed,0)
        witness.on_request(req)
        witness.on_response(Response(req))
        await witness.drain()
        self.assertEqual(witness.observed,1)
        self.assertEqual(witness.events[0]["price_max"],"EXPECTED")
        self.assertEqual(witness.starts,set())
    async def test_denial_blocks_without_fetching_body(self):
        witness=PassiveFilteredRoute()
        request=Request()
        witness.on_request(request)
        witness.on_response(Response(request,status=403))
        self.assertTrue(witness.restricted)
        self.assertEqual(witness.events,[])
        self.assertEqual(witness.observed,1)
    async def test_wrong_query_is_never_tracked(self):
        witness=PassiveFilteredRoute()
        req=Request(TARGET_URL.replace("HDD","SSD"))
        witness.on_request(req)
        witness.on_response(Response(req))
        await witness.drain()
        self.assertEqual(witness.observed,0)


class FakeButton:
    def __init__(self,page,error=None):
        self.page=page
        self.error=error
    async def is_enabled(self):
        return True
    async def click(self,**kwargs):
        if self.error:
            raise self.error
        self.page.url=TARGET_URL
        req=Request()
        for fn in self.page.hooks.get("request",[]):
            fn(req)
        response=Response(req)
        for fn in self.page.hooks.get("response",[]):
            fn(response)


class FakePage:
    def __init__(self,error=None):
        self.url="https://www.daangn.com/kr/search/buy-sell/?q=HDD&in=불당동-2292"
        self.button=FakeButton(self,error)
        self.hooks={}
    def on(self,key,callback):
        self.hooks.setdefault(key,[]).append(callback)
    def remove_listener(self,key,callback):
        self.hooks[key].remove(callback)
    async def wait_for_timeout(self,ms):
        return None


BEFORE={"complete":True,"category":True,"available":True,
        "maximum":50000,"minimum":0}
AFTER={**BEFORE,"observation_status":"OBSERVED_MATCH"}


class EndToEndNoCollectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_apply_metadata_ui_and_url_before_collection(self):
        page=FakePage()
        async def select(*a):
            return page.button,BEFORE
        async def check(*a):
            return AFTER
        with patch("app_v5.precollection_filter_gate.v46.set_filter",select),\
             patch("app_v5.precollection_filter_gate.v46.check_after",check):
            result=await verify_filter_before_collection(page)
        self.assertEqual(result["status"],"PRECOLLECTION_READY_REVIEW")
        self.assertTrue(result["strict_filter_evidence"])
        self.assertTrue(result["ui_selected_after_apply"])
        self.assertTrue(result["filtered_url_matches"])
        self.assertFalse(result["collection_started"])
        self.assertFalse(page.hooks["response"])
        self.assertFalse(page.hooks["request"])

    async def test_apply_error_stops_even_with_valid_preselected_controls(self):
        page=FakePage(error=RuntimeError("PRIVATE_ACTION"))
        async def select(*a):
            return page.button,BEFORE
        with patch("app_v5.precollection_filter_gate.v46.set_filter",select):
            result=await verify_filter_before_collection(page)
        self.assertEqual(result["status"],"BLOCKED_APPLY_ACTION")
        self.assertFalse(result["filter_apply_returned"])
        self.assertFalse(result["collection_started"])

    async def test_wrong_region_precondition_never_opens_filter(self):
        page=FakePage()
        called=False
        async def should_never(*args):
            nonlocal called
            called=True
        with patch("app_v5.precollection_filter_gate.v46.set_filter",should_never):
            result=await verify_filter_before_collection(
                page,region={"term":"OTHER"})
        self.assertFalse(called)
        self.assertEqual(result["status"],"BLOCKED_PRECONDITION")


class OperatorGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_wrong_approval_root_or_robots_never_launches(self):
        attempts=0
        async def diag():
            nonlocal attempts
            attempts+=1
            return {}
        for kwargs in (
            dict(approve="WRONG",live=True,headed=True,
                 directory_check=lambda:True, robots=lambda:True),
            dict(approve=_APPROVAL,live=True,headed=False,
                 directory_check=lambda:True, robots=lambda:True),
            dict(approve=_APPROVAL,live=True,headed=True,
                 directory_check=lambda:False, robots=lambda:True),
            dict(approve=_APPROVAL,live=True,headed=True,
                 directory_check=lambda:True, robots=lambda:False),
        ):
            report=await run(**kwargs, picker_robots=lambda term:{"allowed":True},
                             diagnostic=diag)
            self.assertNotEqual(report["status"],"PRECOLLECTION_EVIDENCE_COMPLETE")
        self.assertEqual(attempts,0)

    async def test_only_confirmed_region_and_all_filters_pass(self):
        async def diagnostic():
            return {
                "status":"TARGET_REGION_CONFIRMED_DIAGNOSTIC",
                "precollection":{
                    "status":"PRECOLLECTION_READY_REVIEW",
                    "strict_filter_evidence":True,
                    "server_filters":{"region":"EXPECTED",
                                      "category":"EXPECTED",
                                      "price_max":"EXPECTED",
                                      "available":"EXPECTED"},
                },
            }
        result=await run(
            approve=_APPROVAL,live=True,headed=True,
            directory_check=lambda:True,robots=lambda:True,
            picker_robots=lambda term:{"allowed":True},
            diagnostic=diagnostic)
        self.assertEqual(result["status"],"PRECOLLECTION_EVIDENCE_COMPLETE")
        self.assertFalse(result["authorizes_listings"])
        self.assertFalse(result["collection_started"])

    async def test_region_alone_does_not_pass_filters(self):
        for row in (
            {"status":"TARGET_REGION_CONFIRMED_DIAGNOSTIC"},
            {"status":"TARGET_REGION_CONFIRMED_DIAGNOSTIC",
             "precollection":{"status":"BLOCKED_FILTER_ROUTE_METADATA"}},
            {"status":"REGION_NOT_COMMITTED",
             "precollection":{"status":"PRECOLLECTION_READY_REVIEW",
                              "strict_filter_evidence":True}},
        ):
            self.assertNotEqual(final_report(row)["status"],
                                "PRECOLLECTION_EVIDENCE_COMPLETE")

    async def test_final_output_resanitizes_nested_report(self):
        result=final_report({
            "status":"TARGET_REGION_CONFIRMED_DIAGNOSTIC",
            "precollection":{
                "status":"PRECOLLECTION_READY_REVIEW",
                "strict_filter_evidence":True,
                "cookie":"SUPER_SECRET",
                "authorizes_listings":True,
            },
        })
        self.assertNotIn("SUPER_SECRET",json.dumps(result))
        self.assertFalse(result["precollection"]["authorizes_listings"])

    async def test_one_public_region_accepts_optional_same_page_hook(self):
        src=inspect.getsource(one_public_region)
        self.assertIn('status == "TARGET_REGION_CONFIRMED_DIAGNOSTIC"',src)
        self.assertIn("on_region_confirmed(page, region)",src)
        self.assertIn('row["precollection"] = candidate',src)
        self.assertNotIn("goto(listing",src)

    async def test_default_cli_is_network_inert(self):
        with patch("builtins.print") as output:
            self.assertEqual(main([]),2)
            self.assertEqual(main(["--live"]),2)
        self.assertTrue(output.called)


class EnvironmentGuards(unittest.TestCase):
    def test_operator_cwd_must_be_own_isolated_clone(self):
        # Root execution cannot be allowed by supplying a forged cwd.
        with patch("ops.oci.precollection.os.geteuid",return_value=1000):
            self.assertTrue(isolated_execution_directory(
                "/home/ubuntu/code/auto-daangn-region-diagnostic",
                home="/home/ubuntu"))
            self.assertFalse(isolated_execution_directory(
                "/opt/auto-daangn-public-stage",home="/home/ubuntu"))
            self.assertFalse(isolated_execution_directory(
                "/home/ubuntu/code/auto-daangn",home="/home/ubuntu"))
            self.assertFalse(isolated_execution_directory(
                "/var/lib/auto-daangn",home="/home/ubuntu"))
        with patch("ops.oci.precollection.os.geteuid",return_value=0):
            self.assertFalse(isolated_execution_directory(
                "/home/ubuntu/code/auto-daangn-region-diagnostic",
                home="/home/ubuntu"))


if __name__ == "__main__":
    unittest.main()
