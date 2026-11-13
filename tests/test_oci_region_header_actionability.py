# -*- coding: utf-8 -*-
"""Offline-only exact header click actionability evidence.

The probe reads neither URLs/HTML/raw node attributes nor pixel
coordinates and never synthesizes a browser click.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
import daangn_v4_1_core as core
from app_v5.region_header_actionability import (
    _PROBE, sanitize_header_actionability, sample_header_actionability,
)
from app_v5.region_picker_phases import sanitize_picker_phases
from ops.oci.precollection import final_report


def snapshot(*, hit="TARGET", geo="IN_VIEWPORT", count=1, shown="YES",
             enabled="YES", state="OBSERVED"):
    return {
        "state": state, "document_visibility": "VISIBLE",
        "document_ready": "COMPLETE", "control_count": count,
        "control_visible": shown, "control_enabled": enabled,
        "geometry": geo, "center_hit": hit, "pointer_events": "ENABLED",
        "raw_cookie": "PRIVATE_AUTH_COOKIE",
        "raw_element": '<button aria-label="PRIVATE_SECRET">',
        "client_x": 314.5,
        "client_y": 500.0,
    }


class FixedPage:
    def __init__(self, result=None, *, raises=False):
        self.result = result
        self.raises = raises
        self.calls = 0
    async def evaluate(self, script):
        self.calls += 1
        if self.raises:
            raise RuntimeError("PRIVATE_BROWSER_EXCEPTION")
        return self.result


class SanitizationTests(unittest.TestCase):
    def test_empty_and_malformed_observations_are_unobservable(self):
        for raw in (None, 42, "PRIVATE", {"center_hit": True}):
            out=sanitize_header_actionability(raw)
            self.assertEqual(out["state"],"UNOBSERVABLE")
            self.assertEqual(out["authorizes_listings"],False)
            self.assertEqual(out["control_count"],-1)

    def test_known_hit_target_and_overlay_and_outside_preserved(self):
        for hit in ("TARGET","OTHER_ELEMENT","NO_ELEMENT",
                    "OUTSIDE_VIEWPORT","UNOBSERVABLE"):
            for geo in ("IN_VIEWPORT","PARTIAL_VIEWPORT",
                        "OUTSIDE_VIEWPORT","EMPTY","UNOBSERVABLE"):
                out=sanitize_header_actionability(snapshot(hit=hit,geo=geo))
                self.assertEqual(out["center_hit"],hit)
                self.assertEqual(out["geometry"],geo)
                self.assertEqual(sanitize_header_actionability(out),out)

    def test_boolean_counts_and_unknown_values_never_leak(self):
        out=sanitize_header_actionability({
            **snapshot(hit="PRIVATE_OVERLAY",count=True),
            "document_visibility":"PRIVATE_LOCATION",
            "control_visible":"PRIVATE_VISIBILITY",
            "document_ready":"PRIVATE_LOADER",
            "pointer_events":"PRIVATE_STYLE",
        })
        self.assertEqual(out["control_count"],-1)
        self.assertEqual(out["center_hit"],"UNOBSERVABLE")
        self.assertEqual(out["document_visibility"],"UNOBSERVABLE")
        self.assertEqual(out["pointer_events"],"UNOBSERVABLE")
        self.assertNotIn("PRIVATE",json.dumps(out))

    def test_read_only_probe_source_has_no_browser_actions_or_raw_export(self):
        self.assertIn("elementFromPoint",_PROBE)
        self.assertIn("getBoundingClientRect",_PROBE)
        for unsafe in (".click(", ".fetch(", "fetch(", "scrollIntoView(",
                       "dispatchEvent(", "setAttribute(", "localStorage",
                       "document.cookie", "outerHTML", "innerHTML"):
            self.assertNotIn(unsafe,_PROBE)


class SampleTests(unittest.IsolatedAsyncioTestCase):
    async def test_observed_sample_is_sanitized(self):
        page=FixedPage(snapshot(hit="OTHER_ELEMENT"))
        out=await sample_header_actionability(page)
        self.assertEqual(page.calls,1)
        self.assertEqual(out["center_hit"],"OTHER_ELEMENT")
        self.assertEqual(out["control_count"],1)
        self.assertNotIn("PRIVATE",json.dumps(out))

    async def test_failed_page_probe_does_not_infer_target(self):
        page=FixedPage(raises=True)
        out=await sample_header_actionability(page)
        self.assertEqual(out["state"],"UNOBSERVABLE")
        self.assertEqual(out["center_hit"],"UNOBSERVABLE")
        self.assertEqual(page.calls,1)

    async def test_no_data_cannot_authorize_region_or_collection(self):
        page=FixedPage(None)
        out=await sample_header_actionability(page)
        self.assertFalse(out["authorizes_listings"])
        self.assertEqual(out["control_visible"],"UNOBSERVABLE")


class HeaderCoreHookTests(unittest.IsolatedAsyncioTestCase):
    async def test_pre_click_hook_and_timeout_gate_never_retry(self):
        class Clicker:
            def __init__(self):self.calls=0
            async def click(self,**kwargs):
                self.calls+=1
                raise PlaywrightTimeoutError("PRIVATE_TIMEOUT")
        class Locator:
            def __init__(self,clicker):
                self.first=clicker
        class Page:
            url="https://www.daangn.com/kr/search/buy-sell/?q=HDD"
            def __init__(self):
                self.btn=Clicker()
                self.role_queries=0
            def get_by_role(self,*args,**kwargs):
                self.role_queries+=1
                return Locator(self.btn)
        page=Page()
        calls=[]
        async def before():
            calls.append("before")
        async def timeout():
            calls.append("timeout")
            return False
        row=await core.ui_select_region(
            page, core.BY_KEY["cheonan"],
            on_before_header_click=before,
            on_header_click_timeout=timeout)
        self.assertEqual(calls,["before","timeout"])
        self.assertEqual(page.btn.calls,1)
        self.assertEqual(page.role_queries,1)
        self.assertEqual(row["progress_stage"],"BEFORE_REGION_BUTTON_CLICK")
        self.assertEqual(row["header_click_exception_kind"],"PLAYWRIGHT_TIMEOUT")
        self.assertFalse(row["clicked_region_button"])
        self.assertFalse(row["header_click_verified_after_timeout"])
        self.assertEqual(row["error"],"TimeoutError")


class OperatorOutputTests(unittest.TestCase):
    def test_phase_sanitizer_is_idempotent_and_never_exports_raw_dom(self):
        src={
            "header_actionability_pre":snapshot(hit="OTHER_ELEMENT"),
            "header_actionability_timeout":snapshot(
                hit="TARGET",geo="PARTIAL_VIEWPORT"),
            "header_activation":{"armed":True},
            "raw_error":"PRIVATE_STACK_TRACE",
        }
        out=sanitize_picker_phases(src)
        self.assertEqual(sanitize_picker_phases(out),out)
        self.assertEqual(out["header_actionability_pre"]["center_hit"],
                         "OTHER_ELEMENT")
        self.assertEqual(out["header_actionability_timeout"]["center_hit"],
                         "TARGET")
        self.assertNotIn("PRIVATE",json.dumps(out))

    def test_operator_shows_both_sanitized_header_snapshots(self):
        report=final_report({
            "status":"REGION_HEADER_ACTION_EXCEPTION",
            "mode":"FILL",
            "picker_phase_diagnostics":{
                "header_actionability_pre":snapshot(
                    hit="OTHER_ELEMENT",geo="IN_VIEWPORT"),
                "header_actionability_timeout":snapshot(
                    hit="OTHER_ELEMENT",geo="IN_VIEWPORT"),
                "core_progress_stage":"BEFORE_REGION_BUTTON_CLICK",
                "header_click_exception_kind":"PLAYWRIGHT_TIMEOUT",
            },
        })
        self.assertEqual(report["status"],"STOP_REGION_NOT_VERIFIED")
        self.assertIsNone(report["precollection"])
        diag=report["region_diagnostics"]
        self.assertEqual(diag["header_actionability_pre"]["center_hit"],
                         "OTHER_ELEMENT")
        self.assertEqual(diag["header_actionability_timeout"]["center_hit"],
                         "OTHER_ELEMENT")
        self.assertEqual(diag["core_progress_stage"],
                         "BEFORE_REGION_BUTTON_CLICK")
        self.assertFalse(report["authorizes_listings"])
        self.assertFalse(report["collection_started"])
        self.assertFalse(report["database_written"])
        self.assertNotIn("PRIVATE",json.dumps(report))


if __name__=="__main__":
    unittest.main()
