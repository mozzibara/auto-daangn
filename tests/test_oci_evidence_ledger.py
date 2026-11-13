# -*- coding: utf-8 -*-
"""Offline regression for non-admitting OCI filter evidence ledger.

Represents the owner's actual FILL/V2 observation using finite verdicts,
not raw URLs, product records or browser network traffic.
"""
from __future__ import annotations

import copy
import json
import unittest

from app_v5.oci_evidence_ledger import summarize_precollection_evidence
from app_v5.precollection_filter_gate import sanitize_precollection


def actual_observation():
    return {
        "status": "BLOCKED_FILTER_URL",
        "region_gate_confirmed": True,
        "ui_selected_before_apply": True,
        "ui_selected_after_apply": False,
        "ui_after_apply_recheck_state": "NOT_RUN",
        "filter_apply_returned": True,
        "filtered_url_matches": False,
        "filtered_url_diagnostics": {
            "shape": "FIRST_PARTY_SEARCH",
            "fields": {
                "keyword": "EXPECTED", "region": "MISSING",
                "category": "EXPECTED", "price_max": "EXPECTED",
                "available": "EXPECTED",
            },
            "unexpected_keys": 0,
        },
        "filter_transport_diagnostics": {
            "search_requests": 1, "search_fetch_requests": 1,
            "search_responses": 1, "search_response_200": 1,
            "search_response_restricted": 0, "search_request_failures": 0,
        },
        "apply_search_request_diagnostics": {
            "observation": "ONE_OBSERVED",
            "transport": "FETCH_OR_XHR", "method": "GET",
            "outcome": "HTTP_200",
            "request_url": {
                "shape": "FIRST_PARTY_SEARCH",
                "fields": {
                    "keyword": "EXPECTED", "region": "MISSING",
                    "category": "EXPECTED", "price_max": "EXPECTED",
                    "available": "EXPECTED",
                },
                "unexpected_keys": 1,
            },
            "response_url": {
                "shape": "FIRST_PARTY_SEARCH",
                "fields": {
                    "keyword": "EXPECTED", "region": "MISSING",
                    "category": "EXPECTED", "price_max": "EXPECTED",
                    "available": "EXPECTED",
                },
                "unexpected_keys": 1,
            },
        },
        "dynamic_loader_metadata_mode": True,
        "dynamic_loader_metadata_count": 1,
        "dynamic_loader_metadata_status": "ONE_PARSED",
        "dynamic_loader_price_shape": "UNTRUSTED_PRICE_ONLY",
        "dynamic_loader_price_echo": "ENCODED_MAX_MATCH",
        "dynamic_loader_server_filters": {
            "region": "EXPECTED", "category": "EXPECTED",
            "available": "EXPECTED", "price_max": "MISSING",
        },
        "authorizes_listings": True,  # deliberate attempted injection
        "collection_started": True,
        "database_written": True,
        "seller": "PRIVATE_SELLER",
        "raw_response": "PRIVATE_HTTP_BODY",
    }


class ActualEvidenceTests(unittest.TestCase):
    def test_user_oci_result_identifies_three_independent_gaps(self):
        safe = sanitize_precollection(actual_observation())
        ledger = safe["evidence_ledger"]
        self.assertEqual(ledger["region_selection"], "SERVER_CONFIRMED")
        self.assertEqual(ledger["apply_request"],
                         "SINGLE_MATCHING_SEARCH_HTTP_200")
        self.assertEqual(ledger["filtered_server_metadata"], {
            "region": "EXPECTED", "category": "EXPECTED",
            "available": "EXPECTED",
        })
        self.assertEqual(ledger["response_price_evidence"],
                         "ENCODED_ECHO_MATCH_ONLY")
        self.assertEqual(ledger["backend_price_enforcement"], "NOT_PROVEN")
        self.assertEqual(ledger["url_region"], "MISSING")
        self.assertEqual(ledger["post_apply_ui"], "NOT_RUN")
        self.assertEqual(ledger["remaining_independent_gaps"], [
            "URL_REGION_NOT_VERIFIED",
            "BACKEND_PRICE_ENFORCEMENT_UNPROVEN",
            "POST_APPLY_UI_NOT_VERIFIED",
        ])
        self.assertEqual(ledger["same_scope_repeat"],
                         "ECHO_ONLY_CANNOT_PROVE_ENFORCEMENT")
        self.assertFalse(ledger["authorizes_listings"])
        self.assertFalse(safe["authorizes_listings"])
        self.assertFalse(safe["collection_started"])
        self.assertFalse(safe["database_written"])
        self.assertNotIn("PRIVATE", json.dumps(safe))
        self.assertEqual(sanitize_precollection(safe), safe)

    def test_direct_max_response_match_is_still_not_behavioral_proof(self):
        raw = actual_observation()
        raw["dynamic_loader_price_shape"] = "DIRECT_ALIAS"
        raw["dynamic_loader_server_filters"]["price_max"] = "EXPECTED"
        evidence = sanitize_precollection(raw)["evidence_ledger"]
        self.assertEqual(evidence["response_price_evidence"],
                         "DECLARED_MAX_MATCH")
        self.assertEqual(evidence["backend_price_enforcement"],
                         "NOT_PROVEN")
        self.assertFalse(evidence["authorizes_listings"])

    def test_nested_max_response_match_is_still_not_backend_proof(self):
        raw = actual_observation()
        raw["dynamic_loader_price_shape"] = "NESTED_PRICE_RANGE_MAX"
        raw["dynamic_loader_server_filters"]["price_max"] = "EXPECTED"
        evidence = sanitize_precollection(raw)["evidence_ledger"]
        self.assertEqual(evidence["response_price_evidence"],
                         "DECLARED_MAX_MATCH")
        self.assertIn("BACKEND_PRICE_ENFORCEMENT_UNPROVEN",
                      evidence["remaining_independent_gaps"])

    def test_wrong_server_max_trumps_matching_price_echo(self):
        raw = actual_observation()
        raw["dynamic_loader_price_shape"] = "DIRECT_ALIAS"
        raw["dynamic_loader_server_filters"]["price_max"] = "OTHER"
        evidence = sanitize_precollection(raw)["evidence_ledger"]
        self.assertEqual(evidence["response_price_evidence"],
                         "DECLARED_MAX_MISMATCH")
        self.assertFalse(evidence["authorizes_listings"])

    def test_mismatched_echo_is_not_silent_success(self):
        raw = actual_observation()
        raw["dynamic_loader_price_echo"] = "ENCODED_MAX_OTHER"
        evidence = sanitize_precollection(raw)["evidence_ledger"]
        self.assertEqual(evidence["response_price_evidence"],
                         "ENCODED_ECHO_MISMATCH")
        self.assertFalse(evidence["authorizes_listings"])

    def test_bad_echo_value_is_never_exported(self):
        raw = actual_observation()
        raw["dynamic_loader_price_echo"] = "PRIVATE_VALUE_SECRET"
        evidence = sanitize_precollection(raw)["evidence_ledger"]
        self.assertEqual(evidence["response_price_evidence"],
                         "ENCODED_ECHO_UNRECOGNIZED")
        self.assertNotIn("PRIVATE", json.dumps(evidence))

    def test_unknown_price_source_is_not_independent_max(self):
        raw = actual_observation()
        raw["dynamic_loader_price_shape"] = "ABSENT"
        evidence = sanitize_precollection(raw)["evidence_ledger"]
        self.assertEqual(evidence["response_price_evidence"],
                         "NO_INDEPENDENT_MAX")

    def test_multiple_price_sources_remain_ambiguous(self):
        raw = actual_observation()
        raw["dynamic_loader_price_shape"] = "MULTIPLE_PRICE_SOURCES"
        raw["dynamic_loader_server_filters"]["price_max"] = "AMBIGUOUS"
        evidence = sanitize_precollection(raw)["evidence_ledger"]
        self.assertEqual(evidence["response_price_evidence"],
                         "DECLARED_MAX_AMBIGUOUS")


class CompetingEvidenceTests(unittest.TestCase):
    def test_multiple_requests_no_favorable_picking(self):
        raw = actual_observation()
        raw["filter_transport_diagnostics"]["search_requests"] = 2
        evidence = sanitize_precollection(raw)["evidence_ledger"]
        self.assertEqual(evidence["apply_request"],
                         "NOT_PROVEN_UNIQUE_MATCHING")
        self.assertEqual(evidence["filtered_server_metadata"], {
            "region": "UNVERIFIED", "category": "UNVERIFIED",
            "available": "UNVERIFIED",
        })
        self.assertEqual(evidence["response_price_evidence"], "UNVERIFIED")
        self.assertEqual(evidence["same_scope_repeat"], "UNDETERMINED")

    def test_http_403_does_not_qualify_positive_filter_metadata(self):
        raw = actual_observation()
        raw["apply_search_request_diagnostics"]["outcome"] = "ACCESS_RESTRICTED"
        raw["filter_transport_diagnostics"]["search_response_200"] = 0
        raw["filter_transport_diagnostics"]["search_response_restricted"] = 1
        evidence = sanitize_precollection(raw)["evidence_ledger"]
        self.assertEqual(evidence["apply_request"],
                         "NOT_PROVEN_UNIQUE_MATCHING")
        self.assertEqual(evidence["response_price_evidence"], "UNVERIFIED")
        self.assertFalse(evidence["authorizes_listings"])

    def test_missing_approval_mode_cannot_promote_fields(self):
        raw = actual_observation()
        raw["dynamic_loader_metadata_mode"] = False
        evidence = sanitize_precollection(raw)["evidence_ledger"]
        self.assertEqual(evidence["filtered_server_metadata"]["region"],
                         "UNVERIFIED")
        self.assertEqual(evidence["response_price_evidence"], "UNVERIFIED")

    def test_unverified_request_url_does_not_promote_response(self):
        raw = actual_observation()
        raw["apply_search_request_diagnostics"]["request_url"][
            "fields"]["price_max"] = "OTHER"
        evidence = sanitize_precollection(raw)["evidence_ledger"]
        self.assertEqual(evidence["apply_request"],
                         "NOT_PROVEN_UNIQUE_MATCHING")
        self.assertEqual(evidence["response_price_evidence"], "UNVERIFIED")

    def test_ui_match_and_present_in_still_not_automatic_collection(self):
        raw = actual_observation()
        raw["filtered_url_diagnostics"]["fields"]["region"] = "EXPECTED"
        raw["ui_after_apply_recheck_state"] = "OBSERVED_MATCH"
        evidence = sanitize_precollection(raw)["evidence_ledger"]
        self.assertEqual(evidence["remaining_independent_gaps"],
                         ["BACKEND_PRICE_ENFORCEMENT_UNPROVEN"])
        self.assertEqual(evidence["backend_price_enforcement"], "NOT_PROVEN")
        self.assertFalse(evidence["authorizes_listings"])


class StructuralSafetyTests(unittest.TestCase):
    def test_empty_input_is_safe_without_implied_region_confirmation(self):
        safe = sanitize_precollection(None)
        evidence = safe["evidence_ledger"]
        self.assertEqual(evidence["region_selection"], "UNVERIFIED")
        self.assertEqual(evidence["apply_request"],
                         "NOT_PROVEN_UNIQUE_MATCHING")
        self.assertEqual(evidence["response_price_evidence"], "UNVERIFIED")
        self.assertFalse(evidence["authorizes_listings"])
        self.assertEqual(sanitize_precollection(safe), safe)

    def test_forged_evidence_ledger_is_not_preserved(self):
        raw = actual_observation()
        raw["evidence_ledger"] = {
            "authorizes_listings": True,
            "backend_price_enforcement": "PROVEN",
            "raw_session": "PRIVATE_COOKIE",
        }
        safe = sanitize_precollection(raw)
        evidence = safe["evidence_ledger"]
        self.assertEqual(evidence["backend_price_enforcement"], "NOT_PROVEN")
        self.assertFalse(evidence["authorizes_listings"])
        self.assertNotIn("PRIVATE", json.dumps(safe))

    def test_pure_helper_always_recomputes_from_sanitized_input(self):
        safe = sanitize_precollection(actual_observation())
        self.assertEqual(summarize_precollection_evidence(safe),
                         safe["evidence_ledger"])


if __name__ == "__main__":
    unittest.main()
