# -*- coding: utf-8 -*-
"""Synthetic-only picker-transition tests: no website calls or raw listings."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import daangn_v4_1_core as core
from app_v5.region_transition import (
    classify_picker_transition, classify_filter_transition,
    sanitize_picker_transition,
)
from scripts.report_v434_failure import classify

REGION = core.BY_KEY["cheonan"]
STEPS = {
    "selected_suggestion": True, "option_metadata": "OBSERVED",
    "option_city_hint": True, "option_exact_term": False,
    "option_data_id": "MISSING", "option_still_visible": False,
}


def event(sid="2292", fid="2292", name="불당동"):
    return {
        "status": 200,
        "public_request": {"valid": True, "public_params": {"q": "HDD"}},
        "model": {"region_id": sid, "filter_region_id": fid,
                  "search_region_name": name},
    }


class PickerTransitionTests(unittest.TestCase):
    def test_fresh_server_region_match_is_diagnostic_only(self):
        result = classify_picker_transition(REGION, STEPS, [event()],
                                            fetch_count=1)
        self.assertEqual(result["post_click_route_status"],
                         "FRESH_ROUTE_OBSERVED")
        self.assertEqual(result["search_region_state"], "EXPECTED")
        self.assertEqual(result["filter_region_state"], "EXPECTED")
        self.assertEqual(result["server_name_state"], "EXACT")
        self.assertNotIn("verified", result)
        self.assertEqual(classify_filter_transition(result, {
            "last_route_search_region_state": "EXPECTED",
            "last_route_filter_region_state": "EXPECTED",
        }), "EXPECTED_REGION_PERSISTED")

    def test_picker_wrong_before_filter_is_not_id_drift_authority(self):
        result = classify_picker_transition(REGION, STEPS, [
            event("900001", "900001", "다른지역")], fetch_count=1)
        self.assertEqual(result["search_region_state"], "OTHER")
        self.assertEqual(result["filter_region_state"], "OTHER")
        self.assertEqual(result["server_ids_agree"], "YES")
        self.assertEqual(result["server_name_state"], "OTHER")
        self.assertEqual(classify_filter_transition(result, {
            "last_route_search_region_state": "OTHER",
            "last_route_filter_region_state": "OTHER",
        }), "REGION_NOT_VERIFIED_AFTER_CLICK")
        self.assertNotIn("900001", str(result))
        self.assertNotIn("다른지역", str(result))

    def test_filter_apply_resets_previously_verified_picker(self):
        result = classify_picker_transition(REGION, STEPS, [event()],
                                            fetch_count=1)
        relation = classify_filter_transition(result, {
            "last_route_search_region_state": "OTHER",
            "last_route_filter_region_state": "OTHER",
        })
        self.assertEqual(relation, "REGION_LOST_AT_FILTER_APPLY")

    def test_no_postclick_fetch_is_unknown_not_silent_success(self):
        result = classify_picker_transition(REGION, STEPS, [], fetch_count=0)
        self.assertEqual(result["post_click_route_status"], "NO_FRESH_ROUTE")
        self.assertEqual(classify_filter_transition(result, {}),
                         "POST_CLICK_ROUTE_NOT_OBSERVABLE")

    def test_two_postclick_responses_remain_ambiguous(self):
        result = classify_picker_transition(REGION, STEPS,
                                            [event(), event()], fetch_count=2)
        self.assertEqual(result["post_click_route_status"],
                         "AMBIGUOUS_FRESH_ROUTES")

    def test_click_failure_cannot_produce_positive_transition(self):
        result = classify_picker_transition(
            REGION, {"selected_suggestion": False}, [event()], fetch_count=1)
        self.assertEqual(result["post_click_route_status"],
                         "SELECTION_NOT_CONFIRMED")

    def test_public_sanitizer_never_echoes_attacker_strings_or_ids(self):
        sample = {
            **classify_picker_transition(REGION, STEPS,
                                         [event("888888", "888888")]),
            "search_region_state": "888888",
            "filter_apply_relation": "secrets://private",
            "raw_url": "https://example.com/sensitive?token=secret",
            "post_click_model_count": 800,
            "option_city_hint": "yes",
        }
        safe = sanitize_picker_transition(sample)
        encoded = json.dumps(safe, ensure_ascii=False)
        for bad in ("888888", "secrets://", "token=", "raw_url"):
            self.assertNotIn(bad, encoded)
        self.assertEqual(safe["search_region_state"], "UNKNOWN")
        self.assertEqual(safe["post_click_model_count"], -1)
        self.assertFalse(safe["option_city_hint"])

    def test_public_failure_script_prints_only_allowlisted_transition(self):
        with TemporaryDirectory() as temp:
            folder = Path(temp)
            diag = classify_picker_transition(REGION, STEPS, [event()],
                                             fetch_count=1)
            diag["filter_apply_relation"] = "REGION_LOST_AT_FILTER_APPLY"
            diag["raw_secret"] = "SECRET_NEVER_PRINT"
            data = {"evaluation": {"contexts": [
                {"context": "cheonan_a", "capture_failure_code":
                 "FRESH_REGION_PROOF_MISSING",
                 "region_picker": {"transition": diag}}
            ]}}
            (folder / "v423_public_controls_results.json").write_text(
                json.dumps(data), encoding="utf-8")
            output = classify(folder)
            self.assertEqual(output["PICKER_POST_CLICK_ROUTE_STATUS"],
                             "FRESH_ROUTE_OBSERVED")
            self.assertEqual(output["PICKER_FILTER_APPLY_TRANSITION"],
                             "REGION_LOST_AT_FILTER_APPLY")
            self.assertNotIn("SECRET_NEVER_PRINT", str(output))


if __name__ == "__main__":
    unittest.main()
