# -*- coding: utf-8 -*-
"""Offline guardrail checks for the owner-only Windows-hosted comparison."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / ".github/workflows/chrome-stable-windows-hosted-compare.yml"
OFFLINE = ROOT / ".github/workflows/ci.yml"


class WindowsHostedWorkflowGuards(unittest.TestCase):
    def test_owner_approval_and_only_manual_dispatch(self):
        text = LIVE.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("github.actor == github.repository_owner", text)
        self.assertIn("inputs.approval == 'I_APPROVE_WINDOWS_HOSTED_REGION_COMPARE_V1'", text)
        for forbidden in ("issue_comment:", "schedule:", "push:", "pull_request:",
                          "repository_dispatch:", "workflow_run:", "upload-artifact"):
            self.assertNotIn(forbidden, text)
        self.assertIn("ref: main", text)
        self.assertIn("persist-credentials: false", text)
        self.assertIn("contents: read", text)
        self.assertNotIn("secrets.", text)

    def test_offline_fixture_runs_before_live_and_no_unsafe_flags(self):
        text = LIVE.read_text(encoding="utf-8")
        fixture = "python -m scripts.chrome_stable_input_compare --headed"
        live = "python -m scripts.chrome_stable_input_compare --live --headed"
        self.assertLess(text.index(fixture), text.index(live))
        self.assertIn("--owner-approval I_APPROVE_CHROME_INPUT_COMPARISON_V1", text)
        self.assertIn("runs-on: windows-2025", text)
        for forbidden in ("--no-sandbox", "--disable-blink-features",
                          "--ignore-certificate-errors", "--proxy-server",
                          "--disable-web-security", "storage-state"):
            self.assertNotIn(forbidden, text)

    def test_regular_ci_is_offline_only(self):
        text = OFFLINE.read_text(encoding="utf-8")
        self.assertIn("windows-chrome-input-fixture:", text)
        self.assertIn("runs-on: windows-2025", text)
        self.assertIn("python -m scripts.chrome_stable_input_compare --headed", text)
        self.assertNotIn("chrome_stable_input_compare --live", text)


if __name__ == "__main__":
    unittest.main()
