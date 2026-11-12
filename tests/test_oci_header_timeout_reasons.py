# -*- coding: utf-8 -*-
"""Offline-only OCI failed picker-click evidence and privacy regressions."""
from __future__ import annotations

import json
import unittest

from app_v5.region_header_activation import (
    assess_header_click_timeout_without_reclick,
    sanitize_header_timeout_reason,
    verify_header_click_timeout_without_reclick,
)
from app_v5.region_picker_phases import sanitize_picker_phases
from ops.oci.precollection import final_report, blocked


_KEYS=("CLICK", "MOUSEDOWN", "MOUSEUP", "POINTERDOWN", "POINTERUP")


def snapshot(*, armed=True, visible=1, enabled=1, candidates=1,
             trusted_count=1, total_count=1):
    return {
        "armed": armed, "header_visible": visible,
        "header_enabled": enabled, "header_candidates": candidates,
        "trusted": {key:trusted_count for key in _KEYS},
        "counts": {key:total_count for key in _KEYS},
        "raw_browser_cookie": "PRIVATE_COOKIE",
    }


class Witness:
    def __init__(self, data, *, armed=True):
        self.armed=armed
        self.data=data

    async def sample(self,page):
        from app_v5.region_header_activation import sanitize_header_activation
        return sanitize_header_activation(self.data)


class Page:
    def __init__(self, *, visible=True, enabled_empty=True, failure=False):
        self.visible=visible
        self.enabled_empty=enabled_empty
        self.failure=failure
        self.calls=0

    async def evaluate(self, script):
        self.calls+=1
        if self.failure:
            raise ValueError("PRIVATE_CHROME_SESSION_ERROR")
        return {
            "one_visible_region_input": self.visible,
            "one_empty_enabled_dialog_input": self.enabled_empty,
            "raw_input_value": "PRIVATE_LOCATION",
        }


class ReasonClassificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_verified_result_equivalent_to_original_boolean_gate(self):
        w=Witness(snapshot())
        page=Page()
        answer=await assess_header_click_timeout_without_reclick(page,w)
        self.assertEqual(answer,{"verified":True,"reason":"VERIFIED"})
        self.assertTrue(await verify_header_click_timeout_without_reclick(
            Page(),w))
        self.assertEqual(page.calls,1)

    async def test_no_observer_never_evaluates_page(self):
        page=Page()
        answer=await assess_header_click_timeout_without_reclick(
            page,Witness(snapshot(),armed=False))
        self.assertEqual(answer["reason"],"WITNESS_NOT_ARMED")
        self.assertFalse(answer["verified"])
        self.assertEqual(page.calls,0)

    async def test_observer_disappeared(self):
        answer=await assess_header_click_timeout_without_reclick(
            Page(),Witness(snapshot(armed=False)))
        self.assertEqual(answer["reason"],"WITNESS_UNAVAILABLE")

    async def test_header_must_be_unique_visible_and_enabled(self):
        for args in (dict(candidates=2),dict(visible=0),
                     dict(enabled=0)):
            with self.subTest(args=args):
                page=Page()
                answer=await assess_header_click_timeout_without_reclick(
                    page,Witness(snapshot(**args)))
                self.assertEqual(answer["reason"],"HEADER_CONTROL_NOT_UNIQUE")
                self.assertEqual(page.calls,0)

    async def test_missing_extra_or_untrusted_click(self):
        for args in (dict(trusted_count=0),dict(total_count=2),
                     dict(trusted_count=2,total_count=2)):
            with self.subTest(args=args):
                page=Page()
                answer=await assess_header_click_timeout_without_reclick(
                    page,Witness(snapshot(**args)))
                self.assertEqual(answer["reason"],"EVENTS_NOT_UNIQUE_TRUSTED")
                self.assertEqual(page.calls,0)

    async def test_dialog_input_missing_ambiguous_or_not_empty(self):
        answer=await assess_header_click_timeout_without_reclick(
            Page(visible=False),Witness(snapshot()))
        self.assertEqual(answer["reason"],"INPUT_NOT_UNIQUE_VISIBLE")
        answer=await assess_header_click_timeout_without_reclick(
            Page(enabled_empty=False),Witness(snapshot()))
        self.assertEqual(answer["reason"],"INPUT_NOT_EMPTY_ENABLED_DIALOG")

    async def test_probe_exception_never_relaxes_gate(self):
        answer=await assess_header_click_timeout_without_reclick(
            Page(failure=True),Witness(snapshot()))
        self.assertEqual(answer["reason"],"INPUT_PROBE_ERROR")
        self.assertFalse(answer["verified"])


class OperatorDiagnosticsTests(unittest.TestCase):
    def test_region_timeout_exposes_safe_reason_not_private_values(self):
        row={
            "status":"REGION_HEADER_ACTION_EXCEPTION",
            "raw_listing_url":"https://private.invalid/SECRET_ITEM",
            "picker_phase_diagnostics":{
                "step_error":"STEP_EXCEPTION",
                "core_progress_stage":"BEFORE_REGION_BUTTON_CLICK",
                "readiness_state":"NOT_RUN",
                "header_click_exception_kind":"PLAYWRIGHT_TIMEOUT",
                "header_timeout_gate_reason":"HEADER_CONTROL_NOT_UNIQUE",
                "core_header_click_returned":False,
                "header_activation":snapshot(candidates=2),
                "phases":{"AFTER_CORE_RETURN":{
                    "visible_inputs":1, "focus":"REGION_INPUT",
                    "raw_html":"PRIVATE_HTML",
                }},
            }
        }
        result=final_report(row)
        self.assertEqual(result["status"],"STOP_REGION_NOT_VERIFIED")
        self.assertEqual(result["region_status"],"REGION_HEADER_ACTION_EXCEPTION")
        safe=result["region_diagnostics"]
        self.assertEqual(safe["header_timeout_gate_reason"],
                         "HEADER_CONTROL_NOT_UNIQUE")
        self.assertEqual(safe["header_trusted_click_count"],1)
        self.assertEqual(safe["header_candidates"],2)
        self.assertEqual(safe["input_visible_at_core_return"],1)
        self.assertFalse(result["authorizes_listings"])
        for private in ("SECRET", "PRIVATE", "private.invalid"):
            self.assertNotIn(private,json.dumps(result,ensure_ascii=False))

    def test_sanitizers_drop_unknown_errors_and_are_idempotent(self):
        malicious={
            "header_timeout_gate_reason":"MY_LOCAL_IP_AND_COOKIE",
            "header_activation":{"raw_token":"PRIVATE_KEY"},
            "raw_region":"PRIVATE_REGION",
        }
        sanitized=sanitize_picker_phases(malicious)
        self.assertEqual(sanitized["header_timeout_gate_reason"],"UNOBSERVABLE")
        self.assertEqual(sanitize_picker_phases(sanitized),sanitized)
        self.assertEqual(sanitize_header_timeout_reason(
            "NOT_INVOKED"),"NOT_INVOKED")
        self.assertEqual(sanitize_header_timeout_reason(
            "PRIVATE_ERROR"),"UNOBSERVABLE")
        self.assertNotIn("PRIVATE",json.dumps(sanitized))

    def test_disabled_approval_never_has_real_region_diagnostics(self):
        result=blocked("OWNER_APPROVAL_REQUIRED")
        self.assertIsNone(result["region_diagnostics"])
        self.assertFalse(result["authorizes_listings"])
        self.assertFalse(result["collection_started"])


if __name__ == "__main__":
    unittest.main()
