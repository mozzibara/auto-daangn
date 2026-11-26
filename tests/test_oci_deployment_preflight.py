# -*- coding: utf-8 -*-
"""Synthetic tests for the administrator's non-mutating deployment preflight."""
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ops.oci import deployment_preflight as preflight


class DeploymentPreflightTests(unittest.TestCase):
    def good(self):
        return {key: True for key in preflight.REQUIRED_CHECKS}

    def test_good_evidence_is_not_activation_authority(self):
        report = preflight.evaluate(self.good(), intake="NOT_INSTALLED")
        self.assertEqual(report["status"], "READY_FOR_REVIEW")
        self.assertEqual(report["blockers"], [])
        self.assertFalse(report["installation_authorized"])
        self.assertFalse(report["collection_authorized"])
        self.assertFalse(report["database_written"])
        self.assertEqual(report["intake"], "NOT_INSTALLED")

    def test_missing_false_or_non_boolean_required_checks_fail_closed(self):
        for key in preflight.REQUIRED_CHECKS:
            for value in (None, False, "true", 1):
                evidence = self.good()
                evidence[key] = value
                with self.subTest(key=key, value=value):
                    report = preflight.evaluate(evidence, intake="DISABLED")
                    self.assertEqual(report["status"], "BLOCKED")
                    self.assertIn(key, report["blockers"])
                    self.assertFalse(report["installation_authorized"])
            evidence = self.good()
            del evidence[key]
            self.assertIn(key, preflight.evaluate(evidence)["blockers"])

    def test_unknown_intake_and_active_intake_hold(self):
        for value in ("ACTIVE", "UNKNOWN", "arbitrary raw data"):
            report = preflight.evaluate(self.good(), intake=value)
            self.assertEqual(report["status"], "BLOCKED")
            self.assertIn("intake_inactive", report["blockers"])

    def test_only_allowlisted_fields_are_exported(self):
        evidence = self.good()
        evidence["secret"] = "raw-test-secret"
        evidence["state_private"] = "raw-test-secret"
        report = preflight.evaluate(evidence, intake="raw-test-secret")
        self.assertNotIn("raw-test-secret", json.dumps(report))
        self.assertEqual(set(report["checks"]), set(preflight.REQUIRED_CHECKS))

    def test_unit_state_requires_both_components_and_explicit_state(self):
        absent = {"LoadState": "not-found", "ActiveState": "inactive", "UnitFileState": ""}
        disabled = {"LoadState": "loaded", "ActiveState": "inactive", "UnitFileState": "disabled"}
        active = dict(disabled, ActiveState="active")
        self.assertEqual(preflight._intake_state(absent, absent), "NOT_INSTALLED")
        self.assertEqual(preflight._intake_state(disabled, disabled), "DISABLED")
        self.assertEqual(preflight._intake_state(disabled, active), "ACTIVE")
        self.assertEqual(preflight._intake_state(absent, disabled), "UNKNOWN")
        self.assertEqual(preflight._intake_state({}, {}), "UNKNOWN")

    def test_runner_positive_control_is_required(self):
        fake_pwd = SimpleNamespace(getpwnam=lambda name: SimpleNamespace(
            pw_uid=1001 if name == "daangn" else 1002, pw_gid=1001))
        with patch.dict("sys.modules", {"pwd": fake_pwd}), \
                patch.object(preflight, "_runner_access", return_value=False), \
                patch.object(preflight, "_meta", return_value=True), \
                patch.object(preflight, "_trusted_ancestors", return_value=True), \
                patch.object(preflight, "_unit", return_value={}):
            report = preflight.collect()
        self.assertIn("runner_identity_probe", report["blockers"])
        self.assertEqual(report["status"], "BLOCKED")

    def test_invalid_command_tokens_do_not_execute_subprocess(self):
        with patch.object(preflight.subprocess, "run",
                          side_effect=AssertionError("must not execute")):
            self.assertEqual(preflight._unit("unknown.service"), {})
            self.assertIsNone(preflight._runner_access(Path("/"), "-c"))

    def test_non_root_cli_does_not_collect(self):
        with patch.object(preflight.os, "geteuid", return_value=1000, create=True), \
                patch.object(preflight, "collect", side_effect=AssertionError("must not collect")):
            self.assertEqual(preflight.main([]), 2)

    def test_cli_rejects_arbitrary_parameters(self):
        with self.assertRaises(SystemExit):
            preflight.main(["--state-dir", "/somewhere"])


if __name__ == "__main__":
    unittest.main()
