#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Daangn v4.2: A-B-A repeatability diagnostic on public, unauthenticated pages.

Two UI sequences, each inside a fresh browser context:
 - Sadang -> Cheonan -> Sadang (warm-up seed: Asan)
 - Cheonan -> Asan -> Cheonan (warm-up seed: Sadang)
All three measured visits are UI transitions with fresh route fetch JSON, avoiding
comparison of boot HTML against SPA route JSON. No login or anti-bot bypass.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Set

import daangn_v4_1_core as core

SEQUENCES = [
    {"key": "sadang_cheonan_sadang", "seed": "asan", "keys": ["sadang", "cheonan", "sadang"]},
    {"key": "cheonan_asan_cheonan", "seed": "sadang", "keys": ["cheonan", "asan", "cheonan"]},
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def diagnostic_status(stage: dict) -> bool:
    """Only a complete UI+fetch+DOM verification can enter the A-B-A statistic."""
    check = stage.get("check") or {}
    route = stage.get("fetch_json") or {}
    return bool(check.get("verified") and check.get("ui_click_completed") and
                route.get("route_found") and route.get("article_urls") and
                (stage.get("after") or {}).get("dom_visible"))


def compact_step(entry: dict, source: dict, target: dict, index: int) -> dict:
    """Keep measured evidence without storing a duplicate initial Remix product set."""
    after = entry.get("after") or {}
    route = entry.get("fetch_json") or {}
    check = entry.get("check") or {}
    action = entry.get("action") or {}
    return {
        "step": index, "from": source["key"], "to": target["key"],
        "measured_at_utc": now(),
        "expected_region_id": target["id"],
        "action": {"clicked_region_button": action.get("clicked_region_button"),
                   "selected_suggestion": action.get("selected_suggestion"),
                   "error": action.get("error"),
                   "click_return_url": action.get("end_url"),
                   "settled_url": after.get("url")},
        "after": {
            "url": after.get("url"), "region_button": after.get("region_button"),
            "region_id_from_url": after.get("region_id_from_url"),
            "initial_loader_region_id": after.get("initial_loader_region_id"),
            "stale_boot_loader": check.get("stale_boot_loader_observed"),
            "dom_stable_across_samples": after.get("dom_stable_across_samples"),
            "dom_visible": after.get("dom_visible", []),
            "dom_visible_count": len(after.get("dom_visible", [])),
            "challenge": after.get("challenge"), "login_wall": after.get("login_wall"),
        },
        "fetch": {
            "search_region_id": route.get("search_region_id"),
            "filter_region_id": route.get("filter_region_id"),
            "search_region_name": route.get("search_region_name"),
            "query_keyword": route.get("query_keyword"),
            "article_count": route.get("article_count"),
            "unique_url_count": route.get("unique_url_count"),
            "article_urls": route.get("article_urls", []),
            "item_region_known_count": route.get("item_region_known_count"),
            "item_region_histogram": route.get("item_region_histogram", {}),
            "article_samples": route.get("article_samples", []),
        },
        "check": check,
        "network": [{k: v for k, v in n.items() if k != "route_data"}
                    for n in entry.get("network", [])],
        "errors": entry.get("errors", []),
        "stage_verified": diagnostic_status(entry),
    }


def pair_metrics(left: list, right: list) -> dict:
    a, b = set(left), set(right)
    inter = len(a & b)
    union = len(a | b)
    return {
        "left_count": len(a), "right_count": len(b),
        "overlap": inter, "union": union,
        "jaccard": round(inter / union, 5) if union else None,
        "recall_of_left": round(inter / len(a), 5) if a else None,
        "coverage_of_right": round(inter / len(b), 5) if b else None,
        "left_only_count": len(a - b), "right_only_count": len(b - a),
        "left_only_sample": sorted(a - b)[:5],
        "right_only_sample": sorted(b - a)[:5],
    }


def analyze_triple(stages: list, field: str, min_repeat: float, min_gap: float) -> dict:
    """Compare same-region revisit A1/A2 and both cross-region boundaries."""
    if len(stages) != 3:
        return {"verdict": "INCOMPLETE_SEQUENCE", "reason": "three_stages_required"}
    if not all(s.get("stage_verified") for s in stages):
        return {"verdict": "INDETERMINATE_UI_OR_ROUTE_UNVERIFIED"}
    def urls(x):
        obj = x["fetch"] if field == "fetch" else x["after"]
        return obj.get("article_urls" if field == "fetch" else "dom_visible", [])
    a1, b, a2 = (urls(s) for s in stages)
    if not all((a1, b, a2)):
        return {"verdict": "INDETERMINATE_EMPTY_RESULT"}
    ret = pair_metrics(a1, a2)
    ab = pair_metrics(a1, b)
    ba = pair_metrics(b, a2)
    repeat = ret["jaccard"]
    middle_max = max(ab["jaccard"], ba["jaccard"])
    gap = round(repeat - middle_max, 5)
    if repeat >= min_repeat and gap >= min_gap:
        verdict = "REVISIT_REPEATABLE_WITH_REGION_ASSOCIATED_CONTRAST"
    elif repeat >= min_repeat and len(set(a1) ^ set(b)) == 0 and len(set(b) ^ set(a2)) == 0:
        verdict = "REVISIT_REPEATABLE_NO_OBSERVED_REGION_CONTRAST"
    elif repeat >= min_repeat:
        verdict = "REVISIT_REPEATABLE_CONTRAST_INSUFFICIENT"
    else:
        verdict = "LOW_REVISIT_REPRODUCIBILITY"
    return {
        "verdict": verdict, "revisit_a1_a2": ret,
        "cross_a1_b": ab, "cross_b_a2": ba,
        "contrast_gap": gap,
        "threshold_repeat_jaccard": min_repeat,
        "threshold_contrast_gap": min_gap,
        "interpreted_as_geographic_accuracy": False,
        "coverage_or_recall_verified": False,
    }


def analyze_sequence(stages: list, min_repeat: float, min_gap: float) -> dict:
    """Only full UI verification authorizes a repeatability assessment."""
    if len(stages) != 3 or not all(s.get("stage_verified") for s in stages):
        return {
            "verdict": "INDETERMINATE_SEQUENCE_NOT_FULLY_VERIFIED",
            "verified_stages": sum(bool(s.get("stage_verified")) for s in stages),
            "fetch": analyze_triple(stages, "fetch", min_repeat, min_gap),
            "dom": analyze_triple(stages, "dom", min_repeat, min_gap),
        }
    fetch = analyze_triple(stages, "fetch", min_repeat, min_gap)
    dom = analyze_triple(stages, "dom", min_repeat, min_gap)
    try:
        t0 = datetime.fromisoformat(stages[0]["measured_at_utc"])
        t2 = datetime.fromisoformat(stages[2]["measured_at_utc"])
        elapsed = round((t2 - t0).total_seconds(), 3)
    except (KeyError, TypeError, ValueError):
        elapsed = None
    if fetch["verdict"] == "REVISIT_REPEATABLE_WITH_REGION_ASSOCIATED_CONTRAST":
        status = "REPEATABLE_REGION_ASSOCIATED_SEARCH_DIFFERENCE"
    elif fetch["verdict"] == "LOW_REVISIT_REPRODUCIBILITY":
        status = "REVISIT_UNSTABLE_OR_TIME_SENSITIVE"
    else:
        status = "REGION_EFFECT_NOT_ESTABLISHED_WITH_THRESHOLDS"
    return {
        "verdict": status, "verified_stages": 3,
        "fetch": fetch, "dom": dom,
        "revisit_elapsed_seconds": elapsed,
        "geographic_precision_verified": False,
        "full_listing_coverage_verified": False,
    }


def stage_region_stats(step: dict, region_key: str) -> dict:
    term = core.BY_KEY[region_key]["term"]
    counts = step["fetch"].get("item_region_histogram") or {}
    return {
        "expected_term": term,
        "known_region_names_in_saved_histogram": sum(counts.values()),
        "exact_region_name_count": counts.get(term, 0),
        "top_region_names": list(counts.items())[:8],
        "note": "Exact dong counts are not a valid proxy for catchment radius or local-market completeness.",
    }


async def run_one_sequence(browser, args, definition: dict) -> dict:
    ctx = await browser.new_context(locale="ko-KR", viewport={"width": 1280, "height": 850})
    page = await ctx.new_page()
    ctx.set_default_timeout(args.timeout * 1000)
    active: Dict[str, Any] = {"bucket": None, "stop": {"blocked": False, "reason": None}}
    pending: Set[asyncio.Task] = set()

    def response_handler(response):
        bucket = active.get("bucket")
        if bucket is None or not core._is_relevant_first_party(response):
            return
        t = asyncio.create_task(core.record_response(response, bucket, active["stop"]))
        pending.add(t)
        t.add_done_callback(pending.discard)

    page.on("response", response_handler)
    seq = {
        "key": definition["key"], "seed": definition["seed"],
        "targets": definition["keys"], "status": "NOT_STARTED",
        "started_utc": now(), "stages": [],
        "seed_info": {}, "stop_reason": None,
    }
    try:
        seed_region = core.BY_KEY[definition["seed"]]
        seed_stop = {"blocked": False, "reason": None}
        seed_row = await core.url_test(page, seed_region, args, active, pending, seed_stop)
        seed_after = seed_row.get("after") or {}
        seq["seed_info"] = {
            "label": seed_region["label"], "http_status": seed_row.get("http_status"),
            "region_button": seed_after.get("region_button"),
            "initial_loader_region_id": seed_after.get("initial_loader_region_id"),
            "url_region_id": seed_after.get("region_id_from_url"),
            "dom_count": seed_after.get("visible_dom_count"),
            "errors": seed_row.get("errors", []),
        }
        if seed_stop["blocked"]:
            seq["status"] = "STOP_ACCESS_RESTRICTED"
            seq["stop_reason"] = seed_stop.get("reason")
            return seq
        if seed_row.get("http_status") != 200 or seed_row.get("errors"):
            seq["status"] = "STOP_SEED_NAVIGATION_FAILED"
            return seq
        if seed_after.get("login_wall") or seed_after.get("challenge"):
            seq["status"] = "STOP_LOGIN_OR_CHALLENGE"
            return seq
        if seed_after.get("initial_loader_region_id") != seed_region["id"]:
            seq["status"] = "STOP_SEED_REGION_MISMATCH"
            return seq
        source = seed_region
        for i, key in enumerate(definition["keys"], 1):
            target = core.BY_KEY[key]
            stop = {"blocked": False, "reason": None}
            started_at_utc = now()
            entry = await core.ui_test(page, source, target, args, active, pending, stop)
            step = compact_step(entry, source, target, i)
            step["started_at_utc"] = started_at_utc
            step["region_stats"] = stage_region_stats(step, key)
            seq["stages"].append(step)
            print("{seq} {i}/3 {name}: {v}, DOM={dom}, JSON={cnt}".format(
                seq=definition["key"], i=i, name=target["label"],
                v=step["check"].get("verdict"),
                dom=step["after"].get("dom_visible_count"),
                cnt=step["fetch"].get("article_count")))
            if stop["blocked"] or step["after"].get("challenge"):
                seq["status"] = "STOP_ACCESS_RESTRICTED"
                seq["stop_reason"] = stop.get("reason") or "challenge_text"
                break
            if step["after"].get("login_wall"):
                seq["status"] = "STOP_LOGIN_WALL"
                break
            if not step["stage_verified"]:
                seq["status"] = "STOP_UI_STAGE_UNVERIFIED"
                break
            source = target
            if i < len(definition["keys"]):
                await page.wait_for_timeout(args.pause_ms)
        if seq["status"] == "NOT_STARTED":
            seq["status"] = "CAPTURED_THREE_UI_STAGES"
        seq["analysis"] = analyze_sequence(seq["stages"], args.min_repeat_jaccard,
                                           args.min_contrast_gap)
        return seq
    except Exception as exc:
        seq["status"] = "SEQUENCE_RUNTIME_ERROR"
        seq["stop_reason"] = type(exc).__name__ + ":" + str(exc)[:300]
        seq["analysis"] = analyze_sequence(seq["stages"], args.min_repeat_jaccard,
                                           args.min_contrast_gap)
        return seq
    finally:
        active["bucket"] = None
        await core.drain(pending)
        await ctx.close()


def report(data: dict) -> str:
    lines = [
        "# 당근 공개 검색 v4.2 A-B-A 반복 검증 보고서", "",
        "- 실행 시각(UTC): " + data["timestamp_utc"],
        "- 검색어: " + data["keyword"],
        "- 상태: **" + data["status"] + "**", "",
        "## 실행 조건", "",
        "- 계정·쿠키 재사용 없음, 시퀀스별 새 비로그인 Chromium 컨텍스트",
        "- 각 시퀀스에 별도의 준비 지역을 연 뒤 A→B→A는 모두 UI 선택으로 진행",
        "- 세 단계 모두 URL·버튼·fetch JSON 지역 ID·화면 매물의 일치가 확인된 경우만 분석",
        "- 로더 fetch Jaccard가 주요 지표, 화면 DOM Jaccard는 보조 지표", "",
        "## 시퀀스 결과", "",
        "| 시퀀스 | 준비 지역 | 완료 단계 | 판정 | fetch A1↔A2 J | fetch A1↔B J | fetch B↔A2 J | 대비 차이 | DOM A1↔A2 J |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    for seq in data.get("sequences", []):
        an = seq.get("analysis") or {}
        f = an.get("fetch") or {}
        d = an.get("dom") or {}
        return_j = (f.get("revisit_a1_a2") or {}).get("jaccard")
        cross1 = (f.get("cross_a1_b") or {}).get("jaccard")
        cross2 = (f.get("cross_b_a2") or {}).get("jaccard")
        dom_j = (d.get("revisit_a1_a2") or {}).get("jaccard")
        def fmt(n):
            return "-" if n is None else (f"{n:.4f}" if isinstance(n, float) else str(n))
        lines.append("| {names} | {seed} | {count}/3 | {verdict} | {ret} | {ab} | {ba} | {gap} | {dom} |".format(
            names="→".join(core.BY_KEY[k]["label"] for k in seq["targets"]),
            seed=core.BY_KEY[seq["seed"]]["label"], count=len(seq["stages"]),
            verdict=an.get("verdict") or seq["status"],
            ret=fmt(return_j),ab=fmt(cross1),ba=fmt(cross2),
            gap=fmt(f.get("contrast_gap")),dom=fmt(dom_j)))
    for seq in data.get("sequences", []):
        lines.extend(["", "### " + "→".join(core.BY_KEY[k]["label"] for k in seq["targets"]), "",
                      "- 실행 상태: **" + seq["status"] + "**"])
        if seq.get("stop_reason"):
            lines.append("- 중단 원인: " + seq["stop_reason"])
        lines.append("")
        lines.extend(["| 단계 | 선택 지역 | URL 지역 ID | 화면 지역 버튼 | fetch 지역 ID/필터 | DOM/JSON | 매물 수 | 판정 |",
                      "|---|---|---|---|---|---:|---:|---|"])
        for s in seq["stages"]:
            c = s["check"]
            lines.append("| {step} | {name} | {uid} | {btn} | {fid}/{flt} | {overlap}/{dom} | {cnt} | {verdict} |".format(
                step=s["step"], name=core.BY_KEY[s["to"]]["label"],
                uid=s["after"].get("region_id_from_url"),
                btn=str(s["after"].get("region_button", "")).replace("|", "/")[:60],
                fid=c.get("fetch_search_region_id"), flt=c.get("fetch_filter_region_id"),
                overlap=c.get("dom_fetch_overlap_count"), dom=c.get("dom_visible_count"),
                cnt=s["fetch"].get("article_count"), verdict=c.get("verdict")))
        f = (seq.get("analysis") or {}).get("fetch") or {}
        ret = f.get("revisit_a1_a2") or {}
        if ret:
            lines.extend(["", "- 동일 지역 재방문 URL 공통: {n}개 / A1 {a}개 / A2 {b}개".format(
                n=ret.get("overlap"),a=ret.get("left_count"),b=ret.get("right_count")),
                "- 재방문 A1 기준 재현율: {}".format(ret.get("recall_of_left")),
                "- 재방문 A2 기준 공통 비율: {}".format(ret.get("coverage_of_right")),
                "- 대비 차이(return Jaccard - max(cross Jaccards)): {}".format(f.get("contrast_gap")),
                "- A1→A2 측정 시간 차이(초): {}".format((seq.get("analysis") or {}).get("revisit_elapsed_seconds"))])
        if seq["stages"]:
            lines.extend(["", "- 각 단계의 상품별 동네 이름 최빈값(최대 8개):"])
            for s in seq["stages"]:
                names = s.get("region_stats", {}).get("top_region_names") or []
                top = ", ".join("{n}={c}".format(n=n,c=c) for n, c in names)
                lines.append("  - {} 단계: {}".format(s["step"], top or "데이터 없음"))
    lines.extend([
        "", "## 판정 해석", "",
        "- `REPEATABLE_REGION_ASSOCIATED_SEARCH_DIFFERENCE`는 지역 전환과 연관된 목록 차이 및 재방문 일치의 **정황**입니다.",
        "- 이것만으로 실제 거래 가능 거리, 전체 지역 매물의 재현율(recall), 검색 순위 편향을 확정하지 않습니다.",
        "- 동일 지역 A1→A2 간에도 검색 순위·신규 게시물·배송형 후보 등으로 매물 집합이 변할 수 있습니다.",
        "- 지역별 정확성의 최종 검증에는 독립적인 앱 검색 표본·동네별 실제 게시글 대조가 필요합니다.",
        "- robots.txt 허용은 자동 수집의 법적·약관상 승인과 동일하지 않습니다.",
        "- 로그인·쿠키·프로필·요청 헤더·응답 본문 전체는 저장하지 않습니다.", "",
    ])
    return "\n".join(lines)


def write_files(data: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "daangn_browser_v4_2_results.json"
    report_path = output_dir / "daangn_browser_v4_2_report.md"
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report_path.write_text(report(data), encoding="utf-8")
    print("Saved:", json_path)
    print("Saved:", report_path)


async def run(args) -> int:
    data = {
        "version": "4.2", "timestamp_utc": now(), "keyword": args.keyword,
        "headed": args.headed, "new_unauthenticated_context_per_sequence": True,
        "credentials_or_cookies_reused": False,
        "min_repeat_jaccard": args.min_repeat_jaccard,
        "min_contrast_gap": args.min_contrast_gap,
        "sequences": [], "status": "NOT_STARTED",
    }
    robots = core.public_robots_check(args.keyword)
    data["robots"] = robots
    if not robots.get("allowed"):
        data["status"] = "STOP_ROBOTS_UNVERIFIED_OR_DISALLOWED"
        write_files(data, args.output_dir)
        return 2
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        data["status"] = "PLAYWRIGHT_NOT_INSTALLED_IN_VENV"
        write_files(data, args.output_dir)
        return 2
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=not args.headed)
            try:
                selected = [d for d in SEQUENCES if args.sequence == "both" or args.sequence == d["key"]]
                for spec in selected:
                    result = await run_one_sequence(browser, args, spec)
                    data["sequences"].append(result)
                    analysis = (result.get("analysis") or {}).get("verdict", "not_computed")
                    print("Analysis {name}: {status} ({analysis})".format(name=spec["key"], status=result["status"], analysis=analysis))
                    if result["status"].startswith("STOP_") or result["status"] == "SEQUENCE_RUNTIME_ERROR":
                        data["status"] = result["status"]
                        break
                    await asyncio.sleep(args.pause_ms / 1000)
            finally:
                await browser.close()
    except Exception as exc:
        data["status"] = "BROWSER_RUNTIME_ERROR"
        data["error"] = type(exc).__name__ + ":" + str(exc)[:300]
    if data["status"] == "NOT_STARTED":
        expected_count = len([d for d in SEQUENCES if args.sequence == "both" or args.sequence == d["key"]])
        complete = len(data["sequences"]) == expected_count and all(
            s["status"] == "CAPTURED_THREE_UI_STAGES" and len(s["stages"]) == 3
            for s in data["sequences"]
        )
        data["status"] = "CAPTURED_ABA_SEQUENCES" if complete else "INCOMPLETE_ABA_SEQUENCES"
    write_files(data, args.output_dir)
    return 0 if data["status"] == "CAPTURED_ABA_SEQUENCES" else 2


def main() -> int:
    ap = argparse.ArgumentParser(description="Daangn v4.2 A-B-A UI region-change repeatability diagnostic")
    ap.add_argument("--keyword", default="HDD")
    ap.add_argument("--sequence", choices=("both", *(d["key"] for d in SEQUENCES)), default="both")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--timeout", type=int, default=22)
    ap.add_argument("--settle-ms", type=int, default=1500)
    ap.add_argument("--pause-ms", type=int, default=1200)
    ap.add_argument("--min-repeat-jaccard", type=float, default=0.80)
    ap.add_argument("--min-contrast-gap", type=float, default=0.10)
    ap.add_argument("--no-scroll", action="store_false", dest="scroll")
    ap.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
    args = ap.parse_args()
    if not (1 <= len(args.keyword.strip()) <= 60):
        ap.error("keyword length must be 1 to 60")
    args.timeout = max(10, min(args.timeout, 45))
    args.settle_ms = max(500, min(args.settle_ms, 4000))
    args.pause_ms = max(600, min(args.pause_ms, 15000))
    if not 0 <= args.min_repeat_jaccard <= 1 or not 0 <= args.min_contrast_gap <= 1:
        ap.error("thresholds must be between 0 and 1")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
