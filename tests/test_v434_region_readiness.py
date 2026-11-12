# -*- coding: utf-8 -*-
"""Synthetic, offline readiness and privacy regressions; no web traffic."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app_v5.region_readiness import (
    RegionReadinessWitness, sanitize_readiness,
)
from app_v5.region_navigation import sanitize_navigation_trace
from daangn_v4_1_core import BY_KEY, ui_select_region
from scripts.report_v434_failure import classify

REGION = BY_KEY["cheonan"]


def snap(*, buttons=47, target=1, city=1, changes=2):
    return {"candidate_buttons": buttons, "target_buttons": target,
            "target_city_buttons": city, "dom_mutations": changes,
            "url": "https://private.example/SECRET"}


class FakeResolver:
    def __init__(self, *, events=None, responses=1, blocked=False):
        self.events = ([{"state": "OBSERVED", "matches": [str(REGION["id"])]}]
                       if events is None else events)
        self.responses = responses
        self.blocked = blocked


class FakeDOM:
    def __init__(self, *samples, arm=True):
        self.samples = list(samples or (snap(), snap(), snap()))
        self.arm = arm
        self.observed = []
        self.cleaned = False

    async def evaluate(self, script, arg=None):
        self.observed.append(("script", arg))
        if "observer.observe" in script:
            return {"armed": self.arm, "snapshot": snap() if self.arm else None}
        if "snapshot?.()" in script:
            return self.samples.pop(0) if self.samples else snap()
        if "stop" in script:
            self.cleaned = True
            return True
        raise AssertionError("Unexpected browser evaluation")


class ReadinessGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_unique_expected_api_plus_three_stable_samples(self):
        dom = FakeDOM(snap(), snap(), snap())
        witness = RegionReadinessWitness(REGION, FakeResolver())
        row = await witness.await_ready(dom, timeout_seconds=1,
                                       interval_seconds=0.005)
        self.assertEqual(row["state"], "READY")
        self.assertTrue(row["dom_stable"])
        self.assertTrue(row["api_unique_candidate"])
        self.assertTrue(row["api_expected_id"])
        self.assertEqual(row["stable_samples"], 3)
        self.assertEqual(row["snapshots"]["FINAL"]["candidate_buttons"], 47)
        self.assertTrue(dom.cleaned)
        self.assertFalse(row["authorizes_listings"])
        self.assertNotIn("SECRET", str(row))

    async def test_mutation_resets_stability_streak(self):
        dom = FakeDOM(snap(changes=2), snap(changes=3), snap(changes=3),
                      snap(changes=3))
        witness = RegionReadinessWitness(REGION, FakeResolver())
        row = await witness.await_ready(dom, timeout_seconds=1,
                                       interval_seconds=0.005)
        self.assertEqual(row["state"], "READY")
        self.assertEqual(row["snapshots"]["FINAL"]["dom_mutations"], 3)
        self.assertTrue(dom.cleaned)

    async def test_wrong_api_id_must_never_start_dom_probe(self):
        dom = FakeDOM()
        observer = FakeResolver(events=[
            {"state": "OBSERVED", "matches": ["999999"]}])
        row = await RegionReadinessWitness(
            REGION, observer).await_ready(dom, timeout_seconds=0.1)
        self.assertEqual(row["state"], "API_ID_MISMATCH")
        self.assertFalse(row["dom_stable"])
        self.assertEqual(len([x for x in dom.observed if x[1] is not None]), 0)
        self.assertTrue(dom.cleaned)

    async def test_ambiguous_or_blocked_api_is_rejected(self):
        for api, expected in (
            (FakeResolver(responses=2), "API_NOT_UNIQUE"),
            (FakeResolver(events=[{"state": "SCHEMA_NOT_RECOGNIZED"}]),
             "API_SCHEMA_UNKNOWN"),
            (FakeResolver(events=[], responses=0, blocked=True), "API_BLOCKED"),
        ):
            with self.subTest(expected=expected):
                row = await RegionReadinessWitness(
                    REGION, api).await_ready(FakeDOM(), timeout_seconds=0.05)
                self.assertEqual(row["state"], expected)
                self.assertFalse(row["dom_stable"])

    async def test_no_api_response_times_out(self):
        dom = FakeDOM()
        row = await RegionReadinessWitness(
            REGION, FakeResolver(events=[], responses=0)).await_ready(
                dom, timeout_seconds=0.04)
        self.assertEqual(row["state"], "API_TIMEOUT")
        self.assertTrue(dom.cleaned)

    async def test_ambiguous_dom_remains_blocked_until_timeout(self):
        dom = FakeDOM(*(snap(target=2, city=2) for _ in range(10)))
        row = await RegionReadinessWitness(
            REGION, FakeResolver()).await_ready(
                dom, timeout_seconds=0.09, interval_seconds=0.01)
        self.assertEqual(row["state"], "DOM_AMBIGUOUS")
        self.assertFalse(row["dom_stable"])
        self.assertTrue(dom.cleaned)

    async def test_missing_or_detached_dialog_never_ready(self):
        row = await RegionReadinessWitness(
            REGION, FakeResolver()).await_ready(
                FakeDOM(arm=False), timeout_seconds=0.1)
        self.assertEqual(row["state"], "DOM_NOT_FOUND")

    def test_twice_sanitized_nested_boundary_never_reveals_web_content(self):
        malicious = {
            "pre_click_readiness": {
                "state": "READY",
                "api_response_count": 1, "api_unique_candidate": True,
                "api_expected_id": True, "dom_stable": True,
                "stable_samples": 3,
                "snapshots": {"INITIAL": {**snap(), "raw_html": "SECRET_TOKEN"},
                              "FINAL": snap()},
                "listing_url": "https://private.example/abc",
                "authorizes_listings": True,
            }
        }
        first = sanitize_navigation_trace(malicious)
        second = sanitize_navigation_trace(first)
        self.assertEqual(first, second)
        row = second["pre_click_readiness"]
        self.assertTrue(row["dom_stable"])
        self.assertFalse(row["authorizes_listings"])
        self.assertNotIn("SECRET", json.dumps(second))
        self.assertNotIn("private.example", json.dumps(second))
        self.assertEqual(row["snapshots"]["FINAL"]["target_city_buttons"], 1)

    def test_invalid_states_and_overflow_drop_to_unknown(self):
        row = sanitize_readiness({
            "state": "PRIVATE_USER_ADDRESS", "api_response_count": 900,
            "stable_samples": 22, "snapshots": {"FINAL":
                {"candidate_buttons": 500, "target_buttons": "SECRET",
                 "dom_mutations": -5}}})
        self.assertEqual(row["state"], "NOT_RUN")
        self.assertEqual(row["stable_samples"], -1)
        self.assertEqual(row["snapshots"]["FINAL"]["candidate_buttons"], -1)
        self.assertNotIn("SECRET", str(row))


class CoreCallbackTests(unittest.IsolatedAsyncioTestCase):
    class Locator:
        def __init__(self):
            self.clicks = 0
            self.presses = 0
            self.fills = 0
            self.sequential = 0
            self.value = ""

        @property
        def first(self):
            return self

        def filter(self, **kwargs):
            return self

        async def count(self):
            return 1

        async def is_visible(self):
            return True

        async def fill(self, val, **kwargs):
            self.fills += 1
            self.value = val

        async def input_value(self):
            return self.value

        async def press_sequentially(self, value, **kwargs):
            self.sequential += 1
            self.value += value

        async def click(self, **kwargs):
            self.clicks += 1

        async def is_enabled(self):
            return True

        async def press(self, key, **kwargs):
            assert key == "Enter"
            self.presses += 1

        async def evaluate(self, *args):
            return {"option_metadata": "OBSERVED", "option_tag": "BUTTON"}

    class Page:
        url = "https://www.daangn.com/kr/search/buy-sell/?q=HDD"

        def __init__(self):
            self.top = CoreCallbackTests.Locator()
            self.input = CoreCallbackTests.Locator()
            self.option = CoreCallbackTests.Locator()

        def get_by_role(self, *args, **kwargs):
            return self.top

        def locator(self, selector):
            return self.input if "input[placeholder" in selector else self.option

        async def wait_for_timeout(self, ms):
            pass

    async def test_api_stable_hook_runs_after_fill_before_click(self):
        page = self.Page()
        steps = []

        async def ready():
            steps.append((page.input.fills, page.option.clicks))
            return {"state": "READY"}

        r = await ui_select_region(
            page, REGION, on_after_search_fill=ready)
        self.assertTrue(r["selected_suggestion"])
        self.assertEqual(steps, [(1, 0)])
        self.assertEqual(page.option.clicks, 1)

    async def test_manual_style_sequential_input_and_first_pointer_click(self):
        page = self.Page()
        steps = []
        async def ready():
            steps.append((page.input.value, page.input.sequential,
                          page.input.fills, page.option.clicks))
            return {"state": "READY"}
        result = await ui_select_region(
            page, REGION, search_input_mode="SEQUENTIAL_KEYS",
            first_activation_mode="POINTER_CLICK",
            on_after_search_fill=ready)
        self.assertTrue(result["selected_suggestion"])
        self.assertEqual(result["search_input_mode"], "SEQUENTIAL_KEYS")
        self.assertEqual(result["first_activation_mode"], "POINTER_CLICK")
        self.assertEqual(page.input.value, REGION["term"])
        self.assertEqual(page.input.sequential, 1)
        self.assertEqual(page.input.fills, 0)
        self.assertEqual(page.option.clicks, 1)
        self.assertEqual(steps, [(REGION["term"], 1, 0, 0)])

    async def test_sequential_input_rejects_nonempty_existing_text(self):
        page = self.Page()
        page.input.value = "PRIVATE"
        result = await ui_select_region(
            page, REGION, search_input_mode="SEQUENTIAL_KEYS")
        self.assertEqual(result["error"], "region_input_not_empty_for_keys")
        self.assertFalse(result["selected_suggestion"])
        self.assertEqual(page.input.sequential, 0)
        self.assertEqual(page.option.clicks, 0)

    async def test_unsupported_input_mode_never_triggers_selector(self):
        page = self.Page()
        result = await ui_select_region(
            page, REGION, search_input_mode="DIRECT_API")
        self.assertEqual(result["error"], "unsupported_search_input_mode")
        self.assertFalse(result["selected_suggestion"])
        self.assertEqual(page.input.sequential, 0)
        self.assertEqual(page.input.fills, 0)
        self.assertEqual(page.option.clicks, 0)

    async def test_initial_native_enter_avoids_pointer_activation(self):
        page = self.Page()
        order = []

        async def before():
            order.append(("BEFORE", page.option.clicks, page.option.presses))

        async def after():
            order.append(("AFTER", page.option.clicks, page.option.presses))

        result = await ui_select_region(
            page, REGION, on_after_search_fill=lambda: {"state": "READY"},
            on_before_select=before, on_after_select=after,
            first_activation_mode="KEYBOARD_ENTER")
        self.assertTrue(result["selected_suggestion"])
        self.assertEqual(result["first_activation_mode"], "KEYBOARD_ENTER")
        self.assertEqual(page.option.presses, 1)
        self.assertEqual(page.option.clicks, 0)
        self.assertEqual(order, [("BEFORE", 0, 0), ("AFTER", 0, 1)])

    async def test_unsupported_activation_never_presses(self):
        page = self.Page()
        result = await ui_select_region(
            page, REGION, on_after_search_fill=lambda: {"state": "READY"},
            first_activation_mode="FORCE_JS_CLICK")
        self.assertEqual(result["error"], "unsupported_first_activation_mode")
        self.assertFalse(result["selected_suggestion"])
        self.assertEqual(page.option.clicks, 0)
        self.assertEqual(page.option.presses, 0)

    async def test_missing_or_ambiguous_api_never_clicks(self):
        for state in ("API_TIMEOUT", "API_NOT_UNIQUE", "DOM_NOT_STABLE"):
            with self.subTest(state=state):
                page = self.Page()
                r = await ui_select_region(
                    page, REGION,
                    on_after_search_fill=lambda: {"state": state})
                self.assertEqual(r["error"], "region_suggestion_not_ready")
                self.assertEqual(page.input.fills, 1)
                self.assertEqual(page.option.clicks, 0)


class RedactedReporterTests(unittest.TestCase):
    def test_preserves_only_categorical_readiness(self):
        with TemporaryDirectory() as td:
            folder = Path(td)
            payload = {"evaluation": {"contexts": [{
                "context": "cheonan_a",
                "capture_failure_code": "FRESH_REGION_PROOF_MISSING",
                "region_picker": {"navigation_trace": {
                    "pre_click_readiness": {
                        "state": "READY", "api_response_count": 1,
                        "api_unique_candidate": True,
                        "api_expected_id": True,
                        "dom_stable": True, "stable_samples": 3,
                        "snapshots": {"INITIAL": snap(changes=0),
                                      "FINAL": snap(changes=1)},
                        "user_private_listing": "SECRET"
                    },
                }},
            }]}}
            (folder / "v423_public_controls_results.json").write_text(
                json.dumps(payload), encoding="utf-8")
            row = classify(folder)
            self.assertEqual(row["READINESS_STATE"], "READY")
            self.assertEqual(row["READINESS_DOM_STABLE"], "YES")
            self.assertEqual(row["READINESS_FINAL_CANDIDATE_BUTTONS"], "47")
            self.assertEqual(row["READINESS_FINAL_DOM_MUTATIONS"], "1")
            self.assertEqual(row["READINESS_AUTHORIZES_LISTINGS"], "NO")
            self.assertNotIn("SECRET", json.dumps(row))


if __name__ == "__main__":
    unittest.main()
