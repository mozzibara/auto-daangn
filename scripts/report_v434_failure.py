# -*- coding: utf-8 -*-
"""Public-safe failure classification for explicitly approved v4.34 runs.

Never print untrusted website text, paths, URL/title, raw runner logs, encrypted
payloads, token material, or the recipient public key. The original capture
gate stays fail-closed. This diagnostic does not access the marketplace.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

OUTER_STATUSES = frozenset({
    "STOP_PREFLIGHT", "STOP_RUNTIME_LIMIT",
    "SEALED_CAPTURE_COMPLETE", "INCONCLUSIVE_SECURE_CAPTURE",
    "INCONCLUSIVE_INCOMPLETE_SECURE_CAPTURE",
})
INNER_STATUSES = frozenset({
    "PUBLIC_STATUS_SIGNAL_SURVEY_COMPLETE_NO_DIRECT_FOR_SALE_PROOF",
    "PUBLIC_DIRECT_FOR_SALE_UI_CONFIRMED",
    "INCONCLUSIVE_MISSING_PIPELINE_EVIDENCE",
    "INCONCLUSIVE_LEGACY_OR_INVALID_EVIDENCE",
    "INCONCLUSIVE_CONTEXT_IDENTITY",
    "QUARANTINED_OR_INCOMPLETE_PUBLIC_SIGNAL_SURVEY",
    "INCONCLUSIVE_INCOMPLETE_BOUNDED_CAPTURE",
    "INCONCLUSIVE_CAPTURE_ARTIFACTS_UNAVAILABLE",
    "INCONCLUSIVE_UPSTREAM_CAPTURE_FAILURE",
})
ROBOTS_REASONS = frozenset({
    "NOT_CHECKED", "ALLOWED", "DISALLOWED", "ROBOTS_NON_200",
    "ROBOTS_TOO_LARGE", "ROBOTS_UNAVAILABLE_HTTPError",
    "ROBOTS_UNAVAILABLE_URLError", "ROBOTS_UNAVAILABLE_TimeoutError",
})
# All emitted strings are fixed constants; never echo unrecognized values.


def _read(folder: Path, filename: str) -> dict:
    path = folder / filename
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16000:
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError, OSError):
        return {}
    return doc if type(doc) is dict else {}


def classify(folder: Path) -> dict[str, str]:
    outer = _read(folder, "v434_run_status.json")
    robots = _read(folder, "v434_robots_decision.json")
    inner = _read(folder, "v429_run_status.json")
    study = _read(folder, "v429_public_status_results.json")

    raw_outer = outer.get("status")
    if type(raw_outer) is str and raw_outer in OUTER_STATUSES:
        outer_code = raw_outer
    elif type(raw_outer) is str and raw_outer.startswith("STOP_ROBOTS_"):
        outer_code = "STOP_ROBOTS"
    elif type(raw_outer) is str and raw_outer.startswith("STOP_"):
        outer_code = "STOP_EXCEPTION_REDACTED"
    else:
        outer_code = "UNAVAILABLE_OR_UNKNOWN"

    raw_reason = robots.get("reason")
    robots_reason = (raw_reason if type(raw_reason) is str\n                     and raw_reason in ROBOTS_REASONS else "UNKNOWN")
    if (type(raw_reason) is str
            and raw_reason.startswith("ROBOTS_UNAVAILABLE_")
            and robots_reason == "UNKNOWN"):
        robots_reason = "ROBOTS_UNAVAILABLE_OTHER"

    raw_inner = inner.get("status")
    inner_code = (raw_inner if type(raw_inner) is str\n                  and raw_inner in INNER_STATUSES else "UNAVAILABLE_OR_UNKNOWN")
    status = study.get("evaluation")
    survey = status.get("status") if type(status) is dict else None
    survey_code = (survey if type(survey) is str\n                   and survey in INNER_STATUSES else "UNAVAILABLE_OR_UNKNOWN")

    http_status = robots.get("http_status")
    safe_http = (str(http_status) if type(http_status) is int
                 and 100 <= http_status <= 599 else "UNKNOWN")

    return {
        "CAPTURE_STATUS": outer_code,
        "CAPTURE_ATTEMPTED_LIVE": (
            "YES" if outer.get("attempted_live") is True else "NO"
        ),
        "ROBOTS_ALLOWED": (
            "YES" if robots.get("allowed") is True
            else "NO" if robots.get("allowed") is False else "UNKNOWN"
        ),
        "ROBOTS_REASON": robots_reason,
        "ROBOTS_HTTP_STATUS": safe_http,
        "INNER_CAPTURE_STATUS": inner_code,
        "SURVEY_STATUS": survey_code,
        "PUBLIC_SUMMARY_PRESENT": (
            "YES" if (folder / "v434_secure_links_summary.json").is_file()
            else "NO"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print public-safe capture failure classification")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    print("V434_REDACTED_FAILURE_DIAGNOSTIC_BEGIN")
    for key, value in classify(args.output_dir).items():
        print(f"{key}={value}")
    print("V434_REDACTED_FAILURE_DIAGNOSTIC_END")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
