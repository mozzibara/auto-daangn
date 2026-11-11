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

    def test_missing_files_are_reported_without_failure(self):
        result = classify(self.folder)
        self.assertEqual(result["PUBLIC_SUMMARY_PRESENT"], "NO")
        self.assertEqual(result["SURVEY_STATUS"], "UNAVAILABLE_OR_UNKNOWN")


if __name__ == "__main__":
    unittest.main()
