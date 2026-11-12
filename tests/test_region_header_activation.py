# -*- coding: utf-8 -*-
"""Offline regression: early region-header failure not mistaken for API readiness."""
from __future__ import annotations

import inspect
import json
import unittest
from unittest.mock import AsyncMock

from app_v5.region_header_activation import (
    HeaderActivationWitness, sanitize_header_activation,
)
from app_v5.region_picker_phases import (
    RegionPickerPhaseWitness, sanitize_picker_phases,
)
from scripts.chrome_stable_input_compare import sanitize_attempt
from daangn_v4_1_core import BY_KEY, ui_select_region


class FailClickButton:
    @property
    def first(self):
        return self
    async def click(self, **kwargs):
        raise TimeoutError("PRIVATE_HOST_INSTANCE_NAME")


class ClickButton:
    @property
    def first(self):
        return self
    async def click(self, **kwargs):
        return None


class FakePage:
    url = "https://www.daangn.com/kr/search/buy-sell/"
    def __init__(self, button):
        self.button=button
    def get_by_role(self, *a, **kw):
        return self.button
    async def wait_for_timeout(self,ms):
        return None
    def locator(self,*args,**kw):
        class Inputs:
            async def count(self):
                return 0
        return Inputs()


class HeaderActivationCoreStageTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_playwright_button_click_reports_exact_preclick_stage(self):
        page=FakePage(FailClickButton())
        callback=AsyncMock()
        step=await ui_select_region(page,BY_KEY["cheonan"],
                                    on_after_open=callback)
        self.assertEqual(step["progress_stage"],"BEFORE_REGION_BUTTON_CLICK")
        self.assertFalse(step["clicked_region_button"])
        self.assertEqual(step["error"],"TimeoutError")
        callback.assert_not_awaited()

    async def test_completed_click_reaches_after_open_observer(self):
        step=await ui_select_region(FakePage(ClickButton()),BY_KEY["cheonan"],
                                     on_after_open=AsyncMock())
        self.assertEqual(step["progress_stage"],"AFTER_OPEN_CALLBACK")
        self.assertTrue(step["clicked_region_button"])
        self.assertEqual(step["error"],"region_input_not_found")

    async def test_header_witness_works_with_predefined_synthetic_page(self):
        class Page:
            def __init__(self):
                self.calls=[]
            async def evaluate(self,script):
                self.calls.append(script)
                if "return true;" in script:
                    return True
                if "return document[key]?.snapshot?.()" in script:
                    return {
                        "armed":True,"header_candidates":1,
                        "header_visible":1,"header_enabled":1,
                        "counts":{"POINTERDOWN":1,"POINTERUP":1,
                                  "MOUSEDOWN":1,"MOUSEUP":1,"CLICK":1},
                        "trusted":{"POINTERDOWN":1,"POINTERUP":1,
                                   "MOUSEDOWN":1,"MOUSEUP":1,"CLICK":1},
                        "private_label":"MY_PRIVATE_REGION",
                    }
                return True
        page=Page()
        probe=HeaderActivationWitness()
        self.assertTrue(await probe.arm(page))
        safe=await probe.sample(page)
        self.assertEqual(safe["trusted"]["CLICK"],1)
        self.assertEqual(safe["header_candidates"],1)
        self.assertFalse(safe["authorizes_listings"])
        self.assertNotIn("MY_PRIVATE",json.dumps(safe))
        await probe.stop(page)
        self.assertFalse(probe.armed)

    async def test_not_armed_or_page_closing_never_exports_exception(self):
        class Page:
            async def evaluate(self,script):
                raise ValueError("PRIVATE_BROWSER_SESSION")
        probe=HeaderActivationWitness()
        self.assertFalse(await probe.arm(Page()))
        safe=await probe.sample(Page())
        self.assertFalse(safe["armed"])
        self.assertNotIn("PRIVATE",json.dumps(safe))


class HeaderActivationSanitizerTests(unittest.TestCase):
    def test_immutable_summary_never_serializes_event_target_details(self):
        raw={
            "armed":True,"header_candidates":1,
            "header_visible":True, "header_enabled":100,
            "counts":{"CLICK":True, "POINTERDOWN":2, "secret":"KEY"},
            "trusted":{"CLICK":1, "POINTERDOWN":200, "secret":"VALUE"},
            "raw_region":"PRIVATE_HOME_DONG",
            "url":"https://private.example/",
            "ip":"203.0.113.8",
        }
        result=sanitize_header_activation(raw)
        self.assertTrue(result["armed"])
        self.assertEqual(result["counts"]["CLICK"],-1)
        self.assertEqual(result["counts"]["POINTERDOWN"],2)
        self.assertEqual(result["trusted"]["CLICK"],1)
        self.assertEqual(result["header_visible"],-1)
        self.assertEqual(sanitize_header_activation(result),result)
        for token in ("PRIVATE","private.example","203.0.113","VALUE"):
            self.assertNotIn(token,json.dumps(result))
        self.assertFalse(result["authorizes_listings"])

    def test_progress_stage_whitelist_and_attempt_idempotence(self):
        fake={
            "step_error":"STEP_EXCEPTION",
            "readiness_state":"NOT_RUN",
            "picker_opened":False,
            "core_progress_stage":"BEFORE_REGION_BUTTON_CLICK",
            "core_header_click_returned":False,
            "header_activation":{"armed":True,"header_candidates":1,
                                 "header_visible":1,"header_enabled":1,
                                 "trusted":{"CLICK":1},"counts":{"CLICK":1}},
            "api":{"state":"NO_TARGET_REQUEST","target_requests":0},
        }
        attempt=sanitize_attempt({
            "mode":"SEQUENTIAL_KEYS",
            "status":"REGION_HEADER_ACTION_EXCEPTION",
            "picker_phase_diagnostics":fake,
            "secret_browser_error":"PRIVATE_CHROME_PROFILE",
        })
        self.assertEqual(attempt["status"],"REGION_HEADER_ACTION_EXCEPTION")
        d=attempt["picker_phase_diagnostics"]
        self.assertEqual(d["core_progress_stage"],"BEFORE_REGION_BUTTON_CLICK")
        self.assertEqual(d["header_activation"]["trusted"]["CLICK"],1)
        self.assertFalse(d["core_header_click_returned"])
        self.assertEqual(sanitize_attempt(attempt),attempt)
        self.assertNotIn("PRIVATE",json.dumps(attempt))

    def test_invalid_stage_never_leaks_raw_exception_or_internal_input(self):
        data=sanitize_picker_phases({
            "core_progress_stage":"PRIVATE_EVASION_FLAG",
            "core_header_click_returned":"yes",
            "header_activation":{"armed":True,"raw_html":"SECRET"},
        })
        self.assertEqual(data["core_progress_stage"],"UNOBSERVABLE")
        self.assertFalse(data["core_header_click_returned"])
        self.assertFalse(data["authorizes_listings"])
        self.assertNotIn("SECRET",json.dumps(data))

    def test_no_stealth_browser_mutation_in_header_observer(self):
        script=inspect.getsource(HeaderActivationWitness)
        for forbidden in ("goto(", "fill(", "press(", "click(",
                          "request(", "add_cookies(", "storage_state("):
            self.assertNotIn(forbidden,script)


if __name__ == "__main__":
    unittest.main()
