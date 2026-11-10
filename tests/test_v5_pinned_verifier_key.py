# -*- coding: utf-8 -*-
"""Ensure the checked-in Ed25519 PUBLIC verifier matches the owner's pinned key."""
from __future__ import annotations

import hashlib
from pathlib import Path
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


PUBLIC_KEY = (Path(__file__).resolve().parents[1] /
              "keys" / "v434" / "ed25519_trusted_public.bin")
EXPECTED_SHA256 = "54473a7acab59b546030d1115f03213c4b6ad7128a902206ef94439d117557e6"
EXPECTED_KEY_ID = "54473a7acab59b546030d111"


class PinnedVerifierKeyTests(unittest.TestCase):
    def test_owner_public_key_matches_independent_fingerprint(self):
        raw = PUBLIC_KEY.read_bytes()
        self.assertEqual(len(raw), 32)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), EXPECTED_SHA256)
        self.assertEqual(hashlib.sha256(raw).hexdigest()[:24], EXPECTED_KEY_ID)
        Ed25519PublicKey.from_public_bytes(raw)


if __name__ == "__main__":
    unittest.main()
