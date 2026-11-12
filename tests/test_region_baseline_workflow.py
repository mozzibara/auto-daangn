# -*- coding: utf-8 -*-
"""Owner-only one-shot region/egress workflow security regression."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
WORKFLOW=ROOT/".github/workflows/region-baseline-egress-contrast.yml"
SOURCE=ROOT/"scripts/region_baseline_contrast.py"
EVIDENCE=ROOT/"app_v5/region_baseline_contrast.py"


class WorkflowSecurity(unittest.TestCase):
    def test_user_approval_bound_to_owner_and_exact_issue(self):
        doc=WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:",doc)
        self.assertIn("issue_comment:",doc)
        self.assertIn("github.event.issue.number == 11",doc)
        self.assertIn("github.event.comment.user.login == github.repository_owner",doc)
        self.assertIn("github.actor == github.repository_owner",doc)
        self.assertIn("inputs.approval == 'I_APPROVE_REGION_BASELINE_V1'",doc)
        self.assertIn("'/run-daangn-region-baseline-v1'",doc)
        for disallowed in ("push:","pull_request:","schedule:","repository_dispatch:",
                           "workflow_run:","upload-artifact","secrets.",
                           "persist-credentials: true"):
            self.assertNotIn(disallowed,doc)
        self.assertIn("ref: main",doc)
        self.assertIn("persist-credentials: false",doc)
        self.assertIn("permissions:\n  contents: read",doc)

    def test_offline_fixture_first_and_bounded_os_matrix(self):
        doc=WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("os: [ubuntu-24.04, windows-2025]",doc)
        for os in ("Linux","Windows"):
            section=doc.split(f"({os})",1)[-1]
            self.assertLess(section.index("python -m scripts.region_baseline_contrast"),
                section.index("--live --headed --egress-context"))
        for disallowed in ("--proxy-server","--no-sandbox",
                           "--disable-blink-features","--ignore-certificate-errors",
                           "storage-state","--force-login"):
            self.assertNotIn(disallowed,doc)
        self.assertIn("timeout-minutes: 14",doc)

    def test_one_site_navigation_no_region_selection_in_own_script(self):
        text=SOURCE.read_text(encoding="utf-8")
        self.assertIn("check_public_robots()",text)
        self.assertIn("SEARCH_URL",text)
        self.assertIn("wait_until=\"domcontentloaded\"",text)
        self.assertNotIn("ui_select_region",text)
        self.assertNotIn("page.click",text)
        self.assertNotIn("route.fulfill",text)
        self.assertNotIn("storage_state",text)
        self.assertNotIn("goto(sample",text)
        self.assertIn("authorizes_listings",text)

    def test_no_raw_ip_or_cookie_in_export(self):
        doc=EVIDENCE.read_text(encoding="utf-8")
        self.assertIn("https://ipapi.co/json/",doc)
        self.assertIn("raw_ip_exported",doc)
        self.assertIn("third_party_ip_geolocation_not_authoritative",doc)
        self.assertNotIn("proxy-server",doc)


if __name__=="__main__":
    unittest.main()
