# -*- coding: utf-8 -*-
"""Sign owner-approved v4.34 output only on the protected Actions runner.

Private signing key comes from an opt-in repository/environment secret;
neither the key nor raw item fields are printed or uploaded.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
from pathlib import Path
import subprocess
import sys

from app_v5.attestation import REPOSITORY, sign_capture


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if not (
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("GITHUB_REPOSITORY") == REPOSITORY
        and os.environ.get("GITHUB_ACTOR") == os.environ.get("GITHUB_REPOSITORY_OWNER")
        and os.environ.get("GITHUB_REF") == "refs/heads/main"
    ):
        print("PRODUCER_SIGNING_CONTEXT_REJECTED", file=sys.stderr)
        return 2
    try:
        encoded = os.environ["V434_ATTEST_ED25519_KEY_B64"].strip(" \t\r\n")
        secret = base64.b64decode(encoded, validate=True)
        if len(secret) != 32:
            raise ValueError("INVALID_SIGNER_SECRET_LENGTH")
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, encoding="utf-8"
        ).strip()
        bundle = sign_capture(
            args.output_dir, secret,
            run_id=int(os.environ["GITHUB_RUN_ID"]),
            run_attempt=int(os.environ["GITHUB_RUN_ATTEMPT"]),
            commit_sha=sha
        )
        target = args.output_dir / "v434_capture_attestation.json"
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(bundle, stream, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
        print("V434_CAPTURE_PROVENANCE_SIGNED")
        return 0
    except (OSError, KeyError, ValueError, TypeError, binascii.Error,
            subprocess.CalledProcessError):
        # No key, listing, filename, command stderr or object content in logs.
        print("V434_CAPTURE_PROVENANCE_SIGNING_REJECTED", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
