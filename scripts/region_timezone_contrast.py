# -*- coding: utf-8 -*-
"""Owner-approved, two-arm Playwright Chrome timezone hypothesis comparison.

DEFAULT and ASIA_SEOUL arms use the SAME hosted runner, Chrome installation,
browser process, locale, public search and FILL method. Only timezone_id
differs. Two visits at most, no login, seller data or listing detail visits.
A changed outcome can suggest a timezone effect but does not prove causality
because the requests are sequential and the server may vary over time.
"""
from __future__ import annotations

import argparse
import asyncio
import json

from app_v5.region_baseline_contrast import (
    safe_machine_class, optional_egress_context, sanitize_egress,
)
from scripts.chrome_stable_input_compare import (
    one_public_region, check_public_robots,
)
from scripts.run_live_checked import check_region_picker_robots
import daangn_v4_1_core as core

APPROVAL = "I_APPROVE_TIMEZONE_REGION_CONTRAST_V1"
SCHEMA = "daangn_timezone_region_contrast_v1"
ARMS = (("DEFAULT", None), ("ASIA_SEOUL", "Asia/Seoul"))
_STOP = ("ACCESS_RESTRICTED", "BASELINE_INVALID", "UNEXPECTED_EXCEPTION")


def classify_arms(attempts):
    rows=attempts if type(attempts) is list else []
    if len(rows)!=2 or [x.get("arm") for x in rows if type(x) is dict]!=[
            "DEFAULT","ASIA_SEOUL"]:
        status="INCOMPLETE"
    else:
        a,b=rows
        a_source=a.get("result") if type(a.get("result")) is dict else {}
        b_source=b.get("result") if type(b.get("result")) is dict else {}
        x=a_source.get("initial_baseline",{}).get("browser",{}).get("timezone")
        y=b_source.get("initial_baseline",{}).get("browser",{}).get("timezone")
        if x!="OTHER" or y!="ASIA_SEOUL":
            status="TIMEZONE_NOT_SEPARATED"
        elif a_source.get("initial_baseline",{}).get("initial_header_family")!=(
                b_source.get("initial_baseline",{}).get("initial_header_family")):
            status="STARTING_REGION_DIFFERENT"
        elif a_source.get("status")=="REGION_NOT_COMMITTED" and (
                b_source.get("status")=="TARGET_REGION_CONFIRMED_DIAGNOSTIC"):
            status="DEFAULT_FAILED_SEOUL_CONFIRMED"
        elif a_source.get("status")=="REGION_NOT_COMMITTED" and (
                b_source.get("status")=="REGION_NOT_COMMITTED"):
            status="BOTH_REGION_NOT_COMMITTED"
        elif (a_source.get("status")=="TARGET_REGION_CONFIRMED_DIAGNOSTIC" and
                b_source.get("status")=="TARGET_REGION_CONFIRMED_DIAGNOSTIC"):
            status="BOTH_REGION_CONFIRMED"
        else:
            status="INCONCLUSIVE"
    return {
        "status":status,
        "causation_proven":False,
        "ip_causation_proven":False,
        "result_authorizes_listings":False,
    }


async def run(*, live=False, headed=False, egress=False):
    from playwright.async_api import async_playwright
    report={
        "schema":SCHEMA,
        "machine":safe_machine_class(),
        "egress":sanitize_egress(None),
        "status":"OFFLINE_FIXTURE",
        "fixture_ok":False,
        "timezone_fixture_ok":False,
        "attempts":[],
        "hypothesis":classify_arms([]),
        "network_location_is_only_context":True,
        "authorizes_listings":False,
    }
    if live:
        if not check_public_robots() or (
                check_region_picker_robots(
                    core.BY_KEY["cheonan"]["term"]).get("allowed") is not True):
            report["status"]="ACCESS_RESTRICTED"
            return report
        if egress:
            report["egress"]=await asyncio.to_thread(
                optional_egress_context,enabled=True)
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(channel="chrome",headless=not headed)
        try:
            from scripts.chrome_stable_input_compare import (
                one_fixture, delegated_manual_fixture)
            fixtures=[]
            for mode in ("FILL","SEQUENTIAL_KEYS"):
                fixtures.append(await one_fixture(browser,mode))
            manual=await delegated_manual_fixture(browser)
            report["fixture_ok"]=(
                all(row["status"]=="FIXTURE_COMPLETE" and row["input_events"]["armed"]
                    for row in fixtures)
                and manual.get("armed") is True
                and manual.get("observed_input") is True
                and manual.get("preserved_after_dialog_removal") is True)
            if not report["fixture_ok"]:
                report["status"]="OFFLINE_FIXTURE_FAILED"
                return report
            # Verify timezone_id actually changes Intl.DateTimeFormat() on a
            # local blank page. No Daangn navigation for this fixture.
            tz_context=await browser.new_context(locale="ko-KR",
                timezone_id="Asia/Seoul")
            try:
                tz_page=await tz_context.new_page()
                await tz_page.set_content("<!doctype html><html><body></body></html>")
                tz_name=await tz_page.evaluate(
                    "() => Intl.DateTimeFormat().resolvedOptions().timeZone")
                report["timezone_fixture_ok"]=(tz_name=="Asia/Seoul")
            finally:
                await tz_context.close()
            if not report["timezone_fixture_ok"]:
                report["status"]="TIMEZONE_FIXTURE_FAILED"
                return report
            if not live:
                return report
            report["status"]="LIVE_DIAGNOSTIC"
            for arm,tz in ARMS:
                item=await one_public_region(browser,"FILL",timezone_id=tz)
                report["attempts"].append({"arm":arm,"result":item})
                if item["status"] in _STOP:
                    break
            report["hypothesis"]=classify_arms(report["attempts"])
            if len(report["attempts"])!=2:
                report["status"]="INCOMPLETE"
        finally:
            await browser.close()
    return report


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--live",action="store_true")
    parser.add_argument("--headed",action="store_true")
    parser.add_argument("--egress-context",action="store_true")
    parser.add_argument("--owner-approval",default="")
    args=parser.parse_args(argv)
    if args.egress_context and not args.live:
        print("EGRESS_REQUIRES_LIVE")
        return 2
    if args.live and args.owner_approval!=APPROVAL:
        print("EXACT_OWNER_APPROVAL_REQUIRED")
        return 2
    try:
        result=asyncio.run(run(live=args.live,headed=args.headed,
                               egress=args.egress_context))
    except Exception:
        print("TIMEZONE_CONTRAST_FAILED")
        return 2
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2))
    return 0 if result["fixture_ok"] and result["timezone_fixture_ok"] and result["status"] in (
        "OFFLINE_FIXTURE","LIVE_DIAGNOSTIC") else 2


if __name__=="__main__":
    raise SystemExit(main())
