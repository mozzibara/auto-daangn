# -*- coding: utf-8 -*-
"""Synthetic and offline-only picker readiness/keyword-request phase regression."""
from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock

import daangn_v4_1_core as core
from app_v5.region_picker_phases import (
    RegionPickerPhaseWitness, _is_region_request, phase_error,
    sanitize_phase, sanitize_picker_phases,
)
from scripts.chrome_stable_input_compare import sanitize_attempt


class Request:
    method = "GET"
    resource_type = "fetch"
    def __init__(self, url):
        self.url=url


class Response:
    def __init__(self, request, status):
        self.request=request
        self.status=status


class FakePage:
    def __init__(self, values):
        self.values=values
    async def evaluate(self, js):
        return self.values


class RegionPickerEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_stage_before_later_visible_input_has_bounded_flag(self):
        probe=RegionPickerPhaseWitness(core.BY_KEY["cheonan"])
        await probe.sample(FakePage({
            "inputs":0,"visible_inputs":0,
            "dialog_inputs":0,"visible_dialog_inputs":0,
            "visible_dialogs":4,"region_buttons":1
        }),"AFTER_PICKER_OPEN_500MS")
        await probe.sample(FakePage({
            "inputs":1,"visible_inputs":1,
            "dialog_inputs":1,"visible_dialog_inputs":1,
            "visible_dialogs":4,"region_buttons":1
        }),"AFTER_SETTLE_4200MS")
        report=probe.export(error="region_input_not_found",readiness="NOT_RUN")
        self.assertTrue(report["delayed_input_observed"])
        self.assertEqual(report["step_error"],"REGION_INPUT_NOT_FOUND")
        self.assertEqual(report["readiness_state"],"NOT_RUN")
        self.assertEqual(report["api"]["state"],"NO_TARGET_REQUEST")
        self.assertFalse(report["authorizes_listings"])

    async def test_request_200_and_first_party_exact_target_only(self):
        probe=RegionPickerPhaseWitness(core.BY_KEY["cheonan"])
        url=("https://www.daangn.com/kr/api/v1/regions/keyword"
             "?keyword=%EB%B6%88%EB%8B%B9%EB%8F%99")
        req=Request(url)
        probe.on_request(req)
        probe.on_response(Response(req,200))
        self.assertEqual(probe.export()["api"]["target_requests"],1)
        self.assertEqual(probe.export()["api"]["target_responses_200"],1)
        self.assertEqual(probe.export()["api"]["state"],"RESPONSE_200")
        self.assertNotIn("불당",json.dumps(probe.export(),ensure_ascii=False))

    async def test_network_failure_is_not_claimed_as_api_timeout(self):
        probe=RegionPickerPhaseWitness(core.BY_KEY["cheonan"])
        req=Request("https://www.daangn.com/kr/api/v1/regions/keyword"
                    "?keyword=%EB%B6%88%EB%8B%B9%EB%8F%99")
        probe.on_request(req)
        probe.on_requestfailed(req)
        self.assertEqual(probe.export()["api"]["state"],"REQUEST_FAILED")

    async def test_http_denial_identified_but_raw_response_never_used(self):
        probe=RegionPickerPhaseWitness(core.BY_KEY["cheonan"])
        req=Request("https://www.daangn.com/kr/api/v1/regions/keyword"
                    "?keyword=%EB%B6%88%EB%8B%B9%EB%8F%99")
        probe.on_request(req)
        probe.on_response(Response(req,403))
        self.assertEqual(probe.export()["api"]["state"],"ACCESS_RESTRICTED")
        self.assertFalse(probe.export()["authorizes_listings"])


class RegionPickerSanitizerTests(unittest.TestCase):
    def test_only_known_error_enums_not_exception_messages(self):
        self.assertEqual(phase_error("region_input_not_found"),
                         "REGION_INPUT_NOT_FOUND")
        self.assertEqual(phase_error("region_suggestion_not_ready"),
                         "REGION_SUGGESTION_NOT_READY")
        self.assertEqual(phase_error("TimeoutError"),"STEP_EXCEPTION")
        self.assertEqual(phase_error("private_exception_access_token"),
                         "OTHER_KNOWN_STEP")

    def test_never_publish_full_raw_url_or_region_or_login(self):
        secret={"phases":{"AFTER_PICKER_OPEN_500MS":{
            "inputs":1,"visible_inputs":1,"dialog_inputs":1,
            "visible_dialog_inputs":1,"visible_dialogs":1,
            "region_buttons":1,"focus":"REGION_INPUT",
            "typed_string":"PRIVATE_REGION",
            "html":"<script>ACCESS_SECRET</script>"}},
            "step_error":"PRIVATE_ACCESS_TOKEN",
            "readiness_state":"API_TIMEOUT",
            "api":{"target_requests":1,"target_responses_200":0,
                   "state":"REQUEST_WITHOUT_RESPONSE",
                   "raw_url":"https://private.invalid/listing",
                   "raw_ip":"203.0.113.99"},
            "path":"PRIVATE_HOME"}
        safe=sanitize_picker_phases(secret)
        self.assertEqual(sanitize_picker_phases(safe),safe)
        self.assertEqual(safe["step_error"],"OTHER_KNOWN_STEP")
        self.assertEqual(safe["api"]["state"],"REQUEST_WITHOUT_RESPONSE")
        self.assertEqual(safe["phases"]["AFTER_PICKER_OPEN_500MS"]["inputs"],1)
        for bad in ("ACCESS_SECRET","PRIVATE","203.0.113","private.invalid"):
            self.assertNotIn(bad,json.dumps(safe,ensure_ascii=False))

    def test_no_bool_passes_as_numeric_counter(self):
        data=sanitize_phase({"inputs":True,"visible_inputs":200,
                             "dialog_inputs":3})
        self.assertEqual(data["inputs"],-1)
        self.assertEqual(data["visible_inputs"],-1)
        self.assertEqual(data["dialog_inputs"],3)

    def test_exact_host_and_path_required(self):
        path="https://www.daangn.com/kr/api/v1/regions/keyword"
        self.assertEqual(_is_region_request(path,"불당동"),
                         "missing_keyword_requests")
        self.assertEqual(_is_region_request(path+"?keyword=PRIVATE","불당동"),
                         "other_keyword_requests")
        self.assertIsNone(_is_region_request(
            "https://example.com/kr/api/v1/regions/keyword?keyword=XXX",
            "불당동"))
        self.assertIsNone(_is_region_request(
            "https://www.daangn.com/kr/buy-sell/listing","불당동"))
        self.assertIsNone(_is_region_request(
            "https://www.daangn.com:444/kr/api/v1/regions/keyword",
            "불당동"))

    def test_attempt_report_fail_closed_and_idempotent(self):
        report=sanitize_attempt({
            "mode":"FILL","status":"API_OR_DOM_NOT_READY",
            "picker_phase_diagnostics":{
                "step_error":"REGION_INPUT_NOT_FOUND",
                "readiness_state":"NOT_RUN",
                "api":{"state":"NO_TARGET_REQUEST",
                       "target_requests":0},
                "delayed_input_observed":True,
                "raw_region":"SENSITIVE_HOME"},
        })
        self.assertTrue(report["picker_phase_diagnostics"][
            "delayed_input_observed"])
        self.assertEqual(sanitize_attempt(report),report)
        self.assertNotIn("SENSITIVE_HOME",json.dumps(report))


class CoreHookTests(unittest.IsolatedAsyncioTestCase):
    async def test_core_after_open_runs_before_input_count(self):
        events=[]
        class Button:
            @property
            def first(self):
                return self
            async def click(self, **kw):
                events.append("CLICK")
        class Inputs:
            async def count(self):
                events.append("COUNT_INPUTS")
                return 0
        class Page:
            url="https://www.daangn.com/kr/search/buy-sell/?q=HDD"
            def get_by_role(self,*a,**kw):
                return Button()
            def locator(self,*a,**kw):
                return Inputs()
            async def wait_for_timeout(self, ms):
                events.append("WAIT")
        async def on_open():
            events.append("OBSERVE_AFTER_OPEN")
        steps=await core.ui_select_region(
            Page(),core.BY_KEY["cheonan"],on_after_open=on_open)
        self.assertEqual(steps["error"],"region_input_not_found")
        self.assertEqual(events,[
            "CLICK","WAIT","OBSERVE_AFTER_OPEN","COUNT_INPUTS"])


if __name__=="__main__":
    unittest.main()
