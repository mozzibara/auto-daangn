# -*- coding: utf-8 -*-
"""Offline-only fail-closed proof of one delivered click and zero re-clicks."""
from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app_v5.region_header_activation import (
    verify_header_click_timeout_without_reclick,
)
from app_v5.region_picker_phases import sanitize_picker_phases
from daangn_v4_1_core import BY_KEY, ui_select_region
from scripts.chrome_stable_input_compare import sanitize_attempt


def one_click_snapshot(*, trusted=1, raw=1, visible=1):
    event_names=("POINTERDOWN","POINTERUP","MOUSEDOWN","MOUSEUP","CLICK")
    return {
        "armed":True, "header_candidates":1, "header_visible":visible,
        "header_enabled":visible,
        "counts":{k:raw for k in event_names},
        "trusted":{k:trusted for k in event_names},
        "authorizes_listings":False,
    }


class FakeWitness:
    armed=True
    def __init__(self, data):
        self.data=data
    async def sample(self, page):
        return self.data


class FakeGatePage:
    def __init__(self, *, one_input=True, empty=True):
        self.calls=0
        self.one_input=one_input
        self.empty=empty
    async def evaluate(self, script):
        self.calls+=1
        return {
            "one_visible_region_input":self.one_input,
            "one_empty_enabled_dialog_input":self.empty,
            "raw_input":"MY_PRIVATE_SEARCH",
        }


class GateTests(unittest.IsolatedAsyncioTestCase):
    async def test_exactly_one_trusted_header_click_and_empty_input_allows(self):
        page=FakeGatePage()
        witness=FakeWitness(one_click_snapshot())
        self.assertTrue(await verify_header_click_timeout_without_reclick(
            page,witness))
        self.assertEqual(page.calls,1)

    async def test_untrusted_duplicate_missing_or_unarmed_fails_closed(self):
        for snapshot in (one_click_snapshot(trusted=0),
                         one_click_snapshot(trusted=2,raw=2),
                         one_click_snapshot(visible=0),
                         one_click_snapshot(raw=2),
                         {**one_click_snapshot(),"armed":False}):
            page=FakeGatePage()
            self.assertFalse(await verify_header_click_timeout_without_reclick(
                page,FakeWitness(snapshot)))
            self.assertEqual(page.calls,0)
        witness=FakeWitness(one_click_snapshot())
        witness.armed=False
        self.assertFalse(await verify_header_click_timeout_without_reclick(
            FakeGatePage(),witness))

    async def test_unready_hidden_or_nonempty_dialog_blocks(self):
        for one_input,empty in ((False,True),(True,False),(False,False)):
            self.assertFalse(await verify_header_click_timeout_without_reclick(
                FakeGatePage(one_input=one_input,empty=empty),
                FakeWitness(one_click_snapshot())))

    async def test_page_error_never_allows_continuation(self):
        class Page:
            async def evaluate(self,script):
                raise ValueError("SECRET_BROWSER_TOKEN")
        self.assertFalse(await verify_header_click_timeout_without_reclick(
            Page(),FakeWitness(one_click_snapshot())))


class CoreRecoveredClickTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_one_click_dispatched_even_after_timeout(self):
        class Button:
            clicks=0
            @property
            def first(self):
                return self
            async def click(self,**kwargs):
                self.clicks+=1
                raise PlaywrightTimeoutError("PRIVATE_NAVIGATION_WAIT")
        class Inputs:
            async def count(self):
                return 0
        class Page:
            url="https://www.daangn.com/kr/search/buy-sell/?q=HDD"
            def __init__(self):
                self.button=Button()
            def get_by_role(self,*args,**kwargs):
                return self.button
            async def wait_for_timeout(self,ms):
                pass
            def locator(self,*args,**kwargs):
                return Inputs()
        page=Page()
        on_timeout=AsyncMock(return_value=True)
        after_open=AsyncMock(return_value=None)
        steps=await ui_select_region(
            page,BY_KEY["cheonan"],
            on_header_click_timeout=on_timeout,on_after_open=after_open)
        self.assertEqual(page.button.clicks,1)
        self.assertEqual(on_timeout.await_count,1)
        self.assertEqual(after_open.await_count,1)
        self.assertFalse(steps["clicked_region_button"])
        self.assertTrue(steps["header_click_verified_after_timeout"])
        self.assertEqual(steps["header_click_exception_kind"],
                         "PLAYWRIGHT_TIMEOUT")
        self.assertEqual(steps["progress_stage"],"AFTER_OPEN_CALLBACK")
        self.assertEqual(steps["error"],"region_input_not_found")

    async def test_without_optin_original_fail_closed(self):
        class Button:
            @property
            def first(self):
                return self
            async def click(self,**kwargs):
                raise PlaywrightTimeoutError("SECRET")
        class Page:
            url="https://www.daangn.com/kr/search/buy-sell/"
            def get_by_role(self,*a,**kw):
                return Button()
        steps=await ui_select_region(Page(),BY_KEY["cheonan"])
        self.assertEqual(steps["progress_stage"],"BEFORE_REGION_BUTTON_CLICK")
        self.assertEqual(steps["error"],"TimeoutError")
        self.assertFalse(steps["header_click_verified_after_timeout"])

    async def test_unverified_timeout_and_other_exception_fail_closed(self):
        class Button:
            def __init__(self,error):
                self.error=error
            @property
            def first(self):
                return self
            async def click(self,**kwargs):
                raise self.error
        class Page:
            url="https://www.daangn.com/kr/search/buy-sell/"
            def __init__(self,error):
                self.error=error
            def get_by_role(self,*a,**kw):
                return Button(self.error)
        for exception, callback_should_run in (
            (PlaywrightTimeoutError("PRIVATE_1"),True),
            (ValueError("PRIVATE_2"),False),
        ):
            callback=AsyncMock(return_value=False)
            steps=await ui_select_region(Page(exception),BY_KEY["cheonan"],
                                         on_header_click_timeout=callback)
            self.assertEqual(steps["progress_stage"],
                             "BEFORE_REGION_BUTTON_CLICK")
            self.assertFalse(steps["header_click_verified_after_timeout"])
            self.assertEqual(callback.await_count,
                             1 if callback_should_run else 0)
            self.assertEqual(steps["header_click_exception_kind"],
                             "PLAYWRIGHT_TIMEOUT" if callback_should_run
                             else "OTHER_EXCEPTION")

    async def test_proof_callback_exception_is_fail_closed(self):
        class Button:
            @property
            def first(self):
                return self
            async def click(self,**kwargs):
                raise PlaywrightTimeoutError("HIDDEN")
        class Page:
            url="https://www.daangn.com/kr/search/buy-sell/"
            def get_by_role(self,*a,**kw):
                return Button()
        async def reject():
            raise RuntimeError("PRIVATE_BROWSER_PROFILE")
        steps=await ui_select_region(
            Page(),BY_KEY["cheonan"],on_header_click_timeout=reject)
        self.assertEqual(steps["error"],"TimeoutError")
        self.assertFalse(steps["header_click_verified_after_timeout"])


class PrivacyTests(unittest.TestCase):
    def test_new_fields_are_strict_enums_and_idempotent(self):
        attempt=sanitize_attempt({
            "status":"REGION_HEADER_ACTION_EXCEPTION",
            "picker_phase_diagnostics":{
                "core_progress_stage":"AFTER_REGION_BUTTON_CLICK_VERIFIED",
                "header_click_verified_after_timeout":True,
                "header_click_exception_kind":"PLAYWRIGHT_TIMEOUT",
                "private_cookie":"PRIVATE_SECRET",
                "api":{"state":"NO_TARGET_REQUEST"},
            }
        })
        data=attempt["picker_phase_diagnostics"]
        self.assertTrue(data["header_click_verified_after_timeout"])
        self.assertEqual(data["header_click_exception_kind"],
                         "PLAYWRIGHT_TIMEOUT")
        self.assertEqual(data["core_progress_stage"],
                         "AFTER_REGION_BUTTON_CLICK_VERIFIED")
        self.assertEqual(sanitize_attempt(attempt),attempt)
        self.assertNotIn("PRIVATE_SECRET",json.dumps(attempt))
        self.assertFalse(attempt["authorizes_listings"])

    def test_unknown_exception_details_cannot_leak(self):
        result=sanitize_picker_phases({
            "header_click_exception_kind":"ERROR PRIVATE_TOKEN",
            "header_click_verified_after_timeout":"yes",
        })
        self.assertEqual(result["header_click_exception_kind"],"NONE")
        self.assertFalse(result["header_click_verified_after_timeout"])
        self.assertFalse(result["authorizes_listings"])


if __name__=="__main__":
    unittest.main()
