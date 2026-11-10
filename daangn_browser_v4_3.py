#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Daangn v4.3: paired A-A-A natural-variation and A-B-A region-contrast diagnostic.

All measured samples use the *same* full-document Playwright navigation and
boot loader extraction method, including same-region refreshes. This avoids
confounding v4.2 SPA route JSON with HTML bootstrap on A-A-A steps.
Only public, no-login pages; no access-control circumvention or repeated retries.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import daangn_v4_1_core as core

REGIONS = ("sadang", "cheonan", "asan")
PAIR_DEFS = (
    {"key": "sadang_cheonan", "a": "sadang", "b": "cheonan"},
    {"key": "cheonan_asan", "a": "cheonan", "b": "asan"},
)
# The order places each matched control near one of the cross-over blocks.
RUN_PLAN = (
    ("control_sadang", "aaa", ("sadang", "sadang", "sadang")),
    ("cross_sadang_cheonan", "aba", ("sadang", "cheonan", "sadang")),
    ("control_cheonan", "aaa", ("cheonan", "cheonan", "cheonan")),
    ("cross_cheonan_asan", "aba", ("cheonan", "asan", "cheonan")),
    ("control_asan", "aaa", ("asan", "asan", "asan")),
)

# Extract only non-secret, aggregate metadata from the initial public loader.
JS_LOADER_META = r"""() => {
  const ld = window.__remixContext?.state?.loaderData || {};
  const route = ld['routes/kr.search.buy-sell._index'] ||
       ld[Object.keys(ld).find(k => /search.*buy-sell/.test(k))] || {};
  const rows = Array.isArray(route.buySellArticles) ? route.buySellArticles : [];
  const names = {};
  for (const row of rows) {
    let area = row && row.region;
    area = area && typeof area === 'object' ? area.name : area;
    if (typeof area === 'string' && area.length) names[area] = (names[area] || 0) + 1;
  }
  return {
    search_region_id: route.searchRegion?.id == null ? null : String(route.searchRegion.id),
    filter_region_id: route.currentFilters?.regionId == null ? null : String(route.currentFilters.regionId),
    search_region_name: String(route.searchRegion?.name || ''),
    keyword: String(route.keyword || route.currentFilters?.search || ''),
    article_count: rows.length,
    item_region_known_count: Object.values(names).reduce((a,b) => a+b, 0),
    item_region_histogram: Object.fromEntries(Object.entries(names).sort((a,b)=>b[1]-a[1]).slice(0,12))
  };
}"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def metric(left: List[str], right: List[str]) -> dict:
    a, b = set(left or []), set(right or [])
    both = len(a & b)
    union = len(a | b)
    return {
        "left_count": len(a), "right_count": len(b),
        "overlap": both, "union": union,
        "jaccard": round(both / union, 6) if union else None,
        "left_revisit_fraction": round(both / len(a), 6) if a else None,
        "left_only_count": len(a - b), "right_only_count": len(b - a),
        "left_only_samples": sorted(a - b)[:4], "right_only_samples": sorted(b - a)[:4],
    }


def stamp_elapsed(left: dict, right: dict) -> Optional[float]:
    try:
        return round((datetime.fromisoformat(right["timestamp_utc"]) -
                      datetime.fromisoformat(left["timestamp_utc"])).total_seconds(), 3)
    except (KeyError, TypeError, ValueError):
        return None


def data_urls(stage: dict, kind: str) -> list:
    return (stage.get("loader_urls", []) if kind == "loader"
            else stage.get("dom_visible_urls", []))


def stage_ok(stage: dict) -> bool:
    return bool(stage.get("verified") and stage.get("http_status") == 200 and
                stage.get("loader_urls") and stage.get("dom_visible_urls") and
                stage.get("region_id") == stage.get("expected_region_id") and
                stage.get("loader_region_id") == stage.get("expected_region_id") and
                stage.get("loader_filter_region_id") == stage.get("expected_region_id") and
                not stage.get("blocked") and not stage.get("errors"))


def natural_variation(stages: list, kind: str = "loader") -> dict:
    """Three same-region snapshots. No statistic if any evidence is invalid."""
    if len(stages) != 3 or not all(stage_ok(x) for x in stages):
        return {"verdict": "INDETERMINATE_UNVERIFIED_AAA", "verified_stages": sum(stage_ok(x) for x in stages)}
    if kind == "dom" and any(s.get("dom_stable") is False for s in stages):
        return {"verdict": "INDETERMINATE_UNSTABLE_DOM"}
    x = [data_urls(s, kind) for s in stages]
    pairs = {"a1_a2": metric(x[0], x[1]),
             "a2_a3": metric(x[1], x[2]),
             "a1_a3": metric(x[0], x[2])}
    js = [p["jaccard"] for p in pairs.values()]
    if any(j is None for j in js):
        return {"verdict": "INDETERMINATE_EMPTY_LISTING"}
    distances = [1 - j for j in js]
    return {
        "verdict": "AAA_MEASURED", "pairwise": pairs,
        "median_jaccard": round(statistics.median(js), 6),
        "max_observed_variation": round(max(distances), 6),
        "median_observed_variation": round(statistics.median(distances), 6),
        "endpoint_revisit_fraction": pairs["a1_a3"]["left_revisit_fraction"],
        "elapsed_seconds": stamp_elapsed(stages[0], stages[2]),
        "observations": 3,
    }


def control_alignment(target: list, controls: list, kind: str) -> Optional[float]:
    """Conservative best-match to a control, with both ends checked separately."""
    if not target or not controls:
        return None
    scores = []
    for s in target:
        options = [metric(data_urls(s, kind), data_urls(c, kind))["jaccard"] for c in controls]
        options = [v for v in options if v is not None]
        if not options:
            return None
        scores.append(max(options))
    return round(min(scores), 6)


def infer_region_effect(aba_stages: list, control_a: list, control_b: list,
                        kind: str = "loader", min_return: float = 0.80,
                        min_excess: float = 0.05, min_alignment: float = 0.80) -> dict:
    """Compare crossover distance to maximum *observed* A/B same-region variation.

    Exploratory threshold, not a statistical test or causal proof.
    """
    if len(aba_stages) != 3 or not all(stage_ok(x) for x in aba_stages):
        return {"verdict": "INDETERMINATE_UNVERIFIED_ABA"}
    if kind == "dom" and any(s.get("dom_stable") is False for s in aba_stages):
        return {"verdict": "INDETERMINATE_UNSTABLE_DOM"}
    n_a = natural_variation(control_a, kind)
    n_b = natural_variation(control_b, kind)
    if n_a.get("verdict") != "AAA_MEASURED" or n_b.get("verdict") != "AAA_MEASURED":
        return {"verdict": "INDETERMINATE_CONTROL_MISSING_OR_INVALID",
                "control_a": n_a.get("verdict"), "control_b": n_b.get("verdict")}
    a1, b, a2 = (data_urls(s, kind) for s in aba_stages)
    ret = metric(a1, a2)
    cross1 = metric(a1, b)
    cross2 = metric(b, a2)
    if any(p["jaccard"] is None for p in (ret, cross1, cross2)):
        return {"verdict": "INDETERMINATE_EMPTY_LISTING"}
    # Worst (most similar) cross-boundary transition is the conservative effect.
    min_cross_distance = 1.0 - max(cross1["jaccard"], cross2["jaccard"])
    noise_bound = max(n_a["max_observed_variation"], n_b["max_observed_variation"])
    excess = min_cross_distance - noise_bound
    align_a = control_alignment([aba_stages[0], aba_stages[2]], control_a, kind)
    align_b = control_alignment([aba_stages[1]], control_b, kind)
    align_ok = (align_a is not None and align_b is not None and
                align_a >= min_alignment and align_b >= min_alignment)
    if ret["jaccard"] < min_return:
        verdict = "INDETERMINATE_ABA_RETURN_UNSTABLE"
    elif not align_ok:
        verdict = "INDETERMINATE_CROSS_TRIAL_DRIFT_OR_CONTEXT"
    elif excess >= min_excess:
        verdict = "REGION_ASSOCIATED_CONTRAST_ABOVE_OBSERVED_NOISE"
    else:
        verdict = "CONTRAST_NOT_ABOVE_OBSERVED_NOISE_THRESHOLD"
    return {
        "verdict": verdict,
        "revisit_a1_a2": ret,
        "cross_a1_b": cross1,
        "cross_b_a2": cross2,
        "min_cross_distance": round(min_cross_distance, 6),
        "max_natural_variation_bound": round(noise_bound, 6),
        "excess_over_observed_noise": round(excess, 6),
        "a_alignment_to_aaa": align_a,
        "b_alignment_to_aaa": align_b,
        "return_threshold": min_return,
        "excess_threshold": min_excess,
        "alignment_threshold": min_alignment,
        "revisit_elapsed_seconds": stamp_elapsed(aba_stages[0], aba_stages[2]),
        "causal_effect_proven": False,
        "statistical_significance_tested": False,
        "complete_area_recall_proven": False,
    }


def analyze_all(trials: list, args) -> dict:
    by_key = {t["key"]: t for t in trials}
    controls = {}
    for area in REGIONS:
        trial = by_key.get("control_" + area)
        if trial:
            controls[area] = {
                "loader": natural_variation(trial["stages"], "loader"),
                "dom": natural_variation(trial["stages"], "dom"),
                "trial_status": trial.get("status"),
            }
    pairs = {}
    for pair in PAIR_DEFS:
        trial = by_key.get("cross_" + pair["key"])
        if trial:
            a = by_key.get("control_" + pair["a"], {}).get("stages", [])
            b = by_key.get("control_" + pair["b"], {}).get("stages", [])
            pairs[pair["key"]] = {
                "loader": infer_region_effect(trial["stages"], a, b, "loader", args.min_return,
                                              args.min_excess, args.min_alignment),
                "dom": infer_region_effect(trial["stages"], a, b, "dom", args.min_return,
                                           args.min_excess, args.min_alignment),
                "trial_status": trial.get("status"),
            }
    return {"controls": controls, "pairs": pairs,
            "primary_metric": "loader_public_boot_json_unique_listing_urls",
            "secondary_metric": "rendered_dom_visible_unique_listing_urls",
            "comparison_method": "same_full_document_navigation_for_aaa_and_aba",
            "interpretation": "bounded exploratory observed noise contrast, not a statistical or geographic-coverage guarantee"}


async def sample_document(page, region: dict, args, active: dict,
                          pending: Set[asyncio.Task]) -> dict:
    """Navigate fresh document; return trace and canonical bootstrap URLs."""
    stop = {"blocked": False, "reason": None}
    stamp = now()
    row = await core.url_test(page, region, args, active, pending, stop)
    if row.get("blocked"):
        # Do not interact further after a block/challenge was detected.
        snap = row.get("after") or {}
        meta = {}
    else:
        try:
            snap = await core.stable_page_snapshot(page, region["term"], args.settle_ms)
            meta = await page.evaluate(JS_LOADER_META)
        except Exception as exc:
            snap = row.get("after") or {}
            meta = {}
            row.setdefault("errors", []).append("extra_snapshot:" + type(exc).__name__)
    urls = sorted(set(snap.get("initial_loader_urls") or []))
    dom = sorted(set(snap.get("dom_visible") or []))
    overlap = len(set(dom) & set(urls))
    rid = snap.get("region_id_from_url")
    btn = snap.get("region_button") or ""
    expected = region["id"]
    button_ok = bool(region["term"] in btn)
    errors = row.get("errors") or []
    matches = {
        "region_url": rid == expected,
        "region_button": button_ok,
        "loader_region": snap.get("initial_loader_region_id") == expected,
        "loader_filter": snap.get("initial_loader_filter_region_id") == expected,
        "route_metadata": meta.get("search_region_id") == expected and meta.get("filter_region_id") == expected,
        "dom_covered_by_loader": bool(dom and overlap / len(dom) >= args.min_dom_overlap),
        "keyword_matches": bool(str(meta.get("keyword") or "").casefold() == args.keyword.casefold()),
    }
    is_blocked = bool(row.get("blocked") or snap.get("challenge") or snap.get("login_wall"))
    verified = bool(row.get("http_status") == 200 and not errors and not is_blocked and
                    all(matches.values()) and urls and dom)
    sample = {
        "timestamp_utc": stamp,
        "target": region["key"], "expected_region_id": expected,
        "http_status": row.get("http_status"), "final_url": snap.get("url"),
        "region_id": rid, "region_button": btn,
        "loader_region_id": snap.get("initial_loader_region_id"),
        "loader_filter_region_id": snap.get("initial_loader_filter_region_id"),
        "loader_article_count": meta.get("article_count", snap.get("initial_loader_count")),
        "loader_urls": urls, "dom_visible_urls": dom,
        "loader_set_sha256": hashlib.sha256("\n".join(urls).encode("utf-8")).hexdigest(),
        "dom_set_sha256": hashlib.sha256("\n".join(dom).encode("utf-8")).hexdigest(),
        "dom_visible_count": len(dom), "dom_loader_overlap_count": overlap,
        "dom_stable": snap.get("dom_stable_across_samples"),
        "region_histogram_top12": meta.get("item_region_histogram", {}),
        "loader_keyword": meta.get("keyword"),
        "loader_search_region_name": meta.get("search_region_name"),
        "matches": matches, "verified": verified,
        "blocked": is_blocked, "block_reason": row.get("block_reason") if is_blocked else None,
        "errors": errors,
        "document_network": [{k: v for k, v in r.items() if k in
                              ("url", "status", "resource_type", "content_type", "is_search_route", "route_error")}
                             for r in row.get("network", []) if r.get("resource_type") == "document"][:2],
    }
    return sample


async def run_trial(browser, args, key: str, trial_kind: str, targets: tuple) -> dict:
    context = await browser.new_context(locale="ko-KR", viewport={"width": 1280, "height": 850})
    page = await context.new_page()
    context.set_default_timeout(args.timeout * 1000)
    active: Dict[str, Any] = {"bucket": None, "stop": None}
    pending: Set[asyncio.Task] = set()

    def on_response(response):
        bucket = active.get("bucket")
        if bucket is None or not core._is_relevant_first_party(response):
            return
        task = asyncio.create_task(core.record_response(response, bucket, active["stop"]))
        pending.add(task)
        task.add_done_callback(pending.discard)

    page.on("response", on_response)
    trial = {"key": key, "kind": trial_kind, "targets": list(targets),
             "status": "NOT_STARTED", "started_utc": now(), "stages": []}
    try:
        for i, target in enumerate(targets, 1):
            sample = await sample_document(page, core.BY_KEY[target], args, active, pending)
            sample["step"] = i
            trial["stages"].append(sample)
            print("{trial} {step}/3 {region}: HTTP={http}, loader={lc}, DOM={dc}, verified={ok}".format(
                trial=key, step=i, region=core.BY_KEY[target]["label"], http=sample.get("http_status"),
                lc=len(sample["loader_urls"]), dc=sample["dom_visible_count"], ok=sample["verified"]))
            if sample["blocked"]:
                trial["status"] = "STOP_ACCESS_RESTRICTED_OR_LOGIN_WALL"
                break
            if not sample["verified"]:
                trial["status"] = "STOP_STAGE_UNVERIFIED"
                break
            if i < 3:
                await page.wait_for_timeout(args.pause_ms)
        if trial["status"] == "NOT_STARTED":
            trial["status"] = "CAPTURED_THREE_DOCUMENT_SNAPSHOTS"
    except Exception as exc:
        trial["status"] = "TRIAL_RUNTIME_ERROR"
        trial["error"] = type(exc).__name__ + ":" + str(exc)[:250]
    finally:
        active["bucket"] = None
        await core.drain(pending)
        await context.close()
    return trial


def describe_float(v: Any) -> str:
    return "-" if v is None else f"{v:.4f}"


def report(data: dict) -> str:
    lines = [
        "# 당근 공개 지역 검색 v4.3: A-A-A 자연 변동 대조 + A-B-A 지역 교차 진단", "",
        "- 실행 시각(UTC): " + data["timestamp_utc"],
        "- 검색어: " + data["keyword"],
        "- 최종 상태: **" + data["status"] + "**", "",
        "## 실험 방법", "",
        "- 동일한 브라우저 full-document 탐색과 boot loader 데이터 추출을 A-A-A 및 A-B-A에 공통으로 사용합니다.",
        "- AAA의 동일 지역 다시 열기도 page.goto()로 새로운 문서 탐색을 시도합니다. 캐시 동작은 통제되지 않았습니다.",
        "- 시퀀스당 독립 비로그인 컨텍스트를 사용하고, 각 3단계 내에서는 같은 컨텍스트를 유지합니다.",
        "- 지역 UI 클릭은 v4.1/v4.2에서 검증됐으나, v4.3 주 지표는 fetch JSON과 최초 HTML을 혼합하지 않도록 문서 탐색끼리 비교합니다.",
        "- 주 지표: 공개 HTML에 내장된 loader 매물 URL 집합; 보조 지표: 화면에 렌더링된 매물 URL 집합.",
        "- 자연 변동 보수적 기준: AAA 3회에서 관측된 세 쌍의 (1-Jaccard) 최댓값, A/B 지역 중 더 큰 값.",
        "- 교차 효과: 최소 교차 거리 - 최대 관측 자연 변동. 임계값은 탐색적 기준일 뿐 유의성 검정이 아닙니다.", "",
        "## A-A-A 자연 변동 대조군", "",
        "| 지역 | 실행 | J(A1,A2) | J(A2,A3) | J(A1,A3) | 최대 관측 자연 변동 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    analysis = data.get("analysis") or {}
    for key in REGIONS:
        s = (analysis.get("controls") or {}).get(key, {}).get("loader") or {}
        pair = s.get("pairwise") or {}
        lines.append("| {name} | {s} | {j12} | {j23} | {j13} | {noise} |".format(
            name=core.BY_KEY[key]["label"], s=s.get("verdict", "not_run"),
            j12=describe_float((pair.get("a1_a2") or {}).get("jaccard")),
            j23=describe_float((pair.get("a2_a3") or {}).get("jaccard")),
            j13=describe_float((pair.get("a1_a3") or {}).get("jaccard")),
            noise=describe_float(s.get("max_observed_variation"))))
    lines.extend(["", "## A-B-A 대비(자연 변동 보정)", "",
                  "| 교차 | 결과 | J(A1,A2) | 최소 교차 거리 | 최대 자연 변동 | 초과분 | AAA A/B 정렬 |",
                  "|---|---|---:|---:|---:|---:|---|"])
    for pair in PAIR_DEFS:
        s = (analysis.get("pairs") or {}).get(pair["key"], {}).get("loader") or {}
        lines.append("| {name} | {v} | {ret} | {cross} | {noise} | {excess} | {align}/{alignb} |".format(
            name=core.BY_KEY[pair["a"]]["label"] + "→" + core.BY_KEY[pair["b"]]["label"] + "→" + core.BY_KEY[pair["a"]]["label"],
            v=s.get("verdict", "not_run"),
            ret=describe_float((s.get("revisit_a1_a2") or {}).get("jaccard")),
            cross=describe_float(s.get("min_cross_distance")),
            noise=describe_float(s.get("max_natural_variation_bound")),
            excess=describe_float(s.get("excess_over_observed_noise")),
            align=describe_float(s.get("a_alignment_to_aaa")),
            alignb=describe_float(s.get("b_alignment_to_aaa"))))
    lines.extend(["", "## 측정 단계 및 품질", "",
                  "| 실험 | 단계 | 지역 | HTTP | URL/버튼/로더/필터 | HTML 상품 | 화면 상품 | 화면∩로더 | 검증 |",
                  "|---|---:|---|---:|---|---:|---:|---:|---|"])
    for trial in data.get("trials", []):
        for s in trial["stages"]:
            checks = s.get("matches", {})
            all_region = all(checks.get(k) for k in ("region_url", "region_button", "loader_region", "loader_filter", "route_metadata", "keyword_matches"))
            lines.append("| {t} | {n} | {r} | {http} | {check} | {loader} | {dom} | {ov}/{total} | {ok} |".format(
                t=trial["key"], n=s["step"], r=core.BY_KEY[s["target"]]["label"],
                http=s.get("http_status"), check="PASS" if all_region else "FAIL",
                loader=len(s.get("loader_urls") or []), dom=len(s.get("dom_visible_urls") or []),
                ov=s.get("dom_loader_overlap_count"), total=s.get("dom_visible_count"),
                ok="PASS" if s.get("verified") else "FAIL"))
        if trial["status"] != "CAPTURED_THREE_DOCUMENT_SNAPSHOTS":
            lines.append("\n- {}: **{}**".format(trial["key"], trial["status"]))
    lines.extend(["", "## 해석상 한계", "",
                  "- AAA 3회는 짧은 시간 동안 관측된 자연 변동의 상한 추정치일 뿐, 전체 시간대의 변동률을 대표하지 않습니다.",
                  "- 지역 변경의 인과 효과나 통계적 유의성을 이 실험만으로 입증하지 않습니다.",
                  "- AAA와 ABA는 서로 다른 새 컨텍스트에서 실행하므로 컨텍스트 간 추천·시간 차이도 검증(정렬) 대상입니다.",
                  "- 새 문서 탐색을 사용해도 브라우저/서버 캐시 영향은 완전히 통제되지 않습니다.",
                  "- 상품별 지역은 검색의 허용 직거래 범위와 동의어가 아니며, 지역 전체 검색 누락률은 검증하지 않습니다.",
                  "- 로그인·쿠키 재사용·프로필 저장·접근 제한 우회 없이 공개 경로만 제한적으로 관측합니다.",
                  "- robots.txt 허용은 별도의 이용약관상 수집 승인과 같지 않습니다.", ""])
    return "\n".join(lines)


def write_artifacts(data: dict, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    js = directory / "daangn_browser_v4_3_results.json"
    md = directory / "daangn_browser_v4_3_report.md"
    js.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md.write_text(report(data), encoding="utf-8")
    print("Saved:", js)
    print("Saved:", md)


def chosen_trials(pair: str) -> list:
    if pair == "both":
        return list(RUN_PLAN)
    target = next(p for p in PAIR_DEFS if p["key"] == pair)
    selected = {"control_" + target["a"], "cross_" + pair, "control_" + target["b"]}
    return [d for d in RUN_PLAN if d[0] in selected]


async def run(args) -> int:
    data = {
        "version": "4.3", "timestamp_utc": now(), "keyword": args.keyword,
        "pair": args.pair, "headed": args.headed,
        "new_unauthenticated_context_per_trial": True,
        "credentials_or_cookies_reused": False,
        "collection_mode": "full_document_playwright_navigation_for_all_steps",
        "min_dom_overlap": args.min_dom_overlap,
        "min_return": args.min_return, "min_excess": args.min_excess,
        "min_alignment": args.min_alignment,
        "trials": [], "status": "NOT_STARTED",
    }
    robots = core.public_robots_check(args.keyword)
    data["robots"] = robots
    if not robots.get("allowed"):
        data["status"] = "STOP_ROBOTS_UNVERIFIED_OR_DISALLOWED"
        write_artifacts(data, args.output_dir)
        return 2
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        data["status"] = "PLAYWRIGHT_NOT_INSTALLED_IN_VENV"
        write_artifacts(data, args.output_dir)
        return 2
    selected = chosen_trials(args.pair)
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=not args.headed)
            try:
                for index, (key, kind, targets) in enumerate(selected):
                    trial = await run_trial(browser, args, key, kind, targets)
                    data["trials"].append(trial)
                    if trial["status"] != "CAPTURED_THREE_DOCUMENT_SNAPSHOTS":
                        data["status"] = trial["status"]
                        break
                    if index < len(selected) - 1:
                        await asyncio.sleep(args.pause_ms / 1000)
            finally:
                await browser.close()
    except Exception as exc:
        data["status"] = "BROWSER_RUNTIME_ERROR"
        data["error"] = type(exc).__name__ + ":" + str(exc)[:250]
    data["analysis"] = analyze_all(data["trials"], args)
    if data["status"] == "NOT_STARTED":
        data["status"] = "CAPTURED_MATCHED_AAA_ABA_TRIALS" if len(data["trials"]) == len(selected) else "INCOMPLETE_TRIALS"
    write_artifacts(data, args.output_dir)
    return 0 if data["status"] == "CAPTURED_MATCHED_AAA_ABA_TRIALS" else 2


def make_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Daangn v4.3 bounded same-region AAA versus cross-region ABA browser diagnostic")
    ap.add_argument("--keyword", default="HDD")
    ap.add_argument("--pair", choices=("both", *(p["key"] for p in PAIR_DEFS)), default="both")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--timeout", type=int, default=22)
    ap.add_argument("--settle-ms", type=int, default=1300)
    ap.add_argument("--pause-ms", type=int, default=1500)
    ap.add_argument("--min-dom-overlap", type=float, default=0.80)
    ap.add_argument("--min-return", type=float, default=0.80)
    ap.add_argument("--min-excess", type=float, default=0.05)
    ap.add_argument("--min-alignment", type=float, default=0.80)
    ap.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
    return ap


def main() -> int:
    parser = make_parser()
    args = parser.parse_args()
    if not (1 <= len(args.keyword.strip()) <= 60):
        parser.error("--keyword must be between 1 and 60 characters")
    if any(not 0 <= getattr(args, k) <= 1 for k in ("min_dom_overlap", "min_return", "min_excess", "min_alignment")):
        parser.error("fractions must be in [0,1]")
    args.timeout = max(10, min(args.timeout, 45))
    args.settle_ms = max(500, min(args.settle_ms, 4000))
    args.pause_ms = max(800, min(args.pause_ms, 15000))
    args.scroll = False  # Keep all measurements on the same fixed first-page rendering.
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
