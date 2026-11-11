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
    classify_early_region_gate, sanitize_picker_transition,
)
from scripts.report_v434_failure import classify
from daangn_state_controls_v4_23 import aggregate

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

    def test_exact_clicked_option_role_is_diagnostic_only(self):
        steps = {**STEPS, "option_tag": "BUTTON",
                 "option_role": "OPTION", "option_parent": "LISTBOX",
                 "option_aria_selected": "FALSE"}
        result = classify_picker_transition(REGION, steps, [event("90001", "90001")])
        self.assertEqual(result["option_tag"], "BUTTON")
        self.assertEqual(result["option_parent"], "LISTBOX")
        self.assertEqual(result["search_region_state"], "OTHER")
        self.assertNotIn("verified", result)
        safe = sanitize_picker_transition({**result,
               "option_role": "PRIVATE SECRET CLICK", "option_parent": "https://token.example/"})
        self.assertEqual(safe["option_role"], "UNKNOWN")
        self.assertEqual(safe["option_parent"], "UNKNOWN")
        self.assertNotIn("PRIVATE SECRET", str(safe))

    def test_independently_wrong_ui_and_fresh_server_stop_before_filter(self):
        other = classify_picker_transition(
            REGION, STEPS, [event("900001","900001","다른지역")],
            fetch_count=1)
        self.assertEqual(
            classify_early_region_gate(other, False),
            "OBSERVED_WRONG_REGION")
        self.assertEqual(
            classify_early_region_gate(other, None),
            "MIXED_OR_UNKNOWN")
        self.assertEqual(
            classify_early_region_gate(other, True),
            "MIXED_OR_UNKNOWN")
        expected = classify_picker_transition(
            REGION, STEPS, [event()], fetch_count=1)
        self.assertEqual(
            classify_early_region_gate(expected, True),
            "LOCALITY_CORROBORATED_DIAGNOSTIC")
        self.assertEqual(
            classify_early_region_gate(expected, False),
            "MIXED_OR_UNKNOWN")
        no_route = classify_picker_transition(
            REGION, STEPS, [], fetch_count=0)
        self.assertEqual(
            classify_early_region_gate(no_route, False),
            "NOT_OBSERVABLE")
        self.assertEqual(
            classify_early_region_gate({}, False),
            "NOT_OBSERVABLE")

    def test_true_aggregation_and_report_preserve_early_stop(self):
        row={
            "context":"cheonan_a",
            "error_type":"REGION_MISMATCH",
            "fresh_region_authority_status":"REGION_UI_NOT_VERIFIED",
            "region_picker":{
                "outcome":"EARLY_REGION_UNCOMMITTED",
                "early_gate":"OBSERVED_WRONG_REGION",
                "selected_region_button_visible":False,
                "navigation_trace":{},
                "private_unknown_field":"SECRET_OWNER_LISTING_URL",
            }
        }
        safe=aggregate([row])
        picked=safe["contexts"][0]["region_picker"]
        self.assertEqual(picked["outcome"],"EARLY_REGION_UNCOMMITTED")
        self.assertEqual(picked["early_gate"],"OBSERVED_WRONG_REGION")
        self.assertEqual(
            safe["contexts"][0]["fresh_region_authority_status"],
            "REGION_UI_NOT_VERIFIED")
        self.assertEqual(
            safe["contexts"][0]["capture_failure_code"],
            "REGION_MISMATCH")
        self.assertNotIn("SECRET_OWNER",json.dumps(safe))
        with TemporaryDirectory() as temp:
            folder=Path(temp)
            (folder/"v423_public_controls_results.json").write_text(
                json.dumps({"evaluation":safe}),encoding="utf-8")
            public=classify(folder)
            self.assertEqual(public["REGION_PICKER_OUTCOME"],
                             "EARLY_REGION_UNCOMMITTED")
            self.assertEqual(public["REGION_PICKER_EARLY_GATE"],
                             "OBSERVED_WRONG_REGION")
            self.assertEqual(public["FRESH_REGION_AUTHORITY_STATUS"],
                             "REGION_UI_NOT_VERIFIED")
            self.assertNotIn("SECRET_OWNER",str(public))

    def test_public_early_gate_report_does_not_approve_locality(self):
        with TemporaryDirectory() as temp:
            folder=Path(temp)
            payload={"evaluation":{"contexts":[{
                "context":"cheonan_a",
                "capture_failure_code":"REGION_MISMATCH",
                "region_picker":{
                    "outcome":"EARLY_REGION_UNCOMMITTED",
                    "early_gate":"OBSERVED_WRONG_REGION",
                    "navigation_trace":{},
                    "unknown_private_id":"MY_PRIVATE_REGION",
                },
            }]}}
            (folder/"v423_public_controls_results.json").write_text(
                json.dumps(payload),encoding="utf-8")
            row=classify(folder)
            self.assertEqual(row["REGION_PICKER_OUTCOME"],
                             "EARLY_REGION_UNCOMMITTED")
            self.assertEqual(row["REGION_PICKER_EARLY_GATE"],
                             "OBSERVED_WRONG_REGION")
            self.assertNotIn("MY_PRIVATE_REGION",str(row))

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

    def test_nonmatching_postclick_query_not_marked_fresh(self):
        unrelated = event()
        unrelated["public_request"]["public_params"]["q"] = "SSD"
        x = classify_picker_transition(REGION, STEPS, [unrelated], fetch_count=1)
        self.assertEqual(x["post_click_route_status"],
                         "POST_CLICK_QUERY_OR_ROUTE_INVALID")
        self.assertEqual(classify_filter_transition(x, {}),
                         "POST_CLICK_ROUTE_NOT_OBSERVABLE")

    def test_unparsed_search_response_is_distinct_from_no_fetch(self):
        x = classify_picker_transition(REGION, STEPS, [], fetch_count=1)
        self.assertEqual(x["post_click_route_status"], "UNPARSED_POST_CLICK_ROUTE")

    def test_missing_filter_route_does_not_claim_locality_reset(self):
        x = classify_picker_transition(REGION, STEPS, [event()], fetch_count=1)
        self.assertEqual(classify_filter_transition(x, {}),
                         "FILTER_APPLY_ROUTE_NOT_OBSERVABLE")

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
