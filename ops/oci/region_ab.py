# -*- coding: utf-8 -*-
"""Owner-approved OCI two-region one-shot locality / result-set A/B diagnostic.

No listing capture, persistence, Telegram, external URL navigation, login,
fingerprint manipulation or collection gate override. Exactly one native FILL
region choice in each of two fresh, isolated Chrome contexts.
"""
from __future__ import annotations

import argparse
import asyncio
import json

from app_v5.region_ab_sample import RegionABSession
from ops.oci.precollection import isolated_execution_directory
from scripts.chrome_stable_input_compare import (
    check_public_robots, one_public_region,
)
from scripts.run_live_checked import check_region_picker_robots

_APPROVAL = "I_APPROVE_OCI_REGION_AB_SAMPLE_V1"


def blocked(status):
    return {
        "schema": "oci_region_ab_aggregate_v1",
        "status": status,
        "authorizes_listings": False,
        "collection_started": False,
        "database_written": False,
        "telegram_used": False,
    }


async def run(*, live=False, headed=False, approval="", directory_check=None,
              robots=None, picker_robots=None, experiment=None):
    if live is not True or headed is not True or approval != _APPROVAL:
        return blocked("OWNER_APPROVAL_REQUIRED")
    check = directory_check or isolated_execution_directory
    if check() is not True:
        return blocked("ISOLATED_NON_ROOT_CHECKOUT_REQUIRED")
    check_robots = robots or check_public_robots
    check_picker = picker_robots or check_region_picker_robots
    try:
        if (check_robots() is not True or
                check_picker("불당동").get("allowed") is not True or
                check_picker("배방읍").get("allowed") is not True):
            return blocked("ROBOTS_NOT_ALLOWED")
    except Exception:
        return blocked("ROBOTS_NOT_ALLOWED")

    # Test injection keeps the exact same owner, directory and robots gates.
    if experiment is not None:
        try:
            value = await experiment()
            return value if type(value) is dict else blocked("DIAGNOSTIC_FAILURE")
        except Exception:
            return blocked("DIAGNOSTIC_FAILURE")

    try:
        from playwright.async_api import async_playwright
        session = RegionABSession()
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(channel="chrome", headless=False)
            try:
                left = await one_public_region(
                    browser, "FILL", region_key="cheonan",
                    click_navigation_wait="NO_WAIT_AFTER",
                    region_ab_session=session)
                # A challenge or missing authoritative locality stops the
                # experiment; do not run the control arm on an unready site.
                if left.get("status") != "TARGET_REGION_CONFIRMED_DIAGNOSTIC":
                    return session.summarize(left, {})
                right = await one_public_region(
                    browser, "FILL", region_key="asan",
                    click_navigation_wait="NO_WAIT_AFTER",
                    region_ab_session=session)
                return session.summarize(left, right)
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
    result = asyncio.run(run(
        live=args.live, headed=args.headed, approval=args.owner_approval))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "OBSERVED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
