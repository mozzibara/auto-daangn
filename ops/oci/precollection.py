# -*- coding: utf-8 -*-
"""One-shot owner-approved OCI FILL locality + filter precollection check.

Separate from OCI signed-import runtime, databases and any listing collector.
Runs a disposable Chrome context once, then exits after UI+Route metadata
checks with an entirely redacted fixed-shape report. Not a capture pipeline.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from app_v5.precollection_filter_gate import (
    verify_filter_before_collection, sanitize_precollection,
)
from scripts.chrome_stable_input_compare import (
    check_public_robots, one_public_region,
)
from scripts.run_live_checked import check_region_picker_robots

_APPROVAL = "I_APPROVE_OCI_PRECOLLECTION_FILL_V1"


def isolated_execution_directory(path=None, *, home=None):
    """Reject root and all existing shared OCI runtime staging/state paths."""
    if os.name != "posix" or os.geteuid() == 0:
        return False
    cwd = Path(path or os.getcwd()).resolve()
    user_home = Path(home or Path.home()).resolve()
    try:
        relative = cwd.relative_to(user_home)
    except ValueError:
        return False
    # A standalone source checkout under the owner's home, not a service
    # or private OCI runtime tree. No authorization derived from checkout.
    return (len(relative.parts) >= 2
            and relative.parts[0] == "code"
            and relative.parts[1] == "auto-daangn-region-diagnostic"
            and ".git" not in relative.parts
            and "/var/lib/auto-daangn" not in str(cwd)
            and "/opt/auto-daangn" not in str(cwd))


def final_report(region_row):
    result = region_row if type(region_row) is dict else {}
    details = result.get("precollection")
    details = sanitize_precollection(details) if type(details) is dict else {}
    region_ok = result.get("status") == "TARGET_REGION_CONFIRMED_DIAGNOSTIC"
    filters_ok = (
        details.get("status") == "PRECOLLECTION_READY_REVIEW"
        and details.get("strict_filter_evidence") is True
        and details.get("region_gate_confirmed") is True
        and details.get("ui_selected_before_apply") is True
        and details.get("ui_selected_after_apply") is True
        and details.get("filter_apply_returned") is True
        and details.get("filtered_url_matches") is True
        and details.get("filtered_route_count") == 1
        and all(details.get("server_filters", {}).get(key) == "EXPECTED"
                for key in ("region", "category", "price_max", "available"))
    )
    if region_ok and filters_ok:
        status = "PRECOLLECTION_EVIDENCE_COMPLETE"
    elif not region_ok:
        status = "STOP_REGION_NOT_VERIFIED"
    else:
        status = "STOP_FILTERS_NOT_VERIFIED"
    return {
        "schema": "oci_fill_precollection_operator_v1",
        "status": status,
        "input_mode": "FILL",
        "region_status": result.get("status") if result.get("status") in (
            "TARGET_REGION_CONFIRMED_DIAGNOSTIC",
            "REGION_HEADER_ACTION_EXCEPTION",
            "REGION_OPTION_ACTION_EXCEPTION",
            "REGION_NOT_COMMITTED",
            "API_OR_DOM_NOT_READY",
            "CLICK_NOT_TRUSTED",
            "ACCESS_RESTRICTED",
            "BASELINE_INVALID",
            "UNEXPECTED_EXCEPTION",
            "INCONCLUSIVE",
        ) else "INCONCLUSIVE",
        "region_route_verified": region_ok,
        "region_header_timeout_reconciled": (result.get(
            "picker_phase_diagnostics", {}).get(
                "header_click_verified_after_timeout") is True),
        "precollection": details if region_ok else None,
        "production_runtime_modified": False,
        "collection_started": False,
        "listing_detail_visited": False,
        "listing_data_exported": False,
        "database_written": False,
        "authorizes_listings": False,
        "next_action_requires_separate_owner_approval": True,
    }


def blocked(reason):
    options = (
        "OWNER_APPROVAL_REQUIRED", "ISOLATED_NON_ROOT_CHECKOUT_REQUIRED",
        "ROBOTS_NOT_ALLOWED", "CHROME_OR_BROWSER_FAILURE",
    )
    return {
        "schema": "oci_fill_precollection_operator_v1",
        "status": reason if reason in options else "CHROME_OR_BROWSER_FAILURE",
        "input_mode": "FILL",
        "region_status": "INCONCLUSIVE",
        "region_route_verified": False,
        "precollection": None,
        "production_runtime_modified": False,
        "collection_started": False,
        "listing_detail_visited": False,
        "listing_data_exported": False,
        "database_written": False,
        "authorizes_listings": False,
        "next_action_requires_separate_owner_approval": True,
    }


async def run(*, approve, live, headed, robots=None, picker_robots=None,
              directory_check=None, diagnostic=None):
    if not (live is True and approve == _APPROVAL and headed is True):
        return blocked("OWNER_APPROVAL_REQUIRED")
    directory_check = directory_check or isolated_execution_directory
    if not directory_check():
        return blocked("ISOLATED_NON_ROOT_CHECKOUT_REQUIRED")
    robots = robots or check_public_robots
    picker_robots = picker_robots or check_region_picker_robots
    try:
        if (robots() is not True or picker_robots("불당동").get("allowed") is not True):
            return blocked("ROBOTS_NOT_ALLOWED")
    except Exception:
        return blocked("ROBOTS_NOT_ALLOWED")
    try:
        if diagnostic is not None:
            region_result = await diagnostic()
        else:
            from playwright.async_api import async_playwright
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(channel="chrome", headless=False)
                try:
                    # Exactly one FILL attempt, no SEQUENTIAL_KEYS, no repeat.
                    region_result = await one_public_region(
                        browser, "FILL",
                        on_region_confirmed=verify_filter_before_collection)
                finally:
                    await browser.close()
        return final_report(region_result)
    except Exception:
        return blocked("CHROME_OR_BROWSER_FAILURE")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--owner-approval", default="")
    options = parser.parse_args(argv)
    if not (options.live and options.headed
            and options.owner_approval == _APPROVAL):
        # No asyncio event loop or browser/robots client is constructed
        # without the full literal one-shot operator approval.
        report = blocked("OWNER_APPROVAL_REQUIRED")
    else:
        report = asyncio.run(run(
            approve=options.owner_approval, live=options.live,
            headed=options.headed))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if report["status"] == "PRECOLLECTION_EVIDENCE_COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
