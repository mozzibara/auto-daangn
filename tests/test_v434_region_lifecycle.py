# -*- coding: utf-8 -*-
"""Privacy and sequencing tests for a read-only dialog lifecycle witness."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app_v5.region_lifecycle import (
    RegionLifecycleWitness, sanitize_region_lifecycle,
)
from app_v5.region_navigation import sanitize_navigation_trace
from daangn_v4_1_core import BY_KEY
from scripts.report_v434_failure import classify


def snapshot(*, state="TARGET_DIALOG_CHOICE", buttons=47,
             region=45, target=1, city=1, login=0, outside=0):
    return {
        "state": state, "selected_control": "OTHER",
        "visible_dialogs": 1, "visible_dialog_buttons": buttons,
        "target_dialog_buttons": target,
        "target_city_dialog_buttons": city,
        "target_outside_buttons": outside,
        "other_region_dialog_buttons": region,
        "confirm_dialog_buttons": 0, "login_dialog_signals": login,
        "region_dialog_inputs": 1, "busy_signals": 0,
        "raw_DOM": "<script>SECRET_USER_URL</script>",
        "full_user_address": "SECRET",
    }


class FakePage:
    def __init__(self, *raw):
        self.raw = list(raw)
        self.calls = 0
        self.args = None

    async def evaluate(self, script, args):
        self.calls += 1
        self.args = args
        if not self.raw:
            return None
        return self.raw.pop(0)


class LifecycleTests(unittest.TestCase):
    def test_double_sanitization_fixed_semantics_only(self):
        input_row = {"checkpoints": {
            "AFTER_FIRST": snapshot(),
            "AFTER_FOLLOWUP_GATE": snapshot(
                state="POSSIBLE_LOGIN_GATE", buttons=2, region=0,
                target=0, city=0, login=1),
            "AFTER_CORE_SETTLE": snapshot(
                state="DIALOG_WITHOUT_CONTROLS", buttons=0,
                region=0, target=0, city=0),
            "AFTER_SETTLE": snapshot(
                state="NO_DIALOG", buttons=0, region=0,
                target=0, city=0),
            "AFTER_DELAYED_SETTLE": {
                **snapshot(state="NO_DIALOG", buttons=0,
                           region=0, target=0, city=0),
                "selected_control": "EXPECTED",
                "unknown_id": "SECRET_OWNER_LINK",
            },
        }, "owner_secret": "PRIVATE_TITLE", "authorizes_listings": True}
        first = sanitize_region_lifecycle(input_row)
        second = sanitize_region_lifecycle(first)
        self.assertEqual(first, second)
        self.assertFalse(first["authorizes_listings"])
        self.assertEqual(
            first["checkpoints"]["AFTER_FIRST"]["other_region_dialog_buttons"], 45)
        self.assertEqual(
            first["checkpoints"]["AFTER_FOLLOWUP_GATE"]["state"],
            "POSSIBLE_LOGIN_GATE")
        self.assertNotIn("PRIVATE", json.dumps(first))
        self.assertNotIn("SECRET", json.dumps(first))
        self.assertNotIn("raw_DOM", json.dumps(first))
        self.assertEqual(
            first["checkpoints"]["AFTER_DELAYED_SETTLE"]["selected_control"],
            "EXPECTED")
        self.assertNotIn("SECRET_OWNER_LINK", json.dumps(first))

    def test_unknown_dom_data_never_exits_report_boundary(self):
        raw = {"region_lifecycle": {"checkpoints": {
            "AFTER_FIRST": {
                "state": "PERSON_ADDRESS", "selected_control": "1234",
                "visible_dialog_buttons": "UNTRUSTED_LINK",
                "target_dialog_buttons": 10000, "raw_HTML": "<secret>",
            },
        }, "source_listing": "SECRET_USER_URL"}}
        first = sanitize_navigation_trace(raw)
        second = sanitize_navigation_trace(first)
        self.assertEqual(first, second)
        c = second["region_lifecycle"]["checkpoints"]["AFTER_FIRST"]
        self.assertEqual(c["state"], "UNOBSERVABLE")
        self.assertEqual(c["selected_control"], "UNOBSERVABLE")
        self.assertEqual(c["visible_dialog_buttons"], -1)
        self.assertEqual(c["target_dialog_buttons"], -1)
        self.assertFalse(second["region_lifecycle"]["authorizes_listings"])
        self.assertNotIn("secret", json.dumps(second).lower())

    def test_counters_are_bounded(self):
        a = sanitize_region_lifecycle({"checkpoints": {
            "AFTER_FIRST": snapshot(buttons=61, region=100)
        }})
        self.assertEqual(a["checkpoints"]["AFTER_FIRST"]["visible_dialog_buttons"], -1)
        self.assertEqual(
            a["checkpoints"]["AFTER_FIRST"]["other_region_dialog_buttons"], -1)


class AsyncLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_observer_calls_page_only_for_allowlisted_stages(self):
        page = FakePage(snapshot(), snapshot(state="NO_DIALOG", buttons=0,
                                              region=0, target=0, city=0))
        probe = RegionLifecycleWitness(BY_KEY["cheonan"])
        await probe.checkpoint(page, "AFTER_FIRST")
        await probe.checkpoint(page, "UNKNOWN_STAGE")
        await probe.checkpoint(page, "AFTER_SETTLE")
        self.assertEqual(page.calls, 2)
        self.assertEqual(page.args["term"], BY_KEY["cheonan"]["term"])
        self.assertEqual(page.args["city"], BY_KEY["cheonan"]["label"])
        out = probe.export()
        self.assertEqual(out["checkpoints"]["AFTER_FIRST"]["visible_dialog_buttons"], 47)
        self.assertEqual(out["checkpoints"]["AFTER_SETTLE"]["state"], "NO_DIALOG")
        self.assertFalse(out["authorizes_listings"])


class ReporterBoundaryTests(unittest.TestCase):
    def test_public_failure_log_prints_only_expected_categories(self):
        with TemporaryDirectory() as td:
            root=Path(td)
            payload={"evaluation":{"contexts":[{
                "context":"cheonan_a",
                "capture_failure_code":"FRESH_REGION_PROOF_MISSING",
                "region_picker":{"navigation_trace":{
                    "region_lifecycle":{"checkpoints":{
                        "AFTER_FIRST":snapshot(),
                        "AFTER_SETTLE":snapshot(state="POSSIBLE_LOGIN_GATE",
                                                buttons=2,region=0,target=0,
                                                city=0,login=1),
                        "AFTER_DELAYED_SETTLE":{
                            **snapshot(state="DIALOG_WITHOUT_CONTROLS",
                                       buttons=0,region=0,target=0,city=0),
                            "selected_control":"EXPECTED",
                            "unknown_pii":"SECRET_PRIVATE_LINK",
                        },
                    }, "raw_sensitive_dom":"PRIVATE_TOKEN"},
                }},
            }]}}
            (root/"v423_public_controls_results.json").write_text(
                json.dumps(payload),encoding="utf-8")
            result=classify(root)
            self.assertEqual(result["LIFECYCLE_AFTER_FIRST_STATE"],
                             "TARGET_DIALOG_CHOICE")
            self.assertEqual(
                result["LIFECYCLE_AFTER_FIRST_OTHER_REGION_DIALOG_BUTTONS"],"45")
            self.assertEqual(result["LIFECYCLE_AFTER_SETTLE_STATE"],
                             "POSSIBLE_LOGIN_GATE")
            self.assertEqual(result["LIFECYCLE_AFTER_SETTLE_LOGIN_DIALOG_SIGNALS"],"1")
            self.assertEqual(result["LIFECYCLE_AUTHORIZES_LISTINGS"],"NO")
            self.assertEqual(
                result["LIFECYCLE_AFTER_DELAYED_SETTLE_SELECTED_CONTROL"],
                "EXPECTED")
            for value in ("PRIVATE_TOKEN","SECRET","raw_DOM","full_user_address"):
                self.assertNotIn(value,str(result))


if __name__=="__main__":
    unittest.main()
