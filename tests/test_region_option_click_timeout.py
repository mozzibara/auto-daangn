# -*- coding: utf-8 -*-
"""Offline-only one-dispatched-option-click timeout regression and privacy."""
from __future__ import annotations
import json
import unittest
from unittest.mock import AsyncMock
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from daangn_v4_1_core import BY_KEY, ui_select_region
from app_v5.region_option_events import verify_single_target_click_after_timeout
from app_v5.region_picker_phases import sanitize_picker_phases
from scripts.chrome_stable_input_compare import sanitize_attempt


class Witness:
    def __init__(self, *, armed=True, epoch=1790000000000):
        self._armed=armed
        self.epoch=epoch
    async def trusted_click_epoch_ms(self,page):
        return self.epoch


GOOD={
    "click_trusted":"YES","document_bubble":"YES",
    "event_target":"BUTTON",
    "events":["POINTER_DOWN","POINTER_UP",
              "CLICK_TARGET","CLICK_DOCUMENT"],
}
class SnapPage:
    def __init__(self,snapshot=None):
        self.snapshot=snapshot if snapshot is not None else GOOD
    async def evaluate(self, script):
        return self.snapshot


class OptionProofTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_once_target_and_document_click_succeeds(self):
        self.assertTrue(await verify_single_target_click_after_timeout(
            SnapPage(),Witness()))
    async def test_unarmed_untrusted_duplicate_or_missing_events_fail(self):
        cases=[
            (GOOD, Witness(armed=False)),
            ({**GOOD,"click_trusted":"NO"},Witness()),
            ({**GOOD,"document_bubble":"NO"},Witness()),
            ({**GOOD,"event_target":"OTHER"},Witness()),
            ({**GOOD,"events":GOOD["events"]+["CLICK_TARGET"]},Witness()),
            ({**GOOD,"events":["POINTER_DOWN","CLICK_TARGET","CLICK_DOCUMENT"]},Witness()),
            (GOOD,Witness(epoch=None)),
        ]
        for snapshot,witness in cases:
            with self.subTest(snapshot=snapshot,witness=witness.epoch):
                self.assertFalse(await verify_single_target_click_after_timeout(
                    SnapPage(snapshot),witness))
    async def test_page_observer_error_is_fail_closed(self):
        class Page:
            async def evaluate(self,script):
                raise RuntimeError("SECRET_USER_PAGE")
        self.assertFalse(await verify_single_target_click_after_timeout(
            Page(),Witness()))


class HeaderButton:
    clicks=0
    @property
    def first(self): return self
    async def click(self,**kw):
        self.clicks+=1


class InputLocator:
    value=""
    @property
    def first(self): return self
    async def count(self):return 1
    async def input_value(self):return self.value
    async def fill(self,value,**kw):self.value=value
    async def press_sequentially(self,value,**kw):self.value=value


class OptionLocator:
    def __init__(self,exception):
        self.exception=exception
        self.clicks=0
    @property
    def first(self): return self
    def filter(self,**kw):return self
    async def count(self):return 1
    async def is_visible(self):return True
    async def evaluate(self,script,metadata):
        return {
            "option_metadata":"OBSERVED",
            "option_city_hint":True,
            "option_exact_term":False,
            "option_data_id":"EXPECTED",
            "option_tag":"BUTTON","option_role":"OPTION",
            "option_parent":"DIALOG","option_aria_selected":"MISSING",
        }
    async def click(self,**kw):
        self.clicks+=1
        raise self.exception


class Page:
    url="https://www.daangn.com/kr/search/buy-sell/?q=HDD"
    def __init__(self,ex):
        self.button=HeaderButton()
        self.inputs=InputLocator()
        self.option=OptionLocator(ex)
    def get_by_role(self,*a,**kw):
        return self.button
    def locator(self,selector):
        return self.inputs if selector.startswith("input[") else self.option
    async def wait_for_timeout(self,ms):pass


async def ready():return {"state":"READY"}


class CoreTimeoutRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_timeout_delivered_option_and_no_repeat_click(self):
        page=Page(PlaywrightTimeoutError("PRIVATE_WAIT"))
        on_option=AsyncMock(return_value=True)
        after_select=AsyncMock()
        steps=await ui_select_region(
            page,BY_KEY["cheonan"],
            on_after_search_fill=ready,
            on_option_click_timeout=on_option,
            on_after_select=after_select,
            search_input_mode="SEQUENTIAL_KEYS")
        self.assertEqual(page.option.clicks,1)
        self.assertEqual(page.button.clicks,1)
        self.assertEqual(on_option.await_count,1)
        self.assertEqual(after_select.await_count,1)
        self.assertTrue(steps["selected_suggestion"])
        self.assertFalse(steps["option_click_returned"])
        self.assertTrue(steps["option_click_verified_after_timeout"])
        self.assertEqual(steps["option_click_exception_kind"],
                         "PLAYWRIGHT_TIMEOUT")
        self.assertEqual(steps["progress_stage"],
                         "AFTER_SUGGESTION_CLICK_VERIFIED")
        self.assertEqual(steps["error"],None)

    async def test_no_callback_timeout_remains_failed(self):
        page=Page(PlaywrightTimeoutError("PRIVATE_TIMEOUT"))
        steps=await ui_select_region(
            page,BY_KEY["cheonan"],on_after_search_fill=ready)
        self.assertEqual(page.option.clicks,1)
        self.assertEqual(steps["progress_stage"],"BEFORE_SUGGESTION_CLICK")
        self.assertEqual(steps["error"],"TimeoutError")
        self.assertFalse(steps["selected_suggestion"])
        self.assertFalse(steps["option_click_verified_after_timeout"])

    async def test_bad_proof_and_non_timeout_never_reclick(self):
        for exception,will_call in (
            (PlaywrightTimeoutError("SECRET1"),True),
            (ValueError("SECRET2"),False),
        ):
            page=Page(exception)
            cb=AsyncMock(return_value=False)
            steps=await ui_select_region(
                page,BY_KEY["cheonan"],on_after_search_fill=ready,
                on_option_click_timeout=cb)
            self.assertEqual(page.option.clicks,1)
            self.assertEqual(cb.await_count,1 if will_call else 0)
            self.assertFalse(steps["selected_suggestion"])
            self.assertFalse(steps["option_click_verified_after_timeout"])
            self.assertEqual(steps["progress_stage"],"BEFORE_SUGGESTION_CLICK")

    async def test_callback_exception_fails_closed(self):
        page=Page(PlaywrightTimeoutError("SECRET"))
        async def fail():
            raise RuntimeError("TOKEN")
        step=await ui_select_region(
            page,BY_KEY["cheonan"],on_after_search_fill=ready,
            on_option_click_timeout=fail)
        self.assertEqual(page.option.clicks,1)
        self.assertFalse(step["option_click_verified_after_timeout"])


class PrivacyTests(unittest.TestCase):
    def test_sanitizer_no_private_exception_and_idempotent(self):
        safe=sanitize_attempt({
            "status":"REGION_OPTION_ACTION_EXCEPTION",
            "picker_phase_diagnostics":{
                "core_progress_stage":"BEFORE_SUGGESTION_CLICK",
                "option_click_returned":False,
                "option_click_verified_after_timeout":False,
                "option_click_exception_kind":"PLAYWRIGHT_TIMEOUT",
                "private_state":"SECRET",
            },"URL":"https://private.invalid",
        })
        self.assertEqual(safe["status"],"REGION_OPTION_ACTION_EXCEPTION")
        self.assertEqual(safe["picker_phase_diagnostics"][
            "option_click_exception_kind"],"PLAYWRIGHT_TIMEOUT")
        self.assertEqual(sanitize_attempt(safe),safe)
        self.assertFalse(safe["authorizes_listings"])
        self.assertNotIn("SECRET",json.dumps(safe))
    def test_malformed_options_are_rejected(self):
        safe=sanitize_picker_phases({
            "option_click_returned":"true",
            "option_click_verified_after_timeout":"true",
            "option_click_exception_kind":"MY_SECRET",
        })
        self.assertFalse(safe["option_click_returned"])
        self.assertFalse(safe["option_click_verified_after_timeout"])
        self.assertEqual(safe["option_click_exception_kind"],"NONE")


if __name__ == "__main__":
    unittest.main()
