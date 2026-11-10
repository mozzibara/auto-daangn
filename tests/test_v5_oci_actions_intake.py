# -*- coding: utf-8 -*-
"""OCI stage 2: real cryptography, real SQLite, FAKE GitHub API + ZIP streams."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from app_v5.attestation import sign_capture, signing_public_key
from daangn_secure_links_v4_34 import seal_manifest
from ops.oci import runtime, backup, actions_intake as intake

SHA = "a" * 40
URL = "https://www.daangn.com/kr/buy-sell/synthetic-intake-abcdefghijkl/"
CLOCK = datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc)


def synthetic_recovery_keypair(folder: Path) -> None:
    """CI fixtures create ephemeral keys directly; server keygen CLI stays blocked."""
    k = X25519PrivateKey.generate()
    runtime._new_file(folder / "recovery-private.bin",
                      k.private_bytes(serialization.Encoding.Raw,
                                      serialization.PrivateFormat.Raw,
                                      serialization.NoEncryption()))
    runtime._new_file(folder / "recovery-public.b64",
                      base64.b64encode(k.public_key().public_bytes(
                          serialization.Encoding.Raw,
                          serialization.PublicFormat.Raw)) + b"\n")


def signed_files(root: Path, recipient_public: str, signer_raw: bytes,
                 run_id: int, amount: int, when: str) -> dict[str, bytes]:
    root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": "4.34", "capture_scoped_only": True,
        "created_utc": when, "clickable_unique_count": 1,
        "unlinked_title_quarantine_count": 0,
        "source_run_unique_candidates": 1, "items": [{
            "title": "합성 HDD NAS 4TB", "url": URL,
            "price_krw": amount, "category": "디지털기기",
            "availability": "판매 가능 추정", "observation_count": 1,
            "full_recommendation_approved": False,
            "seller_confirmed_available": False,
            "captured_from_current_primary_h1": True
        }],
        "unlinked_groups": [],
        "manual_current_price_and_status_recheck_required": True,
        "full_recommendations_approved": 0
    }
    reports = {
        "v434_private_candidate_links.encrypted.json":
            seal_manifest(manifest, recipient_public),
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
            "ended_utc": (datetime.fromisoformat(when) +
                          timedelta(minutes=5)).isoformat()
        },
        "v433_unique_candidates.json": {"evaluation": {"dedup_complete": True}},
        "v429_public_status_results.json": {"evaluation": {
            "survey_complete": True,
            "status": "PUBLIC_STATUS_SIGNAL_SURVEY_COMPLETE_NO_DIRECT_FOR_SALE_PROOF"
        }},
        "v434_robots_decision.json": {"allowed": True}
    }
    for filename, value in reports.items():
        (root / filename).write_text(json.dumps(value, ensure_ascii=False),
                                     encoding="utf-8")
    signature = sign_capture(root, signer_raw, run_id=run_id,
                             run_attempt=1, commit_sha=SHA)
    reports["v434_capture_attestation.json"] = signature
    (root / "v434_capture_attestation.json").write_text(
        json.dumps(signature), encoding="utf-8")
    return {name: (root / name).read_bytes() for name in
            intake.EXPECTED}


def zip_members(files: dict[str, bytes],
                *, prefix: str = "", extra: dict[str, bytes] | None = None) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for name, data in {**files, **(extra or {})}.items():
            archive.writestr(prefix + name, data)
    return buffer.getvalue()


def run_doc(run_id: int, *, attempt: int = 1, actor: str = "mozzibara",
            event: str = "workflow_dispatch", sha: str = SHA, **overrides) -> dict:
    row = {
        "id": run_id, "run_attempt": attempt, "head_sha": sha,
        "status": "completed", "conclusion": "success", "event": event,
        "path": ".github/workflows/secure-links-v434.yml@main",
        "head_branch": "main",
        "repository": {"full_name": "mozzibara/auto-daangn"},
        "head_repository": {"full_name": "mozzibara/auto-daangn"},
        "actor": {"login": actor},
        "triggering_actor": {"login": actor},
    }
    row.update(overrides)
    return row


class FakeGitHub:
    def __init__(self, zip_files: dict[int, bytes], runs: list[dict]):
        self.archives = zip_files
        self.runs = runs
        self.artifact_checks = []
        self.downloads = []

    def list_runs(self):
        return {"total_count": len(self.runs), "workflow_runs": self.runs}

    def list_artifacts(self, run_id: int, name: str):
        self.artifact_checks.append(run_id)
        archive = self.archives.get(run_id)
        if archive is None:
            return {"total_count": 0, "artifacts": []}
        return {"total_count": 1, "artifacts": [{
            "id": run_id + 5000, "name": name,
            "expired": False, "size_in_bytes": len(archive),
            "workflow_run": {"id": run_id},
        }]}

    def download_zip(self, artifact_id: int):
        run_id = artifact_id - 5000
        self.downloads.append(run_id)
        return self.archives[run_id]


class OciActionsIntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.state = self.work / "oci"
        signer = Ed25519PrivateKey.generate()
        self.signer_raw = signer.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
            serialization.NoEncryption())
        pub = signing_public_key(self.signer_raw)
        signer_file = self.work / "signer-public.bin"
        signer_file.write_bytes(pub)
        patch1 = patch("ops.oci.runtime.TRUSTED_SIGNER", signer_file)
        patch2 = patch("ops.oci.runtime.PINNED_SIGNER_SHA256",
                       hashlib.sha256(pub).hexdigest())
        for p in (patch1, patch2):
            p.start()
            self.addCleanup(p.stop)
        runtime.initialize(self.state)
        self.recovery = self.work / "offline"  # stand-in for a different machine
        self.recovery.mkdir()
        synthetic_recovery_keypair(self.recovery)
        self.pub = self.recovery / "recovery-public.b64"
        self.private = self.recovery / "recovery-private.bin"
        self.recipient = runtime._keyring(self.state)[2]

    def confirm(self, *, now=CLOCK):
        sealed = backup.create_backup(self.state, self.pub, now=now)
        # Round-trip through a separately staged fake offsite download.
        downloaded = self.work / "downloaded-from-cloud.sealed.json"
        downloaded.write_bytes(sealed.read_bytes())
        restored = backup.inspect_backup(downloaded, self.private,
                                         scratch=self.work)
        self.assertEqual(restored["state"], "OFFLINE_RESTORE_VERIFIED")
        verified = backup.register_offsite_confirmation(
            self.state, sealed, downloaded,
            operator_verified_offline_restore=True, now=now)
        self.assertEqual(verified["state"], "OFFSITE_BACKUP_CONFIRMED")
        return sealed, downloaded

    def api(self, *entries):
        archives = {}
        runs = []
        for run_id, price, time in entries:
            files = signed_files(self.work / f"producer-{run_id}",
                                 self.recipient, self.signer_raw,
                                 run_id, price, time)
            archives[run_id] = zip_members(files)
            runs.append(run_doc(run_id))
        return FakeGitHub(archives, runs)

    def test_backup_restore_and_immutable_live_server(self):
        before = runtime.status(self.state)
        sealed, downloaded = self.confirm()
        self.assertNotIn(b"history-hmac-private.bin", sealed.read_bytes())
        self.assertNotIn(self.recipient.encode(), sealed.read_bytes())
        self.assertEqual(backup.require_recent_offsite_backup(
            self.state, now=CLOCK)["state"], "OFFSITE_BACKUP_GATE_PASS")
        self.assertEqual(runtime.status(self.state), before)
        self.assertEqual(backup.inspect_backup(downloaded, self.private)[
            "state"], "OFFLINE_RESTORE_VERIFIED")

    def test_backup_missing_or_unverified_prevents_any_api_call(self):
        fake = self.api((9201, 42000, "2026-11-10T01:00:00+00:00"))
        with self.assertRaisesRegex(ValueError, "OFFSITE_VERIFIED_BACKUP_REQUIRED"):
            intake.poll_once(self.state, fake, now=CLOCK)
        self.assertEqual(fake.artifact_checks, [])
        self.confirm(now=CLOCK)
        with self.assertRaisesRegex(ValueError, "OFFSITE_BACKUP_CONFIRMATION_EXPIRED"):
            intake.poll_once(self.state, fake, now=CLOCK+timedelta(days=8))
        self.assertEqual(fake.artifact_checks, [])

    def test_signed_import_drop_replay_and_backup_refresh_gate(self):
        self.confirm(now=CLOCK)
        fake = self.api(
            (9201, 45000, "2026-11-10T01:00:00+00:00"),
            (9202, 35000, "2026-11-11T01:00:00+00:00")
        )
        preview = intake.poll_once(self.state, fake, dry_run=True, now=CLOCK)
        self.assertEqual(preview["state"], "APPROVED_ARTIFACT_AVAILABLE")
        self.assertEqual(fake.downloads, [])
        first = intake.poll_once(self.state, fake, now=CLOCK)
        self.assertEqual(first["imported"], 1)
        self.assertEqual(first["events_generated"], 0)
        self.assertEqual(fake.downloads, [9201])
        self.assertFalse(list((self.state / "inbox").iterdir()))
        # The 9201 change is not yet included in an offsite-verified backup.
        with self.assertRaisesRegex(ValueError, "DATABASE_HAS_UNBACKED_SIGNED_CAPTURES"):
            intake.poll_once(self.state, fake, now=CLOCK)
        self.confirm(now=CLOCK + timedelta(hours=1))
        second = intake.poll_once(self.state, fake, now=CLOCK+timedelta(hours=1))
        self.assertEqual(second["run_id"], 9202)
        self.assertEqual(second["events_generated"], 1)
        self.assertEqual(runtime.status(self.state)["counts"]["listing_events"], 1)
        self.confirm(now=CLOCK + timedelta(hours=2))
        repeated = intake.poll_once(self.state, fake, now=CLOCK+timedelta(hours=2))
        self.assertEqual(repeated["state"], "NO_ELIGIBLE_NEW_SIGNED_ARTIFACT")
        self.assertEqual(fake.downloads, [9201, 9202])

    def test_wrong_actor_event_workflow_branch_source_or_triggering_actor(self):
        good = run_doc(9301)
        invalid = [
            run_doc(9301, actor="stranger"),
            run_doc(9301, event="pull_request"),
            run_doc(9301, path=".github/workflows/other.yml@main"),
            run_doc(9301, head_branch="different"),
            run_doc(9301, head_repository={"full_name": "attacker/fork"}),
            run_doc(9301, triggering_actor={"login": "not-owner"}),
            run_doc(9301, status="in_progress"),
            run_doc(9301, conclusion="failure"),
            run_doc(9301, head_sha="not-commit"),
        ]
        self.assertIsNotNone(intake._valid_run(good))
        for row in invalid:
            with self.subTest(row=row):
                self.assertIsNone(intake._valid_run(row))
        self.assertIsNone(intake._valid_run({"actor": []}))

    def test_unauthorized_run_never_downloads_or_imports(self):
        self.confirm()
        fake = self.api((9301, 41000, "2026-11-10T01:00:00+00:00"))
        fake.runs = [run_doc(9301, actor="stranger")]
        result = intake.poll_once(self.state, fake, now=CLOCK)
        self.assertEqual(result["state"], "NO_ELIGIBLE_NEW_SIGNED_ARTIFACT")
        self.assertEqual(fake.downloads, [])
        self.assertEqual(runtime.status(self.state)["counts"]["listings"], 0)

    def test_zip_traversal_absolute_symlink_duplicate_and_overflow_denied(self):
        files = signed_files(self.work / "producer-9501",
                             self.recipient, self.signer_raw,
                             9501, 41000, "2026-11-10T01:00:00+00:00")
        good = zip_members(files)
        self.assertTrue(good)
        for bad in (
            zip_members({**files, "../private": b"x"}),
            zip_members({**files, "/etc/passwd": b"x"}),
            zip_members({**files, "extra": b"x"}),
            zip_members({**files, "v434_live_output/" +
                         next(iter(files)): b"fake"}),
        ):
            with self.subTest(size=len(bad)):
                target = self.work / ("target-" + hashlib.sha256(bad).hexdigest()[:8])
                target.mkdir()
                with self.assertRaises(ValueError):
                    intake._unpack_exact(bad, target)
        target = self.work / "safe"
        target.mkdir()
        intake._unpack_exact(good, target)
        self.assertEqual({p.name for p in target.iterdir()}, intake.EXPECTED)

    def test_tampered_artifact_fails_before_sqlite_mutation(self):
        self.confirm()
        fake = self.api((9401, 42000, "2026-11-10T01:00:00+00:00"))
        files = signed_files(self.work / "new-producer-9401",
                             self.recipient, self.signer_raw, 9401,
                             42000, "2026-11-10T01:00:00+00:00")
        encrypted = "v434_private_candidate_links.encrypted.json"
        files[encrypted] += b" "
        fake.archives[9401] = zip_members(files)
        with self.assertRaises(ValueError):
            intake.poll_once(self.state, fake, now=CLOCK)
        self.assertEqual(runtime.status(self.state)["counts"]["listings"], 0)
        self.assertEqual(list((self.state / "inbox").iterdir()), [])

    def test_wrong_recovery_key_and_corrupt_cyphertext_fail(self):
        sealed, downloaded = self.confirm()
        other = self.work / "other"
        other.mkdir()
        synthetic_recovery_keypair(other)
        with self.assertRaisesRegex(ValueError, "OFFLINE_RESTORE_VERIFICATION_FAILED"):
            backup.inspect_backup(downloaded, other / "recovery-private.bin")
        envelope = json.loads(downloaded.read_text(encoding="utf-8"))
        envelope["ciphertext"] = "AAAA"
        downloaded.write_text(json.dumps(envelope), encoding="utf-8")
        with self.assertRaises(ValueError):
            backup.inspect_backup(downloaded, self.private)
        with self.assertRaisesRegex(ValueError, "OFFSITE_CIPHERTEXT_MISMATCH"):
            backup.register_offsite_confirmation(
                self.state, sealed, downloaded,
                operator_verified_offline_restore=True, now=CLOCK)

    def test_offsite_operator_confirmation_and_independent_keys(self):
        sealed = backup.create_backup(self.state, self.pub, now=CLOCK)
        downloaded = self.work / "download.sealed.json"
        downloaded.write_bytes(sealed.read_bytes())
        with self.assertRaisesRegex(ValueError, "OFFSITE_RESTORE_OPERATOR_CONFIRMATION_REQUIRED"):
            backup.register_offsite_confirmation(
                self.state, sealed, downloaded,
                operator_verified_offline_restore=False)
        original_public = (self.state / "keys" / runtime.PUBLIC_FILE)
        with self.assertRaisesRegex(ValueError, "RECOVERY_KEY_MUST_BE_INDEPENDENT"):
            backup.create_backup(self.state, original_public, now=CLOCK)

    def test_incomplete_run_catalog_and_missing_artifact(self):
        self.confirm()
        fake = self.api((9701, 42000, "2026-11-10T01:00:00+00:00"))
        fake.archives.clear()
        self.assertEqual(intake.poll_once(self.state, fake, now=CLOCK)["state"],
                         "NO_ELIGIBLE_NEW_SIGNED_ARTIFACT")
        class Overflow(FakeGitHub):
            def list_runs(self):
                return {"total_count": 101, "workflow_runs": self.runs}
        too_many = Overflow({}, [run_doc(9701)])
        with self.assertRaisesRegex(ValueError, "INCOMPLETE_GITHUB_RUN_CATALOG"):
            intake.poll_once(self.state, too_many, now=CLOCK)

    def test_secret_file_must_be_private_not_deploy_key(self):
        token_file = self.work / "actions-token"
        token_file.write_text("github_pat_" + "A" * 60, encoding="utf-8")
        if os.name == "posix":
            token_file.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "GITHUB_READ_TOKEN_FILE_MUST_BE_0600"):
                intake.GitHubREST(token_file)
            token_file.chmod(0o600)
        client = intake.GitHubREST(token_file)
        self.assertTrue(client._token.startswith("github_pat_"))


if __name__ == "__main__":
    unittest.main()
