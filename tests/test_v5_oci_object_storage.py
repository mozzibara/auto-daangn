# -*- coding: utf-8 -*-
"""Synthetic OCI Object Storage readback, offline baseline and unattended gate."""
from __future__ import annotations

import base64
import importlib.util
from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
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

from app_v5.attestation import signing_public_key
from ops.oci import backup, object_storage, runtime

CLOCK = datetime.now(timezone.utc).replace(microsecond=0)


def make_offline_keys(folder: Path):
    key = X25519PrivateKey.generate()
    runtime._new_file(folder / "recovery-private.bin",
                      key.private_bytes(serialization.Encoding.Raw,
                                        serialization.PrivateFormat.Raw,
                                        serialization.NoEncryption()))
    runtime._new_file(folder / "recovery-public.b64", base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)) + b"\n")


class FakeStore:
    def __init__(self, corrupt=False):
        self.objects = {}
        self.puts = 0
        self.gets = 0
        self.corrupt = corrupt

    def put_once(self, name, contents):
        self.puts += 1
        self.objects.setdefault(name, contents)

    def get(self, name):
        self.gets += 1
        result = self.objects[name]
        return result + b"extra" if self.corrupt else result


class OciObjectStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.state = self.folder / "state"
        signer = Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
            serialization.NoEncryption())
        trust = self.folder / "public.bin"
        public = signing_public_key(signer)
        trust.write_bytes(public)
        for name, value in (
            ("TRUSTED_SIGNER", trust),
            ("PINNED_SIGNER_SHA256", hashlib.sha256(public).hexdigest()),
        ):
            p = patch("ops.oci.runtime." + name, value)
            p.start()
            self.addCleanup(p.stop)
        runtime.initialize(self.state)
        self.offline = self.folder / "offline"
        self.offline.mkdir()
        make_offline_keys(self.offline)
        self.recovery_public = self.state / object_storage.RECPUB_REL
        runtime._new_file(self.recovery_public,
                          (self.offline / "recovery-public.b64").read_bytes())
        self.settings = {
            "version": 1, "region": "ap-chuncheon-1",
            "namespace": "syntheticnamespace", "bucket": "private-backup",
            "prefix": "auto-daangn/snapshots",
        }
        self.config = self.state / object_storage.CONFIG_REL
        runtime._new_file(self.config,
                          json.dumps(self.settings).encode("utf-8"))
        self.cloud = FakeStore()

    def establish_manual_baseline(self, *, clock=CLOCK):
        sent = object_storage.sync_backup(
            self.state, self.cloud, self.settings, now=clock)
        self.assertEqual(sent["state"], "OBJECT_STORAGE_READBACK_VERIFIED")
        got = backup.inspect_backup(Path(sent["readback_path"]),
            self.offline / "recovery-private.bin")
        self.assertEqual(got["state"], "OFFLINE_RESTORE_VERIFIED")
        verified = backup.register_offsite_confirmation(
            self.state, Path(sent["archive_path"]), Path(sent["readback_path"]),
            operator_verified_offline_restore=True, now=clock)
        self.assertEqual(verified["state"], "OFFSITE_BACKUP_CONFIRMED")
        return sent

    def test_settings_validation_is_offline_and_no_oci_client_required(self):
        self.assertEqual(object_storage.load_settings(self.state), self.settings)
        for changed in (
            {"region": "file:///etc/passwd"},
            {"prefix": "../outside"},
            {"bucket": "/wrong/bucket"},
            {"token": "should-never-be-in-config"},
        ):
            broken = dict(self.settings, **changed)
            self.config.write_text(json.dumps(broken), encoding="utf-8")
            with self.subTest(broken=changed):
                with self.assertRaises(ValueError):
                    object_storage.load_settings(self.state)


    @unittest.skipUnless(importlib.util.find_spec("oci") is not None,
                         "OCI SDK optional; dedicated Object Storage CI installs it")
    def test_official_sdk_instance_principal_immutable_put_and_bounded_get(self):
        import oci
        with patch.object(oci.auth.signers, "InstancePrincipalsSecurityTokenSigner",
                          return_value=object()) as signer:
            with patch.object(oci.object_storage, "ObjectStorageClient") as maker:
                cli = object_storage.InstancePrincipalObjectStore(
                    region="ap-chuncheon-1",
                    namespace="syntheticnamespace",
                    bucket="private-backup")
                self.assertEqual(signer.call_count, 1)
                self.assertEqual(maker.call_args.kwargs["config"]["region"],
                                 "ap-chuncheon-1")
                data = b"sealed bytes only"
                cli.put_once("auto-daangn/snapshots/test", data)
                self.assertEqual(maker.return_value.put_object.call_args.kwargs[
                    "if_none_match"], "*")
                self.assertEqual(maker.return_value.put_object.call_args.kwargs[
                    "content_length"], len(data))
                stream = BytesIO(data)
                maker.return_value.get_object.return_value = SimpleNamespace(
                    data=SimpleNamespace(raw=stream, close=lambda: None))
                self.assertEqual(cli.get("auto-daangn/snapshots/test"), data)

    @unittest.skipUnless(os.name == "posix", "POSIX permissions")
    def test_world_readable_bucket_settings_rejected(self):
        self.config.chmod(0o644)
        with self.assertRaisesRegex(ValueError,
                "OBJECT_STORAGE_CONFIG_MISSING_OR_UNSAFE"):
            object_storage.load_settings(self.state)
        self.config.chmod(0o600)

    def test_first_cloud_upload_without_offline_restore_cannot_unlock_intake(self):
        sent = object_storage.sync_backup(
            self.state, self.cloud, self.settings, now=CLOCK)
        self.assertTrue(sent["object_name"].startswith("auto-daangn/snapshots/"))
        self.assertEqual(self.cloud.puts, 1)
        self.assertEqual(self.cloud.gets, 1)
        self.assertFalse(sent["offline_restore_verified"])
        self.assertEqual(hashlib.sha256(
            Path(sent["archive_path"]).read_bytes()).hexdigest(), sent["sha256"])
        self.assertNotIn(runtime._keyring(self.state)[0], self.cloud.get(
            sent["object_name"]))
        with self.assertRaisesRegex(ValueError, "OFFSITE_VERIFIED_BACKUP_REQUIRED"):
            backup.require_recent_offsite_backup(self.state, now=CLOCK)
        with self.assertRaisesRegex(ValueError, "INDEPENDENT_OFFLINE_RESTORE_BASELINE_REQUIRED"):
            object_storage.sync_backup(self.state, self.cloud, self.settings,
                                       now=CLOCK, unattended=True)

    def test_independently_restored_baseline_enables_safe_automatic_refresh(self):
        self.establish_manual_baseline()
        status = backup.require_recent_offsite_backup(self.state, now=CLOCK)
        self.assertEqual(status["state"], "OFFSITE_BACKUP_GATE_PASS")
        probe = object_storage.probe_existing_remote(
            self.state, self.cloud, self.settings)
        # Probe uses real now; it will fail in CI if baseline is synthetic past.
        self.assertEqual(probe["state"], "OBJECT_STORAGE_BASELINE_REMOTE_PROBE_PASS")

        before = self.cloud.puts
        skipped = object_storage.sync_backup(
            self.state, self.cloud, self.settings,
            now=CLOCK + timedelta(hours=2), unattended=True)
        self.assertEqual(skipped["state"], "REMOTE_BACKUP_FRESH_SKIP")
        self.assertEqual(before, self.cloud.puts)
        auto = object_storage.sync_backup(
            self.state, self.cloud, self.settings,
            now=CLOCK + timedelta(hours=13), unattended=True)
        self.assertEqual(auto["state"], "CLOUD_READBACK_BACKUP_CONFIRMED")
        self.assertFalse(auto["offline_restore_verified"])
        receipt = json.loads((self.state / backup.RECEIPT).read_text(encoding="utf-8"))
        self.assertFalse(receipt["offline_restore_operator_confirmed"])
        self.assertEqual(receipt["verification_mode"],
                         "CLOUD_READBACK_WITH_OFFLINE_BASELINE")
        self.assertEqual(backup.require_recent_offsite_backup(
            self.state, now=CLOCK + timedelta(hours=13))["state"],
            "OFFSITE_BACKUP_GATE_PASS")

    def test_expired_independent_baseline_blocks_automatic_backup(self):
        self.establish_manual_baseline()
        with self.assertRaisesRegex(ValueError, "OFFLINE_RESTORE_BASELINE_EXPIRED"):
            object_storage.sync_backup(
                self.state, self.cloud, self.settings,
                now=CLOCK + timedelta(days=31), unattended=True)
        self.assertEqual(self.cloud.puts, 1)

    def test_changed_recovery_key_requires_fresh_manual_offline_restore(self):
        self.establish_manual_baseline()
        other = self.folder / "other"
        other.mkdir()
        make_offline_keys(other)
        self.recovery_public.write_bytes(
            (other / "recovery-public.b64").read_bytes())
        with self.assertRaisesRegex(ValueError,
                "RECOVERY_PUBLIC_KEY_CHANGED_REQUIRES_OFFLINE_RESTORE"):
            object_storage.sync_backup(
                self.state, self.cloud, self.settings,
                now=CLOCK + timedelta(hours=13), unattended=True)

    def test_remote_corruption_never_confirms_backup(self):
        broken = FakeStore(corrupt=True)
        with self.assertRaisesRegex(ValueError, "OBJECT_STORAGE_READBACK_SHA256_MISMATCH"):
            object_storage.sync_backup(self.state, broken, self.settings, now=CLOCK)
        self.assertFalse((self.state / backup.RECEIPT).exists())

    def test_collision_does_not_replace_immutable_remote_object(self):
        sealed = backup.create_backup(self.state, self.recovery_public, now=CLOCK)
        key = object_storage._remote_name(self.settings, sealed)
        self.cloud.objects[key] = b"malicious"
        with self.assertRaisesRegex(ValueError, "OBJECT_STORAGE_READBACK_SHA256_MISMATCH"):
            object_storage.upload_and_readback(
                self.state, sealed, self.cloud, self.settings)
        self.assertEqual(self.cloud.objects[key], b"malicious")

    def test_offline_recovery_baseline_missing_fails_closed(self):
        self.establish_manual_baseline()
        (self.state / backup.BASELINE).unlink()
        with self.assertRaisesRegex(ValueError, "INDEPENDENT_OFFLINE_RESTORE_BASELINE_REQUIRED"):
            object_storage.sync_backup(
                self.state, self.cloud, self.settings,
                now=CLOCK + timedelta(hours=13), unattended=True)

    def test_status_does_not_need_network_or_sdk(self):
        with patch("ops.oci.object_storage.InstancePrincipalObjectStore",
                   side_effect=AssertionError("MUST_NOT_CALL_NETWORK")):
            self.assertEqual(object_storage.main(
                ["status", "--state-dir", str(self.state)]), 0)

    def test_wrong_object_name_or_unexpected_local_file_rejected(self):
        runtime._dir(self.state, "backup", create=True)
        external = self.folder / "snapshot-20261110T120000-123456789abc.sealed.json"
        external.write_bytes(b"not encrypted")
        with self.assertRaisesRegex(ValueError,
                "ENCRYPTED_SNAPSHOT_MUST_BE_IN_PRIVATE_BACKUP_DIR"):
            object_storage.upload_and_readback(
                self.state, external, self.cloud, self.settings)
        with self.assertRaisesRegex(ValueError, "NON_CANONICAL_ENCRYPTED_SNAPSHOT_NAME"):
            object_storage._remote_name(
                self.settings, self.folder / "../../key.bin")


if __name__ == "__main__":
    unittest.main()
