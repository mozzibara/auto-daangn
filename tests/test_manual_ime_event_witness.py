# -*- coding: utf-8 -*-
"""Offline privacy regressions for dynamically created owner-operated input."""
from __future__ import annotations

import json
import unittest

from app_v5.manual_region_input_events import (
    ManualRegionInputEventWitness, sanitize_manual_input_events, _JS_ARM,
)
from app_v5.manual_chrome_region import sanitize_manual_report
from app_v5.region_input_events import (
    EVENTS, INPUT_TYPES, sanitize_input_events, sanitize_region_focus,
)
from scripts.chrome_stable_input_compare import sanitize_attempt


class PrivacyTests(unittest.TestCase):
    def test_dynamic_witness_never_serializes_key_names_or_text(self):
        self.assertNotIn("e.key", _JS_ARM)
        self.assertNotIn("e.data", _JS_ARM)
        self.assertNotIn("innerText", _JS_ARM)
        self.assertNotIn("outerHTML", _JS_ARM)
        self.assertNotIn("input.value", _JS_ARM)

    def test_manual_payload_is_bounded_and_idempotent(self):
        raw = {
            "armed": True, "observed_input": True,
            "counts": {v: 3 for v in EVENTS},
            "trusted": {v: 2 for v in EVENTS},
            "sequence": ["KEYDOWN", "COMPOSITIONSTART", "INPUT",
                         "COMPOSITIONEND", "KEYUP", "PRIVATE-KEY"],
            "input_types": {"INSERT_COMPOSITION": 4, "OTHER": 1},
            "composing_events": 3,
            "raw_key": "PRIVATE_PASSWORD", "input_value": "SECRET_ADDRESS",
            "cookie": "PRIVATE_COOKIE", "raw_region": "2292",
        }
        safe = sanitize_manual_input_events(raw)
        self.assertTrue(safe["observed_input"])
        self.assertEqual(safe["counts"]["KEYDOWN"], 3)
        self.assertEqual(safe["input_types"]["INSERT_COMPOSITION"], 4)
        self.assertEqual(safe["composing_events"], 3)
        self.assertEqual(safe["sequence"], raw["sequence"][:-1])
        self.assertEqual(sanitize_manual_input_events(safe), safe)
        for token in ("PRIVATE", "SECRET", "2292", "raw_key", "cookie"):
            self.assertNotIn(token, json.dumps(safe, ensure_ascii=False))
        self.assertFalse(safe["authorizes_listings"])

    def test_untrusted_malformed_semantics_cannot_be_promoted(self):
        safe = sanitize_input_events({
            "counts": {"INPUT": True}, "trusted": {"INPUT": -3},
            "input_types": {"INSERT_TEXT": True, "DELETE": 9999},
            "composing_events": "secret", "sequence": ["PRIVATE", "INPUT"],
        })
        self.assertEqual(safe["counts"]["INPUT"], -1)
        self.assertEqual(safe["trusted"]["INPUT"], -1)
        self.assertEqual(safe["input_types"]["INSERT_TEXT"], -1)
        self.assertEqual(safe["input_types"]["DELETE"], -1)
        self.assertEqual(safe["composing_events"], -1)
        self.assertEqual(safe["sequence"], ["INPUT"])
        self.assertEqual(tuple(safe["input_types"]), INPUT_TYPES)
        self.assertEqual(sanitize_input_events(safe), safe)

    def test_focus_enums_never_export_active_element_identity(self):
        for value in ("REGION_INPUT", "DIALOG_OTHER",
                      "OUTSIDE_DIALOG", "BODY"):
            self.assertEqual(sanitize_region_focus(value), value)
        for value in ("SECRET_INPUT", "https://private.example/", 123, True):
            self.assertEqual(sanitize_region_focus(value), "UNOBSERVABLE")

    def test_manual_report_and_auto_report_have_safe_focus_and_events(self):
        manual = sanitize_manual_report({
            "status": "MANUAL_CLICK_OBSERVED",
            "manual_input_events": {
                "AT_CLICK": {"armed": True, "observed_input": True,
                             "counts": {"INPUT": 5},
                             "sequence": ["COMPOSITIONSTART", "INPUT"]},
                "AFTER_4000MS": {"armed": True, "observed_input": True,
                                  "sequence": ["BLUR", "PRIVATE"]},
                "PRIVATE": "SECRET",
            },
            "input_focus": {"AT_CLICK": "DIALOG_OTHER",
                            "AFTER_4000MS": "OUTSIDE_DIALOG",
                            "RAW": "SECRET"},
            "raw_html": "<private>",
        })
        self.assertEqual(manual["manual_input_events"]["AT_CLICK"]
                         ["counts"]["INPUT"], 5)
        self.assertEqual(manual["input_focus"]["AT_CLICK"], "DIALOG_OTHER")
        self.assertEqual(manual["input_focus"]["AFTER_4000MS"], "OUTSIDE_DIALOG")
        self.assertEqual(sanitize_manual_report(manual), manual)
        self.assertNotIn("SECRET", json.dumps(manual))
        self.assertFalse(manual["authorizes_listings"])
        auto = sanitize_attempt({
            "mode": "SEQUENTIAL_KEYS",
            "input_focus": {"BEFORE_SELECT": "REGION_INPUT",
                            "AFTER_CLICK": "DIALOG_OTHER",
                            "AFTER_4000MS": "PRIVATE_LOCATION"},
            "input_events": {"input_types": {"INSERT_TEXT": 3}},
        })
        self.assertEqual(auto["input_focus"]["AFTER_4000MS"], "UNOBSERVABLE")
        self.assertEqual(sanitize_attempt(auto), auto)
        self.assertFalse(auto["authorizes_listings"])


class FakePage:
    def __init__(self):
        self.calls = []
        self.arm_count = 0
        self.stop_count = 0

    async def evaluate(self, script):
        self.calls.append(script)
        if "addEventListener(name,fn" in script:
            self.arm_count += 1
            return True
        if "snapshot?.()" in script:
            return {"armed": True, "observed_input": True,
                    "counts": {"INPUT": 3}, "trusted": {"INPUT": 3},
                    "sequence": ["BEFOREINPUT", "INPUT"],
                    "input_types": {"INSERT_COMPOSITION": 2},
                    "composing_events": 1, "secret": "PRIVATE"}
        self.stop_count += 1
        return True


class DelegatedObserverTests(unittest.IsolatedAsyncioTestCase):
    async def test_arm_sample_stop_are_read_only_and_ordered(self):
        page = FakePage()
        witness = ManualRegionInputEventWitness()
        self.assertTrue(await witness.arm(page))
        safe = await witness.sample(page)
        self.assertTrue(safe["observed_input"])
        self.assertEqual(safe["counts"]["INPUT"], 3)
        self.assertEqual(safe["composing_events"], 1)
        self.assertFalse(safe["authorizes_listings"])
        self.assertNotIn("PRIVATE", str(safe))
        await witness.stop(page)
        self.assertEqual((page.arm_count, page.stop_count), (1, 1))


if __name__ == "__main__":
    unittest.main()
