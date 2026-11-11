# -*- coding: utf-8 -*-
"""Synthetic-only public failure reporter tests; never visits the marketplace."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.report_v434_failure import classify, main


class RedactedCaptureFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def put(self, file: str, content: dict):
        (self.folder / file).write_text(
            json.dumps(content, ensure_ascii=False), encoding="utf-8"
        )

    def test_preflight_robots_failure_is_classified_without_paths(self):
        self.put("v434_run_status.json", {
            "status": "STOP_ROBOTS_ROBOTS_UNAVAILABLE_HTTPError",
            "attempted_live": False,
            "secret": "do-not-disclose",
        })
        self.put("v434_robots_decision.json", {
            "allowed": False, "reason": "ROBOTS_UNAVAILABLE_HTTPError",
            "http_status": None, "checked_paths": ["/private/secret"],
        })
        result = classify(self.folder)
        self.assertEqual(result["CAPTURE_STATUS"], "STOP_ROBOTS")
        self.assertEqual(result["CAPTURE_ATTEMPTED_LIVE"], "NO")
        self.assertEqual(result["ROBOTS_REASON"], "ROBOTS_UNAVAILABLE_HTTPError")
        stream = StringIO()
        with redirect_stdout(stream):
            self.assertEqual(main(["--output-dir", str(self.folder)]), 0)
        output = stream.getvalue()
        self.assertIn("ROBOTS_REASON=ROBOTS_UNAVAILABLE_HTTPError", output)
        self.assertNotIn("/private", output)
        self.assertNotIn("do-not-disclose", output)

    def test_inner_capture_failure_reports_only_known_enums(self):
        self.put("v434_run_status.json", {
            "status": "INCONCLUSIVE_INCOMPLETE_SECURE_CAPTURE",
            "attempted_live": True,
        })
        self.put("v434_robots_decision.json", {
            "allowed": True, "reason": "ALLOWED", "http_status": 200,
        })
        self.put("v429_run_status.json", {
            "status": "INCONCLUSIVE_UPSTREAM_CAPTURE_FAILURE",
            "inner_secret": "should-not-appear",
        })
        self.put("v429_public_status_results.json", {
            "evaluation": {"status": "INCONCLUSIVE_INCOMPLETE_BOUNDED_CAPTURE"}
        })
        result = classify(self.folder)
        self.assertEqual(result["CAPTURE_ATTEMPTED_LIVE"], "YES")
        self.assertEqual(result["INNER_CAPTURE_STATUS"],
                         "INCONCLUSIVE_UPSTREAM_CAPTURE_FAILURE")
        self.assertEqual(result["SURVEY_STATUS"],
                         "INCONCLUSIVE_INCOMPLETE_BOUNDED_CAPTURE")
        self.assertEqual(result["ROBOTS_HTTP_STATUS"], "200")

    def test_untrusted_fields_are_never_printed(self):
        sensitive = "github_pat_EXAMPLE_DO_NOT_PRINT"
        self.put("v434_run_status.json", {
            "status": {"unexpected": sensitive},
            "attempted_live": sensitive,
        })
        self.put("v434_robots_decision.json", {
            "reason": [sensitive],
            "allowed": sensitive,
            "http_status": sensitive,
            "checked_paths": [sensitive],
        })
        self.put("v429_run_status.json", {"status": [sensitive]})
        self.put("v429_public_status_results.json", {
            "evaluation": {"status": {"bad": sensitive}}
        })
        stream = StringIO()
        with redirect_stdout(stream):
            self.assertEqual(main(["--output-dir", str(self.folder)]), 0)
        self.assertNotIn(sensitive, stream.getvalue())
        self.assertIn("CAPTURE_STATUS=UNAVAILABLE_OR_UNKNOWN", stream.getvalue())
        self.assertIn("ROBOTS_REASON=UNKNOWN", stream.getvalue())

    def test_incomplete_upstream_context_reports_safe_reason_only(self):
        self.put("v423_public_controls_results.json", {
            "evaluation": {
                "status": "INCONCLUSIVE_CONTROL_STUDY_INCOMPLETE",
                "contexts": [{
                    "context": "cheonan_a",
                    "capture_failure_code": "CORRELATED_ROUTE_MISSING",
                    "title": "private HDD seller name",
                    "raw_url": "https://example.org/private-url",
                }],
                "source_detail_visits": 0,
                "browser_capture_exception_types": {},
            }
        })
        result = classify(self.folder)
        self.assertEqual(result["UPSTREAM_CONTEXT_COUNT"], "1")
        self.assertEqual(result["UPSTREAM_CONTEXT_SEQUENCE"], "cheonan_a")
        self.assertEqual(result["UPSTREAM_FIRST_FAILURE_CODE"],
                         "CORRELATED_ROUTE_MISSING")
        self.assertEqual(result["UPSTREAM_EXPECTED_CONTEXTS_COMPLETE"], "NO")
        stream = StringIO()
        with redirect_stdout(stream):
            main(["--output-dir", str(self.folder)])
        self.assertNotIn("private HDD seller name", stream.getvalue())
        self.assertNotIn("example.org", stream.getvalue())

    def test_upstream_context_unknown_strings_redacted(self):
        secret = "github_pat_EXAMPLE_UNTRUSTED_STRING"
        self.put("v423_public_controls_results.json", {
            "evaluation": {
                "status": secret,
                "contexts": [{
                    "context": secret, "capture_failure_code": secret,
                }, {"context": "browser", "capture_failure_code": "BROWSER_EXCEPTION"}],
                "browser_capture_exception_types": {"STOP_Error": 1},
                "source_detail_visits": secret,
            }
        })
        output = classify(self.folder)
        self.assertEqual(output["UPSTREAM_CAPTURE_STATUS"], "UNAVAILABLE_OR_UNKNOWN")
        self.assertEqual(output["UPSTREAM_CONTEXT_SEQUENCE"], "UNKNOWN,browser")
        self.assertEqual(output["UPSTREAM_FIRST_FAILURE_CODE"], "BROWSER_EXCEPTION")
        self.assertEqual(output["UPSTREAM_SOURCE_VISITS"], "UNKNOWN")
        self.assertEqual(output["UPSTREAM_BROWSER_EXCEPTION_PRESENT"], "YES")
        self.assertNotIn(secret, str(output))

    def test_initial_region_redirect_classes_remain_public_safe(self):
        self.put("v423_public_controls_results.json", {
            "evaluation": {
                "status": "INCONCLUSIVE_CONTROL_STUDY_INCOMPLETE",
                "contexts": [{
                    "context": "cheonan_a",
                    "capture_failure_code": "REGION_MISMATCH",
                    "baseline_region_url_evidence": {
                        "requested": {"region": "EXPECTED"},
                        "response": {"region": "MISSING"},
                        "rendered": {
                            "region": "MISSING",
                            "host": "EXPECTED", "path": "EXPECTED",
                            "region_parameter": "MISSING",
                            "keyword": "EXPECTED",
                        },
                        "response_changed_from_request": True,
                        "rendered_changed_from_response": False,
                        "debug_private_url": "https://example.org/SECRET",
                    },
                }],
                "source_detail_visits": 0,
            }
        })
        out = classify(self.folder)
        self.assertEqual(out["BASELINE_REQUEST_REGION"], "EXPECTED")
        self.assertEqual(out["BASELINE_HTTP_REGION"], "MISSING")
        self.assertEqual(out["BASELINE_RENDERED_REGION"], "MISSING")
        self.assertEqual(out["BASELINE_HTTP_URL_CHANGED"], "YES")
        self.assertEqual(out["BASELINE_RENDERED_URL_CHANGED"], "NO")
        self.assertNotIn("SECRET", str(out))
        self.assertNotIn("example.org", str(out))

    def test_region_picker_reports_only_fixed_statuses(self):
        self.put("v423_public_controls_results.json", {
            "evaluation": {"contexts": [{
                "context": "cheonan_a",
                "capture_failure_code": "REGION_MISMATCH",
                "region_picker": {
                    "attempted": True,
                    "robots_permission": "ALLOWED",
                    "button_clicked": True,
                    "suggestion_selected": False,
                    "verified_region_and_keyword": False,
                    "outcome": "UNVERIFIED",
                    "raw_error": "github_pat_MUST_NOT_DISPLAY",
                },
            }]}
        })
        out = classify(self.folder)
        self.assertEqual(out["REGION_PICKER_OUTCOME"], "UNVERIFIED")
        self.assertEqual(out["REGION_PICKER_ROBOTS_PERMISSION"], "ALLOWED")
        self.assertEqual(out["REGION_PICKER_ATTEMPTED"], "YES")
        self.assertEqual(out["REGION_PICKER_BUTTON_CLICKED"], "YES")
        self.assertEqual(out["REGION_PICKER_OPTION_SELECTED"], "NO")
        self.assertNotIn("MUST_NOT_DISPLAY", str(out))

    def test_post_picker_url_and_button_are_categorical_only(self):
        secret = "https://example.invalid/PRIVATE_LISTING"
        self.put("v423_public_controls_results.json", {
            "evaluation": {"contexts": [{
                "context": "cheonan_a",
                "region_picker": {
                    "after_url_proof": {
                        "region": "MISSING",
                        "host": "EXPECTED",
                        "path": "EXPECTED",
                        "keyword": "OTHER",
                        "region_parameter": "MISSING",
                        "bad_raw_url": secret,
                    },
                    "selected_region_button_visible": True,
                },
            }]}
        })
        result = classify(self.folder)
        self.assertEqual(result["REGION_PICKER_FINAL_URL_REGION"], "MISSING")
        self.assertEqual(result["REGION_PICKER_FINAL_URL_KEYWORD"], "OTHER")
        self.assertEqual(result["REGION_PICKER_FINAL_URL_PATH"], "EXPECTED")
        self.assertEqual(result["REGION_PICKER_VISIBLE_REGION_BUTTON"], "YES")
        self.assertNotIn(secret, str(result))

    def test_route_region_field_missing_or_other_is_redacted(self):
        secret = "github_pat_this_value_is_private_keep_out"
        for search_state, filter_state in (
            ("MISSING", "MISSING"), ("EXPECTED", "OTHER"),
            ("OTHER", "EXPECTED"), ("MISSING", "OTHER")):
            with self.subTest(search_state=search_state,
                              filter_state=filter_state):
                self.put("v423_public_controls_results.json", {
                    "evaluation": {"contexts": [{
                        "context": "cheonan_a",
                        "capture_failure_code": "FRESH_REGION_PROOF_MISSING",
                        "fresh_region_authority_status":
                            "ROUTE_REGION_METADATA_MISSING",
                        "region_route_observation": {
                            "last_route_search_region_state": search_state,
                            "last_route_filter_region_state": filter_state,
                            "raw_search_region_id": secret,
                            "raw_filter_region_id": secret,
                            "parsed_route_models": 1,
                        },
                    }]}
                })
                output = classify(self.folder)
                self.assertEqual(output["ROUTE_SEARCH_REGION_FIELD"],
                                 search_state)
                self.assertEqual(output["ROUTE_FILTER_REGION_FIELD"],
                                 filter_state)
                self.assertEqual(
                    output["FRESH_REGION_AUTHORITY_STATUS"],
                    "ROUTE_REGION_METADATA_MISSING")
                self.assertNotIn(secret, str(output))

    def test_untrusted_region_state_is_not_echoed(self):
        secret = "github_pat_injected_as_region_status"
        self.put("v423_public_controls_results.json", {
            "evaluation": {"contexts": [{
                "context": "cheonan_a",
                "region_route_observation": {
                    "last_route_search_region_state": secret,
                    "last_route_filter_region_state": secret,
                },
                "fresh_region_authority_status": secret,
            }]}
        })
        output = classify(self.folder)
        self.assertEqual(output["ROUTE_SEARCH_REGION_FIELD"], "UNKNOWN")
        self.assertEqual(output["ROUTE_FILTER_REGION_FIELD"], "UNKNOWN")
        self.assertEqual(output["FRESH_REGION_AUTHORITY_STATUS"], "UNKNOWN")
        self.assertNotIn(secret, str(output))

    def test_region_name_and_id_agreement_export_only_bounded_values(self):
        secret = "github_pat_never_print_untrusted_region_name"
        self.put("v423_public_controls_results.json", {
            "evaluation": {"contexts": [{
                "context": "cheonan_a",
                "region_route_observation": {
                    "server_region_name_state": "EXACT",
                    "server_region_ids_agree": "YES",
                    "historical_id_drift_candidate": True,
                    "region_name_raw": secret,
                    "raw_region_ids": [secret, secret],
                },
            }]}
        })
        result = classify(self.folder)
        self.assertEqual(result["ROUTE_SERVER_REGION_NAME"], "EXACT")
        self.assertEqual(result["ROUTE_SERVER_REGION_IDS_AGREE"], "YES")
        self.assertEqual(result[
            "ROUTE_HISTORICAL_REGION_ID_DRIFT_CANDIDATE"], "YES")
        self.assertNotIn(secret, str(result))

    def test_untrusted_region_name_status_never_printed(self):
        secret = "github_pat_this_is_not_an_allowlisted_enum"
        self.put("v423_public_controls_results.json", {
            "evaluation": {"contexts": [{
                "context": "cheonan_a",
                "region_route_observation": {
                    "server_region_name_state": secret,
                    "server_region_ids_agree": secret,
                    "historical_id_drift_candidate": secret,
                },
            }]}
        })
        result = classify(self.folder)
        self.assertEqual(result["ROUTE_SERVER_REGION_NAME"], "UNKNOWN")
        self.assertEqual(result["ROUTE_SERVER_REGION_IDS_AGREE"], "UNKNOWN")
        self.assertEqual(result[
            "ROUTE_HISTORICAL_REGION_ID_DRIFT_CANDIDATE"], "UNKNOWN")
        self.assertNotIn(secret, str(result))

    def test_missing_files_are_reported_without_failure(self):
        result = classify(self.folder)
        self.assertEqual(result["PUBLIC_SUMMARY_PRESENT"], "NO")
        self.assertEqual(result["SURVEY_STATUS"], "UNAVAILABLE_OR_UNKNOWN")


if __name__ == "__main__":
    unittest.main()
