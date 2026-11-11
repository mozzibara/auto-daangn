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

    def test_missing_files_are_reported_without_failure(self):
        result = classify(self.folder)
        self.assertEqual(result["PUBLIC_SUMMARY_PRESENT"], "NO")
        self.assertEqual(result["SURVEY_STATUS"], "UNAVAILABLE_OR_UNKNOWN")


if __name__ == "__main__":
    unittest.main()
