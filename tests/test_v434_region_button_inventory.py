# -*- coding: utf-8 -*-
"""Synthetic, offline tests for region-button histograms and privacy boundary."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app_v5.region_button_inventory import (
    RegionButtonInventory, classify_inventory, sanitize_button_inventory,
    sanitize_button_snapshot,
)
from app_v5.region_navigation import sanitize_navigation_trace
from daangn_v4_1_core import BY_KEY
from scripts.report_v434_failure import classify


def example_button(*, candidate="TARGET_WITH_CITY",
                   freshness="NEW_DOM_NODE", role="NATIVE_BUTTON",
                   origin="ORIGINAL_DIALOG", area="BODY", vertical="MIDDLE"):
    return {
        "role": role, "candidate": candidate, "area": area,
        "vertical": vertical, "action": "OTHER", "origin": origin,
        "freshness": freshness,
    }


def example_snapshot(*, fresh=18, targets=1, region_like=6,
                     scope="ORIGINAL_ONLY"):
    return {
        "scope": scope, "overflow": False, "visible_buttons": fresh+3,
        "new_dom_buttons": fresh, "new_target_buttons": targets,
        "new_region_like_buttons": region_like,
        "visible_target_buttons": 1, "region_like_buttons": region_like,
        "active_dialogs": 1,
        "groups": {
            "role": {"NATIVE_BUTTON": fresh+3, "ARIA_OPTION": 0,
                     "ARIA_BUTTON": 0, "OTHER": 0},
            "candidate": {"TARGET_WITH_CITY": targets,
                          "TARGET_ONLY": 0, "CITY_ONLY": region_like-targets,
                          "OTHER_REGION_LIKE": 0,
                          "NOT_REGION_LIKE": fresh+3-region_like},
            "area": {"BODY": fresh+3},
            "vertical": {"MIDDLE": fresh+3},
            "action": {"OTHER": fresh+3},
            "origin": {"ORIGINAL_DIALOG": fresh+3},
            "freshness": {"PRESENT_AT_ARM": 3,
                          "NEW_DOM_NODE": fresh},
        },
        "samples": [example_button()],
    }


class RegionButtonInventoryTests(unittest.TestCase):
    def test_all_categories_survive_double_sanitization(self):
        raw = {
            "armed": "ARMED", "baseline": example_snapshot(
                fresh=0, targets=0, region_like=0),
            "checkpoints": {
                "AFTER_CLICK": example_snapshot(),
                "AFTER_SETTLE": example_snapshot(
                    fresh=0, targets=0, region_like=0,
                    scope="OTHER_ONLY"),
            },
            "interpretation": "TARGET_MATCHING_NEW_DOM_NODES",
            "secret_raw_button_text": "PRIVATE USER URL",
            "authorizes_listings": True,
        }
        safe = sanitize_button_inventory(raw)
        self.assertEqual(safe, sanitize_button_inventory(safe))
        self.assertFalse(safe["authorizes_listings"])
        self.assertEqual(safe["checkpoints"]["AFTER_CLICK"]["new_dom_buttons"], 18)
        self.assertEqual(
            safe["checkpoints"]["AFTER_CLICK"]["groups"]["candidate"]["CITY_ONLY"], 5)
        self.assertEqual(
            safe["checkpoints"]["AFTER_CLICK"]["samples"][0]["vertical"], "MIDDLE")
        self.assertNotIn("PRIVATE USER URL", json.dumps(safe))

    def test_unknown_fields_and_raw_labels_never_escape(self):
        raw = {
            "scope": "private-123", "active_dialogs": 900,
            "visible_buttons": "SECRET",
            "groups": {
                "role": {"NATIVE_BUTTON": 999, "personal": "PRIVATE"},
                "candidate": {"TARGET_ONLY": 3, "OTHER_REGION_LIKE": -3}
            },
            "samples": [
                {**example_button(),
                 "candidate": "PRIVATE_PERSON", "raw_text": "SECRET LINK"},
                "NOT A DICTIONARY",
            ],
        }
        safe = sanitize_button_snapshot(raw)
        self.assertEqual(safe["scope"], "UNOBSERVABLE")
        self.assertEqual(safe["visible_buttons"], -1)
        self.assertEqual(safe["groups"]["role"]["NATIVE_BUTTON"], -1)
        self.assertEqual(safe["groups"]["candidate"]["TARGET_ONLY"], 3)
        self.assertEqual(safe["samples"][0]["candidate"], "UNKNOWN")
        for item in ("SECRET", "PRIVATE", "personal", "raw_text"):
            self.assertNotIn(item, json.dumps(safe))

    def test_capped_sample_count_and_no_unbounded_output(self):
        raw = example_snapshot()
        raw["samples"] = [example_button() for _ in range(55)]
        safe = sanitize_button_snapshot(raw)
        self.assertEqual(len(safe["samples"]), 8)

    def test_unverified_new_target_is_not_a_successful_final_selection(self):
        row = {"armed": "ARMED",
               "checkpoints": {"AFTER_CLICK": example_snapshot()}}
        self.assertEqual(classify_inventory(row),
                         "TARGET_MATCHING_NEW_DOM_NODES")
        self.assertNotIn("VERIFIED", classify_inventory(row))

    def test_new_non_target_regions_and_generic_rerenders(self):
        row = {"armed": "ARMED", "checkpoints": {"AFTER_CLICK": {
            **example_snapshot(), "new_target_buttons": 0}}}
        self.assertEqual(classify_inventory(row), "REGION_LIKE_NEW_DOM_NODES")
        row["checkpoints"]["AFTER_CLICK"]["new_region_like_buttons"] = 0
        self.assertEqual(classify_inventory(row), "GENERIC_DOM_REPLACEMENTS_ONLY")
        row["checkpoints"]["AFTER_CLICK"]["new_dom_buttons"] = 0
        self.assertEqual(classify_inventory(row), "NO_NEW_BUTTON_NODES")

    def test_absent_state_refuses_claiming_followup(self):
        row = {"armed": "ARMED", "checkpoints": {
            "AFTER_CLICK": {"scope": "NO_VISIBLE_DIALOG"}}}
        self.assertEqual(classify_inventory(row),
                         "DIALOG_SCOPE_UNRESOLVED")
        self.assertEqual(classify_inventory({"armed": "NOT_OBSERVABLE"}),
                         "NOT_OBSERVABLE")

    def test_second_public_region_boundary_preserves_enums_only(self):
        raw = {"button_inventory": {
            "armed": "ARMED", "checkpoints": {
                "AFTER_CLICK": example_snapshot()},
            "interpretation": "TARGET_MATCHING_NEW_DOM_NODES",
            "listing_title": "SECRET LISTING",
        }}
        first = sanitize_navigation_trace(raw)
        second = sanitize_navigation_trace(first)
        self.assertEqual(first, second)
        self.assertNotIn("SECRET LISTING", json.dumps(second))
        self.assertEqual(
            second["button_inventory"]["checkpoints"]["AFTER_CLICK"]
            ["groups"]["role"]["NATIVE_BUTTON"], 21)
        self.assertFalse(second["authorizes_listings"])


class FakeLocator:
    def __init__(self):
        self.calls = 0
        self.arg = None

    async def evaluate(self, script, arg):
        self.calls += 1
        self.arg = arg
        return {"armed": "ARMED", "baseline": example_snapshot(
            fresh=0, targets=0, region_like=0)}


class FakePage:
    def __init__(self):
        self.raw = [example_snapshot(), example_snapshot(
            fresh=0, targets=0, region_like=0, scope="OTHER_ONLY")]
        self.stopped = False

    async def evaluate(self, script):
        if "stop" in script:
            self.stopped = True
            return True
        return self.raw.pop(0)


class PassiveCaptureTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_exact_locator_receives_read_only_witness(self):
        target, page = FakeLocator(), FakePage()
        probe = RegionButtonInventory(BY_KEY["cheonan"])
        await probe.arm(target)
        self.assertEqual(target.calls, 1)
        self.assertEqual(target.arg["term"], BY_KEY["cheonan"]["term"])
        self.assertEqual(probe.baseline["new_dom_buttons"], 0)
        await probe.checkpoint(page, "AFTER_CLICK")
        await probe.checkpoint(page, "AFTER_SETTLE")
        exported = probe.export()
        self.assertEqual(exported["interpretation"],
                         "TARGET_MATCHING_NEW_DOM_NODES")
        self.assertEqual(exported["checkpoints"]["AFTER_SETTLE"]["scope"],
                         "OTHER_ONLY")
        self.assertFalse(exported["authorizes_listings"])
        await probe.stop(page)
        self.assertTrue(page.stopped)


class ReportBoundaryTests(unittest.TestCase):
    def test_only_allowlisted_capped_inventory_values_in_public_log(self):
        with TemporaryDirectory() as td:
            folder = Path(td)
            data = {"evaluation": {"contexts": [{
                "context": "cheonan_a",
                "capture_failure_code": "FRESH_REGION_PROOF_MISSING",
                "region_picker": {"navigation_trace": {
                    "button_inventory": {
                        "armed": "ARMED",
                        "baseline": example_snapshot(
                            fresh=0, targets=0, region_like=0),
                        "checkpoints": {
                            "AFTER_CLICK": example_snapshot(),
                            "AFTER_SETTLE": example_snapshot(
                                fresh=0, targets=0, region_like=0,
                                scope="OTHER_ONLY"),
                        },
                        "interpretation": "TARGET_MATCHING_NEW_DOM_NODES",
                        "raw_secret": "SECRET BUYER URL"
                    },
                }},
            }]}}
            (folder / "v423_public_controls_results.json").write_text(
                json.dumps(data), encoding="utf-8")
            report = classify(folder)
            self.assertEqual(report["BUTTONS_INTERPRETATION"],
                             "TARGET_MATCHING_NEW_DOM_NODES")
            self.assertEqual(report["BUTTONS_AFTER_CLICK_NEW_DOM_BUTTONS"], "18")
            self.assertEqual(
                report["BUTTONS_AFTER_CLICK_CANDIDATE_CITY_ONLY"], "5")
            self.assertEqual(
                report["BUTTONS_AFTER_CLICK_ROLE_NATIVE_BUTTON"], "21")
            self.assertEqual(report["BUTTONS_AFTER_SETTLE_SCOPE"], "OTHER_ONLY")
            self.assertEqual(report["BUTTONS_AUTHORIZES_LISTINGS"], "NO")
            self.assertIn("TARGET_WITH_CITY", report[
                "BUTTONS_AFTER_CLICK_CATEGORICAL_SAMPLES"])
            self.assertNotIn("SECRET BUYER", str(report))


if __name__ == "__main__":
    unittest.main()
