# -*- coding: utf-8 -*-
"""Offline OCI first-stage readiness, durable HMAC and signed ingestion checks."""
from __future__ import annotations

import base64
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app_v5.attestation import sign_capture, signing_public_key
from app_v5.history import HistoryStore
from daangn_secure_links_v4_34 import seal_manifest
from ops.oci import runtime

SHA = "a" * 40
URL = "https://www.daangn.com/kr/buy-sell/synthetic-oci-abcdefghijkl/"


class OciPhase1RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.state = self.base / "server-state"
        key = Ed25519PrivateKey.generate()
        self.sign_private = key.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
            serialization.NoEncryption())
        self.sign_public = signing_public_key(self.sign_private)
        self.trust_file = self.base / "trusted-signer.bin"
        self.trust_file.write_bytes(self.sign_public)
        self.patches = [
            patch("ops.oci.runtime.TRUSTED_SIGNER", self.trust_file),
            patch("ops.oci.runtime.PINNED_SIGNER_SHA256",
                  __import__("hashlib").sha256(self.sign_public).hexdigest()),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.created = runtime.initialize(self.state)

    def _signed_bundle(self, run_id: int, when: str, price: int) -> Path:
        name = f"run-{run_id}"
        stage = self.base / name
        stage.mkdir()
        item = {
            "title": "합성 HDD 4TB", "url": URL, "price_krw": price,
            "category": "디지털기기", "availability": "판매 가능 추정",
            "observation_count": 1, "full_recommendation_approved": False,
            "seller_confirmed_available": False,
            "captured_from_current_primary_h1": True
        }
        manifest = {
            "version": "4.34", "capture_scoped_only": True,
            "created_utc": when, "clickable_unique_count": 1,
            "unlinked_title_quarantine_count": 0,
            "source_run_unique_candidates": 1, "items": [item],
            "unlinked_groups": [],
            "manual_current_price_and_status_recheck_required": True,
            "full_recommendations_approved": 0
        }
        _, _, recipient = runtime._keyring(self.state)
        dt = datetime.fromisoformat(when)
        evidence = {
            "v434_private_candidate_links.encrypted.json": seal_manifest(
                manifest, recipient),
            "v434_secure_links_summary.json": {
                "version": "4.34", "status": "SEALED_PRIVATE_CANDIDATES_COMPLETE",
                "unique_candidates": 1, "linked_unique_candidates": 1,
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
                "unique_candidates": 1, "linked_unique_candidates": 1,
                "quarantined_title_groups": 0,
                "ended_utc": (dt + timedelta(minutes=5)).isoformat()
            },
            "v433_unique_candidates.json": {
                "evaluation": {"dedup_complete": True}
            },
            "v429_public_status_results.json": {
                "evaluation": {"survey_complete": True,
                  "status": "PUBLIC_STATUS_SIGNAL_SURVEY_COMPLETE_NO_DIRECT_FOR_SALE_PROOF"}
            },
            "v434_robots_decision.json": {"allowed": True}
        }
        for filename, contents in evidence.items():
            (stage / filename).write_text(
                json.dumps(contents, ensure_ascii=False), encoding="utf-8")
        attest = sign_capture(stage, self.sign_private, run_id=run_id,
                              run_attempt=1, commit_sha=SHA)
        (stage / "v434_capture_attestation.json").write_text(
            json.dumps(attest), encoding="utf-8")
        bundle = self.state / "inbox" / name
        bundle.mkdir(mode=0o700)
        for name in runtime.SIGNED_FILES.values():
            (bundle / name).write_bytes((stage / name).read_bytes())
        return bundle

    def test_state_and_public_key_stable_after_restart(self):
        self.assertTrue(self.created["history_db_present"])
        self.assertFalse(self.created["network_listener"])
        original_private = (self.state / "keys" /
                            runtime.PRIVATE_FILE).read_bytes()
        original_hmac = (self.state / "keys" /
                         runtime.HMAC_FILE).read_bytes()
        public = runtime._keyring(self.state)[2]
        self.assertEqual(len(base64.b64decode(public, validate=True)), 32)
        second = runtime.initialize(self.state)
        self.assertTrue(second["keyring_reused"])
        self.assertEqual(original_private, (self.state / "keys" /
                                            runtime.PRIVATE_FILE).read_bytes())
        self.assertEqual(original_hmac, (self.state / "keys" /
                                         runtime.HMAC_FILE).read_bytes())
        self.assertEqual(runtime._keyring(self.state)[2], public)
        self.assertEqual(runtime.status(self.state)["counts"]["listings"], 0)

    def test_signed_two_runs_price_event_idempotence_and_server_restart(self):
        first = self._signed_bundle(8101, "2026-11-10T00:00:00+00:00", 45000)
        second = self._signed_bundle(8102, "2026-11-11T00:00:00+00:00", 35000)
        check = runtime.import_capture(self.state, first,
                    expected_commit_sha=SHA, run_id=8101, dry_run=True)
        self.assertEqual(check["validated_candidates"], 1)
        self.assertEqual(runtime.status(self.state)["counts"]["listings"], 0)
        r1 = runtime.import_capture(self.state, first,
                                    expected_commit_sha=SHA, run_id=8101)
        self.assertEqual((r1["imported"], r1["events_generated"]), (1, 0))
        r2 = runtime.import_capture(self.state, second,
                                    expected_commit_sha=SHA, run_id=8102)
        self.assertEqual((r2["imported"], r2["events_generated"]), (1, 1))
        duplicate = runtime.import_capture(self.state, second,
                                    expected_commit_sha=SHA, run_id=8102)
        self.assertEqual((duplicate["imported"], duplicate["already_present"],
                          duplicate["events_generated"]), (0, 1, 0))
        counts = runtime.status(self.state)["counts"]
        self.assertEqual(counts["listings"], 1)
        self.assertEqual(counts["listing_observations"], 2)
        self.assertEqual(counts["capture_attestations"], 2)
        self.assertEqual(counts["listing_events"], 1)
        _, hmac_key, _ = runtime._keyring(self.state)
        store = HistoryStore(self.state / "db" / "history.sqlite3", hmac_key)
        events = store.get_events()
        self.assertEqual(events[0]["event_type"], "PRICE_DROPPED")
        self.assertEqual((events[0]["previous_value"], events[0]["current_value"]),
                         ("45000", "35000"))
        self.assertEqual(store.get_observations(store.stable_key(URL))[-1][
            "transaction_status"], "NOT_VERIFIED")

    def test_tamper_and_independently_expected_source_run_fail_closed(self):
        bundle = self._signed_bundle(8201, "2026-11-10T01:00:00+00:00", 43000)
        for sha, run in (("b" * 40, 8201), (SHA, 8202)):
            with self.subTest(sha=sha, run=run):
                with self.assertRaises(ValueError):
                    runtime.import_capture(self.state, bundle,
                                           expected_commit_sha=sha, run_id=run)
        self.assertEqual(runtime.status(self.state)["counts"]["listings"], 0)
        f = bundle / runtime.SIGNED_FILES["encrypted_json"]
        f.write_bytes(f.read_bytes() + b" ")
        with self.assertRaises(ValueError):
            runtime.import_capture(self.state, bundle,
                                   expected_commit_sha=SHA, run_id=8201)
        self.assertEqual(runtime.status(self.state)["counts"]["listings"], 0)

    def test_missing_file_symlink_or_wrong_inbox_rejected(self):
        bundle = self._signed_bundle(8301, "2026-11-10T01:00:00+00:00", 43000)
        outside = self.base / "outsider"
        outside.mkdir()
        with self.assertRaisesRegex(ValueError,
                                     "CAPTURE_BUNDLE_MUST_BE_ONE_DIRECT_INBOX_CHILD"):
            runtime.import_capture(self.state, outside,
                                   expected_commit_sha=SHA, run_id=8301)
        key = bundle / runtime.SIGNED_FILES["unique_json"]
        key.unlink()
        with self.assertRaisesRegex(ValueError, "CAPTURE_EVIDENCE_MISSING_OR_UNSAFE"):
            runtime.import_capture(self.state, bundle,
                                   expected_commit_sha=SHA, run_id=8301)

    def test_missing_or_changed_hmac_key_fails_without_rotation(self):
        hmac_file = self.state / "keys" / runtime.HMAC_FILE
        preserved = hmac_file.read_bytes()
        hmac_file.write_bytes(b"z" * 32)
        with self.assertRaisesRegex(ValueError, "HISTORY_DATABASE_HMAC_KEY_MISMATCH"):
            runtime.status(self.state)
        hmac_file.write_bytes(preserved)
        self.assertEqual(runtime.status(self.state)["schema_version"], 3)
        hmac_file.unlink()
        with self.assertRaisesRegex(ValueError, "PARTIAL_KEYRING"):
            runtime.initialize(self.state)

    @unittest.skipUnless(os.name == "posix", "POSIX file mode contract")
    def test_private_mode_and_private_directory_enforced(self):
        hmac_file = self.state / "keys" / runtime.HMAC_FILE
        hmac_file.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "PRIVATE_KEY_PERMISSIONS_NOT_0600"):
            runtime.status(self.state)
        hmac_file.chmod(0o600)
        self.state.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "STATE_DIR_MUST_BE_PRIVATE"):
            runtime.status(self.state)
        self.state.chmod(0o700)

    def test_cli_cannot_initialize_keys_inside_github_actions(self):
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "CI": "true"}):
            with self.assertRaises(SystemExit):
                runtime.main(["init", "--state-dir", str(self.base / "new-state")])
        self.assertFalse((self.base / "new-state").exists())

    def test_status_and_public_key_never_print_raw_secret(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = runtime.main(["status", "--state-dir", str(self.state)])
        self.assertEqual(code, 0)
        output = buffer.getvalue()
        for name in (runtime.HMAC_FILE, runtime.PRIVATE_FILE):
            self.assertNotIn(name, output)
        self.assertIn("OCI_PHASE1_HEALTHY", output)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = runtime.main(["public-key", "--state-dir", str(self.state)])
        self.assertEqual(code, 0)
        self.assertEqual(len(base64.b64decode(buffer.getvalue().strip())), 32)


if __name__ == "__main__":
    unittest.main()
