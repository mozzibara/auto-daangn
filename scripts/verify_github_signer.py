# -*- coding: utf-8 -*-
"""Verify the configured Actions signing secret against the pinned public key.

Never print, persist, upload, or include the private secret in an exception.
This check uses no network and never visits marketplace pages.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import hmac
import os
from pathlib import Path
import sys

from app_v5.attestation import signing_public_key

KEY_PATH = (Path(__file__).resolve().parents[1] /
            "keys" / "v434" / "ed25519_trusted_public.bin")
EXPECTED_SHA256 = "54473a7acab59b546030d1115f03213c4b6ad7128a902206ef94439d117557e6"


def verify_signer_secret(secret_b64: str, public_key: bytes) -> bool:
    """Use exact 32-byte Ed25519 seed, not X25519 private key or PEM."""
    if not isinstance(secret_b64, str):
        return False
    # A GitHub Secret pasted from a .txt file may retain a final CRLF/LF.
    # Do not permit whitespace embedded in the base64 seed.
    secret_b64 = secret_b64.strip(" \t\r\n")
    if len(secret_b64) != 44:
        return False
    if not isinstance(public_key, bytes) or len(public_key) != 32:
        return False
    if not hmac.compare_digest(hashlib.sha256(public_key).hexdigest(),
                               EXPECTED_SHA256):
        return False
    try:
        secret = base64.b64decode(secret_b64, validate=True)
        if len(secret) != 32:
            return False
        actual = signing_public_key(secret)
        return hmac.compare_digest(actual, public_key)
    except (ValueError, TypeError, binascii.Error):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check signer seed against the pinned public verifier key.")
    parser.add_argument("--local-secret-file", type=Path)
    args = parser.parse_args(argv)
    try:
        public = KEY_PATH.read_bytes()
        if args.local_secret_file is not None:
            if os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI"):
                raise ValueError("LOCAL_FILE_CHECK_NOT_ALLOWED_IN_CI")
            if (args.local_secret_file.is_symlink()
                    or not args.local_secret_file.is_file()):
                raise ValueError("LOCAL_KEY_NOT_REGULAR_FILE")
            secret = args.local_secret_file.read_text(encoding="utf-8")
        else:
            secret = os.environ.get("V434_ATTEST_ED25519_KEY_B64", "")
        matched = verify_signer_secret(secret, public)
    except (OSError, UnicodeError, ValueError):
        matched = False
    if not matched:
        # Distinguish an absent secret from a malformed/wrong key without
        # printing the secret, its length, or any derived key bytes.
        code = ("V434_ED25519_SIGNER_SECRET_NOT_CONFIGURED"
                if (args.local_secret_file is None and
                    not os.environ.get("V434_ATTEST_ED25519_KEY_B64", "").strip())
                else "V434_ED25519_SIGNER_SECRET_MISMATCH_OR_INVALID_FORMAT")
        print(code, file=sys.stderr)
        return 2
    print("V434_ED25519_SIGNER_PUBLIC_KEY_MATCH")
    print("PINNED_SIGNER_KEY_ID=" + EXPECTED_SHA256[:24])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
