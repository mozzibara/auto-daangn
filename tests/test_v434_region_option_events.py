# -*- coding: utf-8 -*-
"""Synthetic, no-network tests of exact clicked-option event evidence."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app_v5.region_option_events import (
    RegionOptionEventWitness, classify_option_purpose,
    sanitize_option_attributes, sanitize_option_event,
    sanitize_option_snapshot,
)
from app_v5.region_navigation import sanitize_navigation_trace
from daangn_v4_1_core import BY_KEY
from scripts.report_v434_failure import classify


def attr(**kwargs):
    return {"tag": "BUTTON", "role": "MISSING", "parent": "DIALOG",
            "haspopup": "MISSING", "expanded": "MISSING",
            "button_type": "BUTTON", "data_state": "MISSING",
            "aria_disabled": "MISSING", "tab_focus": "FOCUSABLE",
            "aria_label_relation": "CITY",
            "has_aria_controls": False, "has_aria_describedby": False,
            "inside_form": False, "native_disabled": False, **kwargs}


def snap(*, events=None, added_dialogs=0, added_buttons=0, expanded="MISSING"):
    return {"events": events if events is not None else [
                    "POINTER_DOWN", "POINTER_UP", "CLICK_TARGET", "CLICK_DOCUMENT"],
            "click_trusted": "YES", "default_prevented": "NO",
            "target_connected": "NO", "dialog_connected": "YES",
            "dialog_visible": "YES", "focus": "INSIDE_DIALOG",
            "expanded": expanded, "event_target": "DESCENDANT",
            "document_bubble": "YES",
            "child_mutations": 1, "attribute_mutations": 1,
            "added_buttons": added_buttons, "added_dialogs": added_dialogs,
            "added_inputs": 0}


class OptionClassificationTests(unittest.TestCase):
    def test_no_observed_click_is_not_equivalent_to_failed_click(self):
        data = {"arm_state": "ARMED", "attributes": attr(),
                "checkpoints": {"AFTER_SETTLE": snap(events=[])}}
        self.assertEqual(classify_option_purpose(
            data, server_region="OTHER", visible_control="OTHER_VISIBLE"),
            "CLICK_EVENT_NOT_SEEN")

    def test_click_received_but_no_locality_commit(self):
        data = {"arm_state": "ARMED", "attributes": attr(),
                "checkpoints": {"AFTER_SETTLE": snap()}}
        self.assertEqual(classify_option_purpose(
            data, server_region="OTHER", visible_control="OTHER_VISIBLE"),
            "CLICK_DELIVERED_NO_COMMIT")
        self.assertEqual(classify_option_purpose(
            data, server_region="EXPECTED", visible_control="TARGET_VISIBLE"),
            "COMMIT_CORROBORATED_DIAGNOSTIC")

    def test_new_dialog_or_expansion_suggests_another_step_but_not_authority(self):
        data = {"arm_state": "ARMED", "attributes": attr(),
                "checkpoints": {"AFTER_SETTLE": snap(added_dialogs=1)}}
        self.assertEqual(classify_option_purpose(
            data, server_region="OTHER", visible_control="OTHER_VISIBLE"),
            "SECOND_STAGE_SIGNAL")
        data["checkpoints"]["AFTER_SETTLE"] = snap(expanded="TRUE")
        self.assertEqual(classify_option_purpose(
            data, server_region="OTHER", visible_control="OTHER_VISIBLE"),
            "SECOND_STAGE_SIGNAL")
        # Re-rendered buttons alone do NOT prove another actionable UI step.
        data["checkpoints"]["AFTER_SETTLE"] = snap(added_buttons=7)
        self.assertEqual(classify_option_purpose(
            data, server_region="OTHER", visible_control="OTHER_VISIBLE"),
            "CLICK_DELIVERED_NO_COMMIT")

    def test_missing_arm_stays_unobservable(self):
        self.assertEqual(classify_option_purpose(
            {"arm_state": "NOT_OBSERVABLE", "checkpoints": {
                "AFTER_SETTLE": snap()}}, server_region="EXPECTED",
            visible_control="TARGET_VISIBLE"), "NOT_OBSERVABLE")

    def test_double_sanitization_is_idempotent_and_private(self):
        raw = {"arm_state": "ARMED", "attributes": attr(),
               "checkpoints": {
                   "AFTER_CLICK": snap(),
                   "AFTER_SETTLE": snap(added_buttons=2)},
               "purpose": "CLICK_DELIVERED_NO_COMMIT",
               "raw_HTML": "<script>SECRET_PERSONAL_TOKEN</script>",
               "authorizes_listings": True}
        once = sanitize_option_event(raw)
        twice = sanitize_option_event(once)
        self.assertEqual(once, twice)
        self.assertFalse(twice["authorizes_listings"])
        self.assertEqual(twice["checkpoints"]["AFTER_SETTLE"]["added_buttons"], 2)
        self.assertNotIn("SECRET_PERSONAL_TOKEN", json.dumps(twice))
        self.assertNotIn("raw_HTML", json.dumps(twice))

    def test_untrusted_strings_and_overflow_never_leave_sanitizer(self):
        injected = {
            "attributes": {"role": "SECRET_USER_REGION", "haspopup": "__SECRET__",
                           "aria_label_relation": "http://seller.example/private",
                           "inside_form": "yes", "native_disabled": True},
            "checkpoints": {"AFTER_SETTLE": {
                "click_trusted": "seller-private",
                "events": ["CLICK_TARGET", "https://secret.example/token"],
                "added_buttons": 2000,
                "target_connected": "SECRET_ID",
                "attribute_mutations": -20,
            }},
            "purpose": "http://example.com/user_token",
        }
        safe = sanitize_option_event(injected)
        blob = json.dumps(safe)
        for bad in ("SECRET", "seller", "https:", "private", "token", "USER_REGION"):
            self.assertNotIn(bad, blob)
        self.assertEqual(safe["checkpoints"]["AFTER_SETTLE"]["events"],
                         ["CLICK_TARGET"])
        self.assertEqual(safe["checkpoints"]["AFTER_SETTLE"]["added_buttons"], -1)
        self.assertEqual(safe["attributes"]["role"], "UNOBSERVABLE")
        self.assertEqual(safe["purpose"], "NOT_OBSERVABLE")

    def test_nested_navigation_report_drops_unknown_dom_data(self):
        row = sanitize_navigation_trace({
            "option_event": {
                "arm_state": "ARMED",
                "attributes": attr(),
                "checkpoints": {"AFTER_SETTLE": snap()},
                "purpose": "CLICK_DELIVERED_NO_COMMIT",
                "unknown_listing": "https://private.example/seller"},
            "events": [], "event_count": 0,
        })
        self.assertEqual(row["option_event"]["purpose"],
                         "CLICK_DELIVERED_NO_COMMIT")
        self.assertEqual(sanitize_navigation_trace(row), row)
        self.assertNotIn("private.example", str(row))


class FakeLocator:
    def __init__(self):
        self.calls = 0

    async def evaluate(self, script, arg):
        self.calls += 1
        self.script = script
        self.meta = arg
        return attr()


class FakePage:
    def __init__(self):
        self.stopped = False
        self.checkpoints = [snap(), snap(added_buttons=1)]

    async def evaluate(self, script):
        if "stop" in script:
            self.stopped = True
            return True
        return self.checkpoints.pop(0)


class OptionWatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_arm_only_exact_locator_and_capture_without_additional_click(self):
        watcher = RegionOptionEventWitness(BY_KEY["cheonan"])
        locator, page = FakeLocator(), FakePage()
        await watcher.arm(locator)
        self.assertEqual(locator.calls, 1)
        self.assertEqual(locator.meta["term"], "불당동")
        await watcher.checkpoint(page, "AFTER_CLICK")
        await watcher.checkpoint(page, "AFTER_SETTLE")
        result = watcher.export(server_region="OTHER", visible_control="OTHER_VISIBLE")
        self.assertEqual(result["arm_state"], "ARMED")
        self.assertEqual(result["purpose"], "CLICK_DELIVERED_NO_COMMIT")
        self.assertEqual(result["checkpoints"]["AFTER_CLICK"]["events"][-1],
                         "CLICK_DOCUMENT")
        self.assertEqual(result["checkpoints"]["AFTER_SETTLE"]["added_buttons"], 1)
        await watcher.stop(page)
        self.assertTrue(page.stopped)


class PublicFailureReportTests(unittest.TestCase):
    def test_fixed_enums_not_page_content_in_redacted_failure_log(self):
        with TemporaryDirectory() as td:
            folder = Path(td)
            event = sanitize_option_event({
                "arm_state": "ARMED",
                "attributes": attr(),
                "checkpoints": {"AFTER_CLICK": snap(),
                                "AFTER_SETTLE": snap(added_buttons=3)},
                "purpose": "CLICK_DELIVERED_NO_COMMIT"})
            data = {"evaluation": {"contexts": [{
                "context": "cheonan_a", "capture_failure_code":
                    "FRESH_REGION_PROOF_MISSING",
                "region_picker": {"navigation_trace": {
                    "option_event": {**event, "secret_url": "PRIVATE_SECRET_URL"}}}
            }]}}
            (folder / "v423_public_controls_results.json").write_text(
                json.dumps(data), encoding="utf-8")
            output = classify(folder)
            self.assertEqual(output["OPTION_EVENT_PURPOSE"],
                             "CLICK_DELIVERED_NO_COMMIT")
            self.assertEqual(output["OPTION_EVENT_ARM_STATE"], "ARMED")
            self.assertEqual(output["OPTION_ATTR_HASPOPUP"], "MISSING")
            self.assertEqual(output["OPTION_AFTER_SETTLE_ADDED_BUTTONS"], "3")
            self.assertEqual(output["OPTION_AFTER_SETTLE_EVENTS"],
                             "POINTER_DOWN,POINTER_UP,CLICK_TARGET,CLICK_DOCUMENT")
            self.assertEqual(output["OPTION_EVENT_AUTHORIZES_LISTINGS"], "NO")
            self.assertNotIn("PRIVATE_SECRET_URL", str(output))


if __name__ == "__main__":
    unittest.main()
