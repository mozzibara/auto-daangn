# -*- coding: utf-8 -*-
"""Public-source architecture invariants: offline security guardrails.

These checks do not contact GitHub, Daangn, OCI, or Telegram and do not
require secrets. They catch accidental regressions in the public repo's
producer trust boundary and approval-only live capture workflow.
"""
from __future__ import annotations

from pathlib import Path
import unittest

from app_v5.attestation import REPOSITORY
from ops.oci.actions_intake import OWNER, REPO, WORKFLOW
from scripts.pre_oci_v434_ephemeral import REPO as APPROVED_REPO

ROOT = Path(__file__).resolve().parents[1]


class PublicArchitectureContractTests(unittest.TestCase):
    def test_only_public_producer_is_trusted(self):
        self.assertEqual(REPOSITORY, "mozzibara/auto-daangn")
        self.assertEqual(REPO, REPOSITORY)
        self.assertEqual(APPROVED_REPO, REPOSITORY)
        self.assertEqual(OWNER, "mozzibara")
        self.assertEqual(WORKFLOW, ".github/workflows/secure-links-v434.yml")

    def test_owner_approval_stays_manual(self):
        text = (ROOT / WORKFLOW).read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("issue_comment:", text)
        self.assertIn("github.actor == github.repository_owner", text)
        self.assertIn("github.event.issue.number == 1", text)
        self.assertIn("github.event.issue.pull_request == null", text)
        self.assertIn("ref: main", text)
        self.assertNotIn("pull_request_target:", text)
        self.assertNotIn("schedule:", text)

    def test_workflows_have_minimum_default_permissions(self):
        files = sorted((ROOT / ".github/workflows").glob("*.yml"))
        self.assertTrue(files)
        for file in files:
            with self.subTest(workflow=file.name):
                body = file.read_text(encoding="utf-8")
                self.assertIn("permissions:\n  contents: read", body)
                self.assertNotIn("pull_request_target:", body)
                self.assertNotIn("permissions: write-all", body)

    def test_signing_secret_only_referenced_in_owner_controlled_workflows(self):
        files = sorted((ROOT / ".github/workflows").glob("*.yml"))
        permit = {"secure-links-v434.yml", "verify-v434-signer.yml"}
        for file in files:
            if "secrets.V434_ATTEST_ED25519_KEY_B64" in file.read_text(
                    encoding="utf-8"):
                self.assertIn(file.name, permit)

    def test_signer_only_accessible_in_main_only_environment(self):
        for workflow in ("secure-links-v434.yml",
                         "verify-v434-signer.yml"):
            text = (ROOT / ".github/workflows" / workflow).read_text(
                encoding="utf-8")
            with self.subTest(workflow=workflow):
                self.assertIn("environment: daangn-producer", text)
                self.assertIn("secrets.V434_ATTEST_ED25519_KEY_B64", text)
                self.assertIn("contents: read", text)
                self.assertNotIn("pull_request_target:", text)
                self.assertNotIn("schedule:", text)

    def test_missing_or_invalid_signer_fails_before_browser_capture(self):
        text = (ROOT / WORKFLOW).read_text(encoding="utf-8")
        self.assertIn("PRODUCER_SIGNER_ENVIRONMENT_SECRET_NOT_CONFIGURED",
                      text)
        self.assertIn("python -m scripts.verify_github_signer", text)
        self.assertLess(text.index("python -m scripts.verify_github_signer"),
                        text.index("python -m playwright install --with-deps chromium"))
        self.assertLess(text.index("python -m playwright install --with-deps chromium"),
                        text.index("python scripts/run_secure_links_v434_checked.py"))
        self.assertIn(
            "if: success() && env.CAPTURE_TEST_MODE != "
            "'EPHEMERAL_REVIEWABLE_TEST' && "
            "steps.secure.outputs.exit_code == '0'", text)
        self.assertNotIn("capture remains ADVISORY", text)

    def test_public_source_does_not_automatically_launch_browser(self):
        body = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertNotIn("python -m playwright install", body)
        # Actual browser installation belongs solely to the manual live job.
        capture = (ROOT / WORKFLOW).read_text(encoding="utf-8")
        self.assertIn("python -m playwright install --with-deps chromium", capture)

    def test_oci_timers_share_bounded_host_lock(self):
        services = (
            "daangn-actions-intake.service",
            "daangn-object-storage-backup.service",
            "daangn-status.service",
        )
        lock = ("ExecStart=/usr/bin/flock -w 20 "
                "/var/lib/auto-daangn/db/oci-ops.lock ")
        for name in services:
            with self.subTest(service=name):
                text = (ROOT / "ops/oci/systemd" / name).read_text(
                    encoding="utf-8")
                self.assertIn(lock, text)
                self.assertIn("ReadWritePaths=/var/lib/auto-daangn", text)

    def test_public_repo_has_no_private_runtime_artifacts(self):
        forbidden = (
            ROOT / ".env",
            ROOT / "local_private",
            ROOT / "keys/v434/ed25519_signer_secret_b64.txt",
            ROOT / "db/history.sqlite3",
            ROOT / "v434_live_output",
        )
        for path in forbidden:
            self.assertFalse(path.exists(), str(path))


if __name__ == "__main__":
    unittest.main()
