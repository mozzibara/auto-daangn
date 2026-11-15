# -*- coding: utf-8 -*-
"""One-shot owner-approved Buldang/Sadang3/Buldang public Route experiment.

Fixed first-party Chrome interactions only. No URL synthesis, proxy,
geolocation spoofing, login, storage reuse, retry, product detail, DB write,
Telegram or collector-gate changes. Each arm gets a fresh browser context;
all item identities are digested with one volatile secret and discarded.
"""
from __future__ import annotations

import argparse
import asyncio
import json

from app_v5.region_aa_far import RegionAAFarSession
from ops.oci.precollection import isolated_execution_directory
from scripts.chrome_stable_input_compare import (
    check_public_robots, one_public_region,
)
from scripts.run_live_checked import check_region_picker_robots

_APPROVAL = "I_APPROVE_OCI_REGION_AA_FAR_V1"
_STEPS = (("a1", "cheonan"), ("far", "sadang"), ("a2", "cheonan"))
_STOP_STATUSES = frozenset((
    "ACCESS_RESTRICTED", "BASELINE_INVALID", "UNEXPECTED_EXCEPTION",
))


def blocked(status):
    return {
        "schema": "oci_region_aa_far_aggregate_v1",
        "status": status,
        "authorizes_listings": False,
        "collection_started": False,
        "database_written": False,
        "telegram_used": False,
    }


async def run(*, live=False, headed=False, approval="",
              directory_check=None, robots=None, picker_robots=None):
    # Approval MUST precede any environment probe or network activity.
    if live is not True or headed is not True or approval != _APPROVAL:
        return blocked("OWNER_APPROVAL_REQUIRED")
    directory = directory_check or isolated_execution_directory
    if directory() is not True:
        return blocked("ISOLATED_NON_ROOT_CHECKOUT_REQUIRED")
    check_robots = robots or check_public_robots
    check_picker = picker_robots or check_region_picker_robots
    try:
        if (check_robots() is not True or
                check_picker("불당동").get("allowed") is not True or
                check_picker("사당제3동").get("allowed") is not True):
            return blocked("ROBOTS_NOT_ALLOWED")
    except Exception:
        return blocked("ROBOTS_NOT_ALLOWED")

    try:
        from playwright.async_api import async_playwright
        session = RegionAAFarSession()
        observations = {}
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                channel="chrome", headless=False)
            try:
                for arm, region_key in _STEPS:
                    # one_public_region opens + closes its own disposable
                    # browser context, then inspects exactly one post-click
                    # Route response from the browser's normal UI flow.
                    row = await one_public_region(
                        browser, "FILL", region_key=region_key,
                        click_navigation_wait="NO_WAIT_AFTER",
                        region_ab_session=session,
                        region_diagnostic_arm_key=arm)
                    observations[arm] = row
                    state = row.get("status")
                    if state in _STOP_STATUSES:
                        break
                    # If first Buldang failed, no valid baseline can exist.
                    if arm == "a1" and state != (
                            "TARGET_REGION_CONFIRMED_DIAGNOSTIC"):
                        break
                    # A failed FAR header click may still permit one
                    # independent A2 (not a retry of the failed FAR click).
                    # Site access restrictions above always stop the run.
                return session.report(observations)
            finally:
                await browser.close()
    except Exception:
        return blocked("DIAGNOSTIC_FAILURE")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--owner-approval", default="")
    args = parser.parse_args(argv)
    report = asyncio.run(run(
        live=args.live, headed=args.headed, approval=args.owner_approval))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report.get("status") == "OBSERVED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
