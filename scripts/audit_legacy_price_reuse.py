# -*- coding: utf-8 -*-
"""Classify historical v4.18/v4.19 JSON result files offline, if available.

Does NOT run browser studies, make network calls, emit raw file contents,
modify existing evidence files or grant listing collection permission.
Missing files never imply historical price filtering was proven.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app_v5.historical_price_reuse_audit import audit_archived_price_reports


def _safe_read_json(path):
    if path is None:
        return None
    try:
        source = Path(path)
        if not source.is_file() or source.stat().st_size > 2_000_000:
            return {"version": "INVALID_ARCHIVAL_INPUT"}
        with source.open("rb") as stream:
            blob = stream.read(2_000_001)
        if len(blob) > 2_000_000:
            return {"version": "INVALID_ARCHIVAL_INPUT"}
        doc = json.loads(blob)
        return doc if type(doc) is dict else {"version": "INVALID_ARCHIVAL_INPUT"}
    except (OSError, ValueError, UnicodeError, TypeError):
        return {"version": "INVALID_ARCHIVAL_INPUT"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v418", type=Path,
                        help="Existing v418_price_crossover_results.json")
    parser.add_argument("--v419", type=Path,
                        help="Existing v419_filter_schema_results.json")
    args = parser.parse_args(argv)
    first = _safe_read_json(args.v418)
    second = _safe_read_json(args.v419)
    status = audit_archived_price_reports(first, second)
    # Only these fixed-enum classifications are printed, never file paths,
    # error strings, responses, seller/listing fields or user data.
    print(json.dumps(status, ensure_ascii=False, sort_keys=True))
    return 0 if status["archival_record_status"] == "SELF_REPORTED_COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
