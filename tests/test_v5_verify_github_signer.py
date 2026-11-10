# -*- coding: utf-8 -*-
"""Synthetic offline signing-key match tests; no GitHub Actions secret read."""
from __future__ import annotations
import base64
from contextlib import redirect_stdout
from io import StringIO
import hashlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.verify_github_signer import (
    EXPECTED_SHA256, KEY_PATH, main, verify_signer_secret
)


class SignerSecretCheckTests(unittest.TestCase):
    def test_stored_public_key_is_32_bytes_and_pinned(self):
        data = KEY_PATH.read_bytes()
        self.assertEqual(len(data), 32)
        self.assertEqual(hashlib.sha256(data).hexdigest(), EXPECTED_SHA256)

    def test_text_file_line_endings_do_not_change_seed(self):
        # The mismatch may arise from pasting an entire base64 .txt file.
        # Use a synthetic key; never read the actual GitHub Secret here.
        seed = Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption()
        )
        encoded = base64.b64encode(seed).decode("ascii")
        # The verifier may only trust the independent pinned key, so
        # extra newline must not change the decision for this random seed.
        pub = Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        # Patch the test-only trust fingerprint so valid synthetic signatures
        # exercise the POSITIVE path without the real Actions secret.
        with patch("scripts.verify_github_signer.EXPECTED_SHA256",
                   hashlib.sha256(pub).hexdigest()):
            self.assertTrue(verify_signer_secret(encoded, pub))
            for suffix in ("\n", "\r\n", "  "):
                with self.subTest(suffix=repr(suffix)):
                    self.assertTrue(verify_signer_secret(encoded + suffix, pub))
            self.assertFalse(verify_signer_secret(encoded[:20] + " " + encoded[20:], pub))

    def test_local_secret_file_cli_uses_same_pinned_verifier(self):
        seed = Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption()
        )
        pub = Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        with TemporaryDirectory() as name:
            folder = Path(name)
            secret_path = folder / "secret.txt"
            public_path = folder / "trusted.bin"
            secret_path.write_text(base64.b64encode(seed).decode("ascii") + "\n",
                                   encoding="utf-8")
            public_path.write_bytes(pub)
            stdout = StringIO()
            with (patch("scripts.verify_github_signer.KEY_PATH", public_path),
                  patch("scripts.verify_github_signer.EXPECTED_SHA256",
                        hashlib.sha256(pub).hexdigest()),
                  patch.dict(os.environ, {"CI": "", "GITHUB_ACTIONS": "",
                                         "V434_ATTEST_ED25519_KEY_B64": ""}),
                  redirect_stdout(stdout)):
                self.assertEqual(main(["--local-secret-file", str(secret_path)]), 0)
            self.assertIn("V434_ED25519_SIGNER_PUBLIC_KEY_MATCH", stdout.getvalue())

    def test_wrong_seed_never_matches_pinned_key(self):
        random_seed = Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption()
        )
        self.assertFalse(verify_signer_secret(
            base64.b64encode(random_seed).decode("ascii"), KEY_PATH.read_bytes()
        ))

    def test_reject_invalid_secret_without_logging(self):
        for bad in ("", "not-a-secret", "@@" * 22,
                    base64.b64encode(b"x" * 16).decode("ascii")):
            with self.subTest(value_type="invalid"):
                self.assertFalse(verify_signer_secret(bad, KEY_PATH.read_bytes()))

    def test_incorrect_verifier_refused(self):
        seed = Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption()
        )
        pub = Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.assertFalse(verify_signer_secret(
            base64.b64encode(seed).decode("ascii"), pub
        ))


if __name__ == "__main__":
    unittest.main()
