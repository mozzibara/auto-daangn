# -*- coding: utf-8 -*-
"""Offline owner-gated v4.34 encrypted collector pilot, never a live site request."""
from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch, AsyncMock

import daangn_full_route_v4_14 as full
import daangn_status_study_v4_29 as study
from scripts.run_secure_links_v434_checked import run as sealed_run

TOKEN = "I_APPROVE_V434_REGION_CLICK_NO_WAIT_V1"


class PilotApprovalTests(unittest.TestCase):
    def exercise(self, *, mode="DEFAULT", approval="", expected_called=False):
        with TemporaryDirectory() as td:
            checker_calls = []
            cmds = []
            def checker(profile):
                checker_calls.append(True)
                return {"allowed": True, "reason": "ALLOWED"}
            def runner(cmd, **kw):
                cmds.append(cmd)
                return SimpleNamespace(returncode=2)
            with patch("scripts.run_secure_links_v434_checked.validate_public_key"):
                rc = sealed_run(
                    Path(td), "SYNTHETIC_PUBLIC_KEY",
                    checker=checker, runner=runner,
                    region_click_navigation_wait=mode,
                    region_click_approval=approval,
                )
            self.assertEqual(rc, 2)
            report = json.loads(
                (Path(td)/"v434_run_status.json").read_text(encoding="utf-8"))
            self.assertFalse(report["encrypted_links_written"])
            self.assertFalse(report["raw_listing_urls_or_titles_written"])
            self.assertEqual(bool(cmds), expected_called)
            self.assertEqual(bool(checker_calls), expected_called)
            return report, cmds

    def test_default_never_adds_experimental_flags(self):
        report, cmds = self.exercise(expected_called=True)
        self.assertNotIn("--region-click-navigation-wait", cmds[0])
        self.assertNotIn("--region-click-approval", cmds[0])
        self.assertTrue(report["attempted_live"]) # Mock runner, no actual IO.

    def test_explicit_new_owner_approval_passes_only_known_literal(self):
        report, cmds = self.exercise(
            mode="NO_WAIT_AFTER", approval=TOKEN, expected_called=True)
        args = cmds[0]
        self.assertEqual(args.count("--region-click-navigation-wait"), 1)
        self.assertEqual(args[args.index("--region-click-navigation-wait")+1],
                         "NO_WAIT_AFTER")
        self.assertEqual(args[args.index("--region-click-approval")+1], TOKEN)
        self.assertEqual(report["status"], "INCONCLUSIVE_INCOMPLETE_SECURE_CAPTURE")

    def test_missing_or_wrong_additional_approval_never_checks_robots(self):
        for approval in ("", "NOT_APPROVED", "OLD_APPROVAL"):
            with self.subTest(approval=approval):
                report, cmds = self.exercise(
                    mode="NO_WAIT_AFTER", approval=approval)
                self.assertEqual(report["status"],
                                 "STOP_OWNER_REGION_CLICK_APPROVAL_REQUIRED")
                self.assertFalse(report["attempted_live"])
                self.assertFalse(cmds)

    def test_default_with_spurious_approval_and_unknown_mode_are_blocked(self):
        report, _ = self.exercise(mode="DEFAULT", approval=TOKEN)
        self.assertEqual(report["status"], "STOP_EXTRANEOUS_REGION_CLICK_APPROVAL")
        report, _ = self.exercise(mode="UNKNOWN", approval=TOKEN)
        self.assertEqual(report["status"], "STOP_UNSUPPORTED_REGION_CLICK_MODE")

    def test_production_collector_retains_original_route_ui_gate(self):
        source = inspect.getsource(full.capture)
        self.assertIn("click_navigation_wait=navigation_wait", source)
        self.assertIn("UNKNOWN_REGION_CLICK_NAVIGATION_MODE", source)
        self.assertIn("REGION_MISMATCH", source)
        self.assertIn("fresh_region_authority_status", source)
        self.assertIn("FRESH_REGION_PROOF_MISSING", source)

    def test_github_workflow_second_approval_required_for_pilot(self):
        path = Path(__file__).resolve().parents[1] / ".github/workflows/secure-links-v434.yml"
        data = path.read_text(encoding="utf-8")
        self.assertIn("region_click_navigation_wait:", data)
        self.assertIn("region_click_approval:", data)
        self.assertIn("inputs.region_click_navigation_wait != 'NO_WAIT_AFTER'", data)
        self.assertIn("inputs.region_click_approval == '"+TOKEN+"'", data)
        self.assertIn("--region-click-navigation-wait NO_WAIT_AFTER", data)
        self.assertIn("ref: main", data)
        self.assertIn("environment: daangn-producer", data)


class DownstreamApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_indirect_worker_rejects_missing_approval_before_previous_run(self):
        options = SimpleNamespace(
            region_click_navigation_wait="NO_WAIT_AFTER",
            region_click_approval="OLD_APPROVAL"
        )
        with patch.object(study.previous, "run", new_callable=AsyncMock) as run:
            with self.assertRaisesRegex(ValueError,
                                        "EXACT_OWNER_REGION_CLICK_APPROVAL_REQUIRED"):
                await study.run(options)
            run.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
