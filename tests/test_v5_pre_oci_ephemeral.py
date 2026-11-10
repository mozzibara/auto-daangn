# -*- coding: utf-8 -*-
"""Synthetic, offline pre-OCI ephemeral X25519 -> signature -> SQLite tests."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from app_v5.attestation import sign_capture, signing_public_key
from daangn_secure_links_v4_34 import seal_manifest
from app_v5.sealed_import import read_encrypted
from scripts.pre_oci_v434_ephemeral import (
    PINNED_FINGERPRINT, REPO, WORKFLOW_REF,
    require_owner_approved_actions, generate_ephemeral_recipient,
    audit_ephemeral_capture,
)

SHA = "a" * 40


def synthetic_manifest():
    return {
        "version": "4.34", "capture_scoped_only": True,
        "created_utc": "2026-11-10T01:23:45+00:00",
        "clickable_unique_count": 1, "unlinked_title_quarantine_count": 0,
        "source_run_unique_candidates": 1,
        "items": [{
            "title": "synthetic HDD 4TB",
            "url": "https://www.daangn.com/kr/buy-sell/synthetic-abcdefghijkl/",
            "price_krw": 40000, "category": "디지털기기",
            "availability": "판매 가능 추정",
            "observation_count": 1,
            "full_recommendation_approved": False,
            "seller_confirmed_available": False,
            "captured_from_current_primary_h1": True
        }],
        "unlinked_groups": [],
        "manual_current_price_and_status_recheck_required": True,
        "full_recommendations_approved": 0
    }


def env():
    return {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_REPOSITORY_OWNER": "mozzibara",
        "GITHUB_ACTOR": "mozzibara",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_WORKFLOW_REF": WORKFLOW_REF,
        "GITHUB_SHA": SHA,
        "GITHUB_RUN_ID": "501",
        "GITHUB_RUN_ATTEMPT": "1",
        "CAPTURE_APPROVAL": "I_APPROVE_V434_ENCRYPTED_PUBLIC_LINKS",
        "CAPTURE_TEST_MODE": "EPHEMERAL_REVIEWABLE_TEST"
    }


class PreOciEphemeralTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.temp_dir = self.root / "temporary"
        self.out = self.root / "capture"
        self.out.mkdir()

    def test_only_exact_owner_main_workflow_and_approval_can_execute(self):
        self.assertEqual(require_owner_approved_actions(env(), commit_sha=SHA),
                         (501, 1))
        for field, value in (
            ("GITHUB_ACTIONS", "false"),
            ("GITHUB_REPOSITORY", "outsider/fork"),
            ("GITHUB_ACTOR", "someone_else"),
            ("GITHUB_EVENT_NAME", "pull_request"),
            ("GITHUB_EVENT_NAME", "issue_comment"),
            ("GITHUB_REF", "refs/heads/feature"),
            ("GITHUB_WORKFLOW_REF", "other-workflow"),
            ("CAPTURE_APPROVAL", "NOT_APPROVED"),
            ("CAPTURE_TEST_MODE", "CAPTURE_ENCRYPTED_ONLY"),
            ("GITHUB_SHA", "b" * 40)
        ):
            with self.subTest(field=field, value=value):
                bad = env()
                bad[field] = value
                with self.assertRaisesRegex(ValueError, "OWNER_APPROVED_MAIN"):
                    require_owner_approved_actions(bad, commit_sha=SHA)

    def test_exact_owner_issue_comment_approval_only(self):
        event = {
            "action": "created",
            "issue": {"number": 1},
            "comment": {
                "body": "/run-daangn-pre-oci-e2e-v434",
                "user": {"login": "mozzibara"}
            },
            "sender": {"login": "mozzibara"}
        }
        path = self.root / "issue-event.json"
        def run_with_event(payload):
            path.write_text(json.dumps(payload), encoding="utf-8")
            approved = env()
            approved["GITHUB_EVENT_NAME"] = "issue_comment"
            approved["GITHUB_EVENT_PATH"] = str(path)
            return require_owner_approved_actions(approved, commit_sha=SHA)
        self.assertEqual(run_with_event(event), (501, 1))
        for field, value in (
            ("action", "edited"),
            ("issue", {"number": 4}),
            ("issue", {"number": 1, "pull_request": {"url": "pr"}}),
            ("comment", {"body": "/run-daangn-pre-oci-e2e-v434 extra",
                         "user": {"login": "mozzibara"}}),
            ("comment", {"body": "/run-daangn-pre-oci-e2e-v434",
                         "user": {"login": "other"}}),
            ("sender", {"login": "other"})
        ):
            with self.subTest(field=field, value=value):
                bad = dict(event)
                bad[field] = value
                with self.assertRaisesRegex(ValueError, "OWNER_APPROVED_MAIN"):
                    run_with_event(bad)

    def test_prepare_generates_private_files_exclusively_and_public_only_env(self):
        github_env = self.root / "github-env"
        github_env.write_text("", encoding="utf-8")
        generate_ephemeral_recipient(self.temp_dir, github_env)
        recipient = self.temp_dir / "recipient-private.bin"
        hmac_key = self.temp_dir / "history-hmac.bin"
        self.assertEqual(recipient.stat().st_size, 32)
        self.assertEqual(hmac_key.stat().st_size, 32)
        self.assertNotEqual(recipient.read_bytes(), hmac_key.read_bytes())
        public_value = github_env.read_text(encoding="utf-8").split("=", 1)[1].strip()
        self.assertEqual(len(base64.b64decode(public_value)), 32)
        self.assertNotIn(base64.b64encode(recipient.read_bytes()).decode(),
                         github_env.read_text(encoding="utf-8"))
        envelope = seal_manifest(synthetic_manifest(), public_value)
        p = self.out / "encrypted.json"
        p.write_text(json.dumps(envelope), encoding="utf-8")
        self.assertEqual(read_encrypted(p, recipient.read_bytes())["clickable_unique_count"], 1)
        with self.assertRaises(FileExistsError):
            generate_ephemeral_recipient(self.temp_dir, github_env)

    def _signed_files(self):
        (self.root / "github-env").write_text("", encoding="utf-8")
        generate_ephemeral_recipient(self.temp_dir, self.root / "github-env")
        public_value = (self.root / "github-env").read_text(
            encoding="utf-8").split("=", 1)[1].strip()
        files = {
            "v434_private_candidate_links.encrypted.json":
                seal_manifest(synthetic_manifest(), public_value),
            "v434_secure_links_summary.json": {
                "version": "4.34",
                "status": "SEALED_PRIVATE_CANDIDATES_COMPLETE",
                "unique_candidates": 1,
                "linked_unique_candidates": 1,
                "quarantined_title_groups": 0,
                "full_recommendations_approved": 0,
                "key_material_on_github": False,
                "plaintext_urls_or_titles_in_artifacts": False
            },
            "v434_run_status.json": {
                "version": "4.34", "status": "SEALED_CAPTURE_COMPLETE",
                "attempted_live": True, "encrypted_links_written": True,
                "approval_required": True, "strict_listing_approved_count": 0,
                "max_source_visits": 9, "max_control_visits": 6,
                "unique_candidates": 1,
                "linked_unique_candidates": 1,
                "quarantined_title_groups": 0,
                "ended_utc": "2026-11-11T02:00:00+00:00"
            },
            "v433_unique_candidates.json": {
                "evaluation": {"dedup_complete": True}
            },
            "v429_public_status_results.json": {
                "evaluation": {
                    "survey_complete": True,
                    "status": "PUBLIC_STATUS_SIGNAL_SURVEY_COMPLETE_NO_DIRECT_FOR_SALE_PROOF"
                }
            },
            "v434_robots_decision.json": {"allowed": True}
        }
        for filename, data in files.items():
            (self.out / filename).write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
        seed = Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption()
        )
        public = signing_public_key(seed)
        pinned = self.root / "test-trusted-public.bin"
        pinned.write_bytes(public)
        signed = sign_capture(
            self.out, seed, run_id=501, run_attempt=1, commit_sha=SHA
        )
        (self.out / "v434_capture_attestation.json").write_text(
            json.dumps(signed, ensure_ascii=False), encoding="utf-8"
        )
        return pinned, hashlib.sha256(public).hexdigest()

    def test_authenticated_ephemeral_import_and_idempotent_replay(self):
        pinned, fingerprint = self._signed_files()
        with patch("scripts.pre_oci_v434_ephemeral.PUBLIC_FILE", pinned), patch(
                "scripts.pre_oci_v434_ephemeral.PINNED_FINGERPRINT", fingerprint):
            result = audit_ephemeral_capture(self.out, self.temp_dir,
                                             commit_sha=SHA, run_id=501, attempt=1)
        self.assertEqual(result["result"], "PASS_EPHEMERAL_REVIEWABLE")
        self.assertEqual(result["reviewable_rows"], 1)
        self.assertTrue(result["idempotent_replay"])
        self.assertTrue(result["transaction_status_remains_unverified"])
        self.assertTrue(result["stock_remains_unobserved"])
        self.assertTrue((self.temp_dir / "test-only.sqlite3").is_file())

    def test_tamper_rejected_before_sqlite_creation(self):
        pinned, fingerprint = self._signed_files()
        target = self.out / "v434_private_candidate_links.encrypted.json"
        target.write_bytes(target.read_bytes() + b" ")
        with patch("scripts.pre_oci_v434_ephemeral.PUBLIC_FILE", pinned), patch(
                "scripts.pre_oci_v434_ephemeral.PINNED_FINGERPRINT", fingerprint):
            with self.assertRaisesRegex(ValueError, "ATTESTED_FILE_HASH_MISMATCH"):
                audit_ephemeral_capture(self.out, self.temp_dir,
                                        commit_sha=SHA, run_id=501, attempt=1)
        self.assertFalse((self.temp_dir / "test-only.sqlite3").exists())

    def test_wrong_run_id_rejected(self):
        pinned, fingerprint = self._signed_files()
        with patch("scripts.pre_oci_v434_ephemeral.PUBLIC_FILE", pinned), patch(
                "scripts.pre_oci_v434_ephemeral.PINNED_FINGERPRINT", fingerprint):
            with self.assertRaisesRegex(ValueError, "SIGNED_JOB_ID_MUST_MATCH_GITHUB_RUN"):
                audit_ephemeral_capture(self.out, self.temp_dir,
                                        commit_sha=SHA, run_id=502, attempt=1)


if __name__ == "__main__":
    unittest.main()
