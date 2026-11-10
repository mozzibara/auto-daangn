# -*- coding: utf-8 -*-
"""Generate a private Ed25519 producer key and a pinned public verifier key.

Run only on a trusted OWNER machine. Never run in CI and never commit secrets.
Writes files with exclusive creation; deliberately does not print key material.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import os
from pathlib import Path
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path,
                        default=Path("local_private/v434-signer"))
    args = parser.parse_args(argv)
    if os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI"):
        print("SIGNER_KEYGEN_FORBIDDEN_IN_CI", file=sys.stderr)
        return 2
    root = args.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    secret = root / "ed25519_signer_secret_b64.txt"
    trusted = root / "ed25519_trusted_public.bin"
    if secret.exists() or trusted.exists():
        print("SIGNER_KEY_FILES_ALREADY_EXIST", file=sys.stderr)
        return 2
    signer = Ed25519PrivateKey.generate()
    private_raw = signer.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
        serialization.NoEncryption()
    )
    public_raw = signer.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    for path, data in (
        (secret, base64.b64encode(private_raw) + b"\n"),
        (trusted, public_raw)
    ):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
    print("SIGNER_KEYPAIR_CREATED")
    print("SIGNER_KEY_ID=" + hashlib.sha256(public_raw).hexdigest()[:24])
    print("PRIVATE_KEY_MUST_REMAIN_LOCAL_OR_IN_GITHUB_ACTIONS_SECRET")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
