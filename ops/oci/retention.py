# -*- coding: utf-8 -*-
"""Explicit, listing-scoped deletion for ephemeral used-goods monitoring.

No backup upload, marketplace access, or broad automatic retention policy.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

from app_v5.history import HistoryStore
from ops.oci import runtime


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Forget uninteresting listings or purge verified SOLD listings")
    parser.add_argument("action", choices=("forget", "purge-sold"))
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--listing-url", help="Exact canonical Daangn listing URL")
    parser.add_argument("--confirm-delete", action="store_true",
                        help="Required for irreversible database deletion")
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        if not args.confirm_delete:
            raise ValueError("EXPLICIT_DELETE_CONFIRMATION_REQUIRED")
        if args.action == "forget" and not args.listing_url:
            raise ValueError("LISTING_URL_REQUIRED")
        if args.action == "purge-sold" and args.listing_url is not None:
            raise ValueError("UNEXPECTED_LISTING_URL")
        root = runtime._root(args.state_dir, create=False)
        _, key, _ = runtime._keyring(root)
        store = HistoryStore(root / "db" / "history.sqlite3", key)
        if args.action == "forget":
            result = store.forget_listing(store.stable_key(args.listing_url))
            state = "LISTING_FORGOTTEN" if result["deleted"] else "LISTING_NOT_FOUND"
        else:
            result = store.purge_verified_sold()
            state = "VERIFIED_SOLD_PURGE_COMPLETE"
        print(json.dumps({"state": state, **result}, sort_keys=True))
        return 0
    except (ValueError, OSError, RuntimeError, sqlite3.Error):
        print("RETENTION_OPERATION_REJECTED", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
