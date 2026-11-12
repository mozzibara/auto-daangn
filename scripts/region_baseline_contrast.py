# -*- coding: utf-8 -*-
"""One-click-free, owner-approved initial-region observation across hosts.

Offline by default. --live performs ONE robots-permitted ordinary public
search page navigation and no region-selection click, item visit, login,
proxy, fingerprint spoofing, storage reuse or bypass. --egress-context is a
separate explicit third-party IP geolocation lookup with sanitized output.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

from app_v5.manual_chrome_region import (
    SEARCH_URL, ManualSearchResponses, is_public_search,
)
from app_v5.region_baseline_contrast import (
    capture_first_load, sanitize_baseline, safe_machine_class,
    optional_egress_context, sanitize_egress, compare_baselines,
)
from scripts.chrome_stable_input_compare import check_public_robots
import daangn_v4_1_core as core

_APPROVAL = "I_APPROVE_REGION_BASELINE_V1"
_BROWSER = "GOOGLE_CHROME_STABLE"
_MAX_CAPTURE = 1
_SCHEMA = "daangn_initial_region_baseline_v1"


def sanitized_report(source):
    x=source if type(source) is dict else {}
    samples=x.get("snapshots") if type(x.get("snapshots")) is dict else {}
    env=x.get("machine") if type(x.get("machine")) is dict else {}
    safe_machine=safe_machine_class(
        environ={"GITHUB_ACTIONS":"true" if env.get("runtime")=="GITHUB_HOSTED" else "",
                 "CI":"true" if env.get("runtime")=="OTHER_CI" else "",
                 "HTTPS_PROXY":"1" if env.get("http_proxy_configured") is True else ""},
        system=("Windows" if env.get("os")=="WINDOWS" else
                "Linux" if env.get("os")=="LINUX" else "Other"))
    return {
        "schema":_SCHEMA, "browser":_BROWSER,
        "site_visit": "ONE_PUBLIC_SEARCH_PAGE" if x.get("site_visit")==
                      "ONE_PUBLIC_SEARCH_PAGE" else "NO_SITE_VISIT",
        "http_class":x.get("http_class") if x.get("http_class") in (
            "HTTP_200","HTTP_RESTRICTED","HTTP_OTHER","NOT_RUN") else "NOT_RUN",
        "machine":safe_machine,
        "egress":sanitize_egress(x.get("egress")),
        "snapshots":{
            k:sanitize_baseline(samples.get(k))
            for k in ("BASELINE_DOM_READY","BASELINE_SETTLED")},
        "status":x.get("status") if x.get("status") in (
            "OFFLINE_FIXTURE","BASELINE_OBSERVED","ACCESS_RESTRICTED",
            "NO_CHROME","INITIAL_PAGE_INVALID","OBSERVATION_ERROR")
            else "OBSERVATION_ERROR",
        "region_click_attempted":False,
        "listing_links_visited":False,
        "login_used":False,
        "authorizes_listings":False,
    }


async def observe(*, live=False, headed=False, egress_context=False):
    from playwright.async_api import async_playwright

    result={
        "site_visit":"NO_SITE_VISIT",
        "http_class":"NOT_RUN", "status":"OBSERVATION_ERROR",
        "machine":safe_machine_class(),
        "egress":optional_egress_context(enabled=False),
        "snapshots":{},
    }
    if live and not check_public_robots():
        result["status"]="ACCESS_RESTRICTED"
        return sanitized_report(result)
    # The HTTP request to the optional IP metadata provider is performed
    # only after public-site robots validation; it is NOT a Daangn request.
    result["egress"]=await asyncio.to_thread(
        optional_egress_context,enabled=live and egress_context)
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(channel="chrome",headless=not headed)
        try:
            context=await browser.new_context(
                locale="ko-KR",viewport={"width":1280,"height":850})
            try:
                page=await context.new_page()
                observer=ManualSearchResponses(core.BY_KEY["cheonan"])
                if live:
                    page.on("request",observer.on_request)
                    page.on("response",observer.on_response)
                    response=await page.goto(
                        SEARCH_URL,wait_until="domcontentloaded",timeout=25000)
                    result["site_visit"]="ONE_PUBLIC_SEARCH_PAGE"
                    if response is None:
                        result["status"]="INITIAL_PAGE_INVALID"
                        return sanitized_report(result)
                    result["http_class"]=(
                        "HTTP_200" if response.status==200 else
                        "HTTP_RESTRICTED" if response.status in core.BLOCK_STATUS
                        else "HTTP_OTHER")
                    if result["http_class"]=="HTTP_RESTRICTED":
                        result["status"]="ACCESS_RESTRICTED"
                        return sanitized_report(result)
                    if response.status!=200 or not is_public_search(page.url):
                        result["status"]="INITIAL_PAGE_INVALID"
                        return sanitized_report(result)
                else:
                    # Offline HTML fixture: never navigate to marketplace.
                    await page.set_content(
                        "<!doctype html><html lang='ko'><body>"
                        "<button type='button' aria-label='지역 선택: 불당동'>"
                        "지역 선택: 불당동</button></body></html>")
                if live:
                    await observer.drain()
                result["snapshots"]["BASELINE_DOM_READY"]=await capture_first_load(
                    page,core.BY_KEY["cheonan"],passive_events=list(observer.events))
                if live:
                    await page.wait_for_timeout(1600)
                    await observer.drain()
                result["snapshots"]["BASELINE_SETTLED"]=await capture_first_load(
                    page,core.BY_KEY["cheonan"],passive_events=list(observer.events))
                if observer.blocked:
                    result["status"]="ACCESS_RESTRICTED"
                else:
                    result["status"]=("BASELINE_OBSERVED" if live
                                      else "OFFLINE_FIXTURE")
            finally:
                await context.close()
        finally:
            await browser.close()
    return sanitized_report(result)


def load_report(path):
    with Path(path).open("r",encoding="utf-8") as stream:
        raw=json.load(stream)
    if type(raw) is not dict or raw.get("schema")!=_SCHEMA:
        raise ValueError("INCOMPATIBLE_BASELINE_REPORT")
    return sanitized_report(raw)


def comparison(local, hosted):
    a=load_report(local)
    b=load_report(hosted)
    if (a["status"]!="BASELINE_OBSERVED" or
            b["status"]!="BASELINE_OBSERVED"):
        raise ValueError("BOTH_LIVE_BASELINES_REQUIRED")
    evidence=compare_baselines(
        a["snapshots"]["BASELINE_SETTLED"],
        b["snapshots"]["BASELINE_SETTLED"])
    evidence["egress_country_comparison"]=(
        "SAME" if a["egress"]["country"]==b["egress"]["country"] else
        "DIFFERENT")
    evidence["egress_network_comparison"]=(
        "SAME" if a["egress"]["network_provider_hint"]==
        b["egress"]["network_provider_hint"] else "DIFFERENT")
    evidence["local_runtime"]=a["machine"]["runtime"]
    evidence["hosted_runtime"]=b["machine"]["runtime"]
    evidence["status"]="CATEGORICAL_COMPARISON_ONLY"
    evidence["causal_hypothesis_proven"]=False
    evidence["region_selection_tested"]=False
    return evidence


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--live",action="store_true",
                   help="One robots-first public search baseline (no click)")
    p.add_argument("--headed",action="store_true")
    p.add_argument("--egress-context",action="store_true",
                   help="Explicit 1 external IP geo request; provider observes exit IP")
    p.add_argument("--owner-approval",default="")
    p.add_argument("--output",type=Path,
                   help="Write sanitized categories only (no IP/URL/cookies)")
    p.add_argument("--compare-local",type=Path)
    p.add_argument("--compare-hosted",type=Path)
    args=p.parse_args(argv)
    if args.compare_local is not None or args.compare_hosted is not None:
        if (args.compare_local is None or args.compare_hosted is None
                or args.live or args.egress_context):
            print("INVALID_COMPARISON_ARGUMENTS")
            return 2
        try:
            doc=comparison(args.compare_local,args.compare_hosted)
        except Exception:
            print("INVALID_BASELINE_COMPARISON")
            return 2
        print(json.dumps(doc,ensure_ascii=False,indent=2,sort_keys=True))
        return 0
    if args.egress_context and not args.live:
        print("EGRESS_CONTEXT_REQUIRES_LIVE_OPT_IN")
        return 2
    if args.live and args.owner_approval != _APPROVAL:
        print("MISSING_EXACT_OWNER_APPROVAL")
        return 2
    try:
        doc=asyncio.run(observe(live=args.live,headed=args.headed,
                                egress_context=args.egress_context))
    except Exception:
        print("REGION_BASELINE_FAILED")
        return 2
    text=json.dumps(doc,ensure_ascii=False,indent=2,sort_keys=True)
    print(text)
    if args.output is not None:
        if args.output.exists():
            print("REFUSING_TO_OVERWRITE_EXISTING_BASELINE")
            return 2
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(text+"\n",encoding="utf-8")
    return 0 if doc["status"] in ("BASELINE_OBSERVED","OFFLINE_FIXTURE") else 2


if __name__=="__main__":
    raise SystemExit(main())
