#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Daangn v4.3.1: bounded cold-document vs repeat vs cross-region diagnostic.

Each plan uses its own fresh *unauthenticated* Chromium context and one page:
  1. cold first document for region A
  2. repeat exactly the same URL for region A
  3. first document for region B in the already used context
  4. repeat exactly the same URL for region B

No login, proxy, captcha solving, access-control bypass, forced cache busting,
or unbounded retries. HTTP cache diagnostics are observational, not causal proof.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

import daangn_v4_1_core as core
import daangn_browser_v4_3 as legacy

PLANS = (
    ("cold_sadang", ("sadang", "sadang", "cheonan", "cheonan")),
    ("cold_cheonan", ("cheonan", "cheonan", "asan", "asan")),
    ("cold_asan", ("asan", "asan", "sadang", "sadang")),
)
LABELS = ("context_first", "same_url_repeat", "region_switch_first", "switched_url_repeat")
MAX_CAPTURE_BYTES = 2_000_000
CACHE_KEYS = (
    "cache-control", "age", "etag", "last-modified", "expires", "date", "vary",
    "x-cache", "x-cache-hits", "x-vercel-cache", "cf-cache-status", "cache-status",
    "x-served-by", "x-nextjs-cache",
)

JS_EXTRA = r"""() => {
  const ld = window.__remixContext?.state?.loaderData || {};
  const route = ld['routes/kr.search.buy-sell._index'] ||
    ld[Object.keys(ld).find(k => /search.*buy-sell/.test(k))] || {};
  const rows = Array.isArray(route.buySellArticles) ? route.buySellArticles : [];
  const areaCounts = {};
  const ordered = [];
  for (const r of rows) {
    if (!r || typeof r !== 'object') continue;
    if (typeof r.href === 'string') ordered.push(r.href);
    const region = r.region;
    const name = region && typeof region === 'object' ? region.name : region;
    if (typeof name === 'string' && name) areaCounts[name] = (areaCounts[name] || 0) + 1;
  }
  return {
    search_region_id: route.searchRegion?.id == null ? null : String(route.searchRegion.id),
    filter_region_id: route.currentFilters?.regionId == null ? null : String(route.currentFilters.regionId),
    keyword: String(route.keyword || route.currentFilters?.search || ''),
    row_count: rows.length,
    order: ordered,
    area_top12: Object.fromEntries(Object.entries(areaCounts).sort((a,b) => b[1]-a[1]).slice(0,12))
  };
}"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digest_lines(values: List[str], ordered: bool = False) -> str:
    arr = list(values) if ordered else sorted(set(values))
    return hashlib.sha256("\n".join(arr).encode("utf-8")).hexdigest()


def metric(a: List[str], b: List[str]) -> dict:
    return legacy.metric(a, b)


def canonical_cache_info(headers: Dict[str, str]) -> dict:
    """Allowlist safe cache diagnostics only; never persist headers wholesale."""
    lowered = {str(k).lower(): str(v) for k, v in headers.items()}
    return {k: lowered[k][:240] for k in CACHE_KEYS if k in lowered}


def cache_hint(headers: dict, from_service_worker: Optional[bool]) -> str:
    """Indication only; not proof that a CDN/browser cache caused a listing mismatch."""
    if from_service_worker is True:
        return "SERVICE_WORKER_REPORTED"
    values = " ".join(str(headers.get(k, "")) for k in
                      ("x-cache", "x-vercel-cache", "cf-cache-status", "cache-status", "x-nextjs-cache")).upper()
    if any(token in values for token in ("HIT", "STALE", "REVALIDATED")):
        return "CACHE_HIT_HEADER_OBSERVED"
    age = str(headers.get("age", ""))
    if age.isdigit() and int(age) > 0:
        return "NONZERO_AGE_HEADER_OBSERVED"
    if any(token in values for token in ("MISS", "BYPASS", "DYNAMIC")):
        return "MISS_OR_BYPASS_HEADER_OBSERVED"
    return "NO_DIRECT_CACHE_STATE_EVIDENCE"


def phase_ok(s: dict) -> bool:
    return bool(s.get("verified") and not s.get("blocked") and s.get("http_status") == 200 and
                s.get("loader_urls") and s.get("dom_visible_urls") and
                s.get("region_id") == s.get("expected_region_id") and
                s.get("loader_region_id") == s.get("expected_region_id") and
                s.get("loader_filter_region_id") == s.get("expected_region_id") and
                s.get("document", {}).get("response_status") == 200 and
                s.get("document", {}).get("body_sha256"))


def summarize_plan(plan: dict) -> dict:
    stages = plan.get("stages", [])
    if len(stages) != 4 or not all(phase_ok(s) for s in stages):
        return {"verdict": "INDETERMINATE_PHASE_NOT_VERIFIED", "valid_stages": sum(map(phase_ok, stages))}
    a1, a2, b1, b2 = stages
    return {
        "verdict": "FOUR_PHASES_MEASURED",
        "cold_vs_repeat_a": metric(a1["loader_urls"], a2["loader_urls"]),
        "switch_vs_repeat_b": metric(b1["loader_urls"], b2["loader_urls"]),
        "warm_a_vs_warm_b": metric(a2["loader_urls"], b2["loader_urls"]),
        "first_a_vs_first_b": metric(a1["loader_urls"], b1["loader_urls"]),
        "cold_vs_repeat_dom": metric(a1["dom_visible_urls"], a2["dom_visible_urls"]),
        "a_first_row_count": a1["loader_article_count"],
        "b_first_row_count": b1["loader_article_count"],
        "a_repeat_row_count": a2["loader_article_count"],
        "b_repeat_row_count": b2["loader_article_count"],
        "cold_early_dom_count": a1.get("dom_early_count"),
        "cold_final_dom_count": a1.get("dom_visible_count"),
        "all_body_digests_equal": len({x["document"]["body_sha256"] for x in stages}) == 1,
        "all_loader_sets_equal": len({x["loader_set_sha256"] for x in stages}) == 1,
    }


def classify_initial_behavior(plans: list) -> dict:
    """Describe measured artifacts; never infer cache causality from set equality."""
    eligible = [p for p in plans if p.get("status") == "CAPTURED_FOUR_PHASES" and
                len(p.get("stages", [])) == 4 and all(phase_ok(s) for s in p["stages"])]
    cold = [p["stages"][0] for p in eligible]
    cold_groups: Dict[str, list] = {}
    for s in cold:
        cold_groups.setdefault(s["loader_set_sha256"], []).append(s)
    collisions = []
    for sha, rows in cold_groups.items():
        region_ids = sorted(set(x["expected_region_id"] for x in rows))
        if len(region_ids) >= 2:
            collisions.append({"set_sha256": sha, "region_ids": region_ids,
                               "regions": sorted(set(x["target"] for x in rows)),
                               "article_counts": sorted(set(x["loader_article_count"] for x in rows)),
                               "document_hashes_distinct": len(set(x["document"]["body_sha256"] for x in rows)),
                               "dom_hashes_distinct": len(set(x["dom_set_sha256"] for x in rows))})
    warm_rows = [s for p in eligible for s in (p["stages"][1], p["stages"][3])]
    warm_groups: Dict[str, dict] = {}
    for s in warm_rows:
        warm_groups.setdefault(s["target"], {})[s["loader_set_sha256"]] = s
    warm_same_area = {}
    for name, by_sha in warm_groups.items():
        matching = [s for s in warm_rows if s["target"] == name]
        warm_same_area[name] = {
            "samples": len(matching), "unique_set_hashes": len(by_sha),
            "pairwise_jaccard": metric(matching[0]["loader_urls"], matching[1]["loader_urls"])["jaccard"]
            if len(matching) == 2 else None,
        }
    warm_differences = []
    for i, a in enumerate(warm_rows):
        for b in warm_rows[i + 1:]:
            if a["expected_region_id"] != b["expected_region_id"]:
                j = metric(a["loader_urls"], b["loader_urls"])["jaccard"]
                warm_differences.append({"left_region": a["target"], "right_region": b["target"],
                                         "jaccard": j})
    cold_changes = [metric(p["stages"][0]["loader_urls"], p["stages"][1]["loader_urls"])["jaccard"]
                    for p in eligible]
    warm_distinct_across_regions = any(row["jaccard"] is not None and row["jaccard"] < .98
                                       for row in warm_differences)
    if len(eligible) < 3:
        verdict = "INDETERMINATE_NEEDS_THREE_COLD_CONTEXTS"
    elif collisions and warm_distinct_across_regions and any(j is not None and j < .98 for j in cold_changes):
        verdict = "CROSS_REGION_IDENTICAL_FIRST_DOCUMENT_SET_WITH_WARM_DIVERGENCE"
    elif collisions:
        verdict = "CROSS_REGION_IDENTICAL_FIRST_DOCUMENT_SET_OBSERVED"
    elif any(j is not None and j < .98 for j in cold_changes):
        verdict = "COLD_REPEAT_VARIATION_WITHOUT_CROSS_REGION_COLLISION"
    else:
        verdict = "NO_LARGE_COLD_FIRST_SET_ANOMALY_OBSERVED"
    return {
        "verdict": verdict,
        "complete_plans": len(eligible),
        "expected_plans": len(PLANS),
        "cold_cross_region_collisions": collisions,
        "cold_to_repeat_jaccards": cold_changes,
        "warm_same_region_cross_context": warm_same_area,
        "warm_differences_across_regions": warm_differences,
        "artifact_observed": bool(collisions),
        "specific_cache_layer_proven": False,
        "backend_causal_mechanism_proven": False,
        "geographic_coverage_proven": False,
        "note": "Metadata and DOM overlap alone do not prove correct listing region scope."
    }


def _safe_info_error(exc: Exception) -> str:
    return type(exc).__name__  # avoid logging potentially credential-bearing URLs


async def response_brief(response, kind: str) -> dict:
    """Safe, bounded response trace of only public search HTML or route JSON."""
    headers = canonical_cache_info(response.headers)
    try:
        from_sw = bool(response.from_service_worker)
    except Exception:
        from_sw = None
    item = {
        "type": kind, "status": response.status,
        "resource_type": response.request.resource_type,
        "url": core.sanitized_url(response.url),
        "cache_headers": headers, "from_service_worker": from_sw,
        "cache_hint": cache_hint(headers, from_sw),
        "body_sha256": None, "body_bytes": None,
        "route_data": None, "error": None,
    }
    if response.status in core.BLOCK_STATUS:
        item["error"] = "ACCESS_RESTRICTED_HTTP"
        return item
    try:
        content_length = response.headers.get("content-length", "")
        if content_length.isdigit() and int(content_length) > MAX_CAPTURE_BYTES:
            item["error"] = "BODY_EXCEEDS_CAP_FROM_CONTENT_LENGTH"
            return item
        body = await asyncio.wait_for(response.body(), timeout=12)
        item["body_bytes"] = len(body)
        if len(body) > MAX_CAPTURE_BYTES:
            item["error"] = "BODY_EXCEEDS_CAP"
            return item
        item["body_sha256"] = hashlib.sha256(body).hexdigest()
        if kind == "route_json":
            item["route_data"] = core.parse_search_route_json(body)
    except Exception as exc:
        item["error"] = _safe_info_error(exc)
    return item


async def sample_document(page, region: dict, args, active: dict,
                          pending: Set[asyncio.Task], observation: dict) -> dict:
    """Use v4.3's tested full-document sampling, plus document response traces."""
    document_tasks: Set[asyncio.Task] = set()
    documents: list = []
    route_responses: list = []
    blockers: list = []

    def event_handler(response):
        try:
            p = urlparse(response.url)
            if p.hostname != "www.daangn.com" or not p.path.startswith(core.SEARCH_PATH):
                return
            kind = ("route_json" if response.request.resource_type in ("fetch", "xhr") and
                    core._is_search_route_response(response.url) else
                    "document" if response.request.resource_type == "document" else None)
            if kind is None:
                return
            if response.status in core.BLOCK_STATUS:
                blockers.append("HTTP_" + str(response.status))
            async def work():
                info = await response_brief(response, kind)
                (documents if kind == "document" else route_responses).append(info)
            task = asyncio.create_task(work())
            document_tasks.add(task)
            task.add_done_callback(document_tasks.discard)
        except Exception as exc:
            blockers.append("RESPONSE_HANDLER_ERROR_" + _safe_info_error(exc))

    page.on("response", event_handler)
    try:
        stage = await legacy.sample_document(page, region, args, active, pending)
        # A short stable window is already used by the legacy sampler.
        if document_tasks:
            await asyncio.wait_for(asyncio.gather(*list(document_tasks), return_exceptions=True), timeout=15)
        try:
            extra = await page.evaluate(JS_EXTRA) if not stage.get("blocked") else {}
        except Exception:
            extra = {}
            stage.setdefault("errors", []).append("EXTRA_LOADER_METADATA_UNAVAILABLE")
        document = next((d for d in reversed(documents) if d.get("type") == "document"), {})
        stage["document"] = {
            "response_status": document.get("status"),
            "body_sha256": document.get("body_sha256"),
            "body_bytes": document.get("body_bytes"),
            "cache_headers": document.get("cache_headers", {}),
            "from_service_worker": document.get("from_service_worker"),
            "cache_hint": document.get("cache_hint"),
            "error": document.get("error"),
        }
        stage["route_fetches"] = route_responses[:6]
        stage["route_fetch_count"] = len(route_responses)
        stage["observed_access_restriction"] = blockers[:2]
        stage["loader_article_order_sha256"] = digest_lines(extra.get("order", []), ordered=True)
        stage["loader_area_top12"] = extra.get("area_top12") or {}
        stage["loader_metadata_match"] = (extra.get("search_region_id") == region["id"] and
                                           extra.get("filter_region_id") == region["id"])
        stage["initial_search_phase"] = observation["phase"]
        stage["context_plan"] = observation["plan"]
        stage["dom_early_count"] = observation.get("dom_early_count")  # no early sample in v4.3
        stage["verified"] = bool(stage["verified"] and document.get("status") == 200 and
                                  document.get("body_sha256") and stage["loader_metadata_match"] and
                                  not blockers and not document.get("error") and
                                  not any(r.get("error") == "ACCESS_RESTRICTED_HTTP" for r in route_responses))
        if blockers:
            stage["blocked"] = True
            stage["block_reason"] = blockers[0]
        return stage
    finally:
        page.remove_listener("response", event_handler)


async def run_plan(browser, args, plan_key: str, targets: tuple) -> dict:
    context = await browser.new_context(locale="ko-KR", viewport={"width": 1280, "height": 850})
    page = await context.new_page()
    context.set_default_timeout(args.timeout * 1000)
    active: Dict[str, Any] = {"bucket": None, "stop": None}
    pending: Set[asyncio.Task] = set()

    def base_on_response(response):
        if not core._is_relevant_first_party(response) or active.get("bucket") is None:
            return
        task = asyncio.create_task(core.record_response(response, active["bucket"], active["stop"]))
        pending.add(task)
        task.add_done_callback(pending.discard)

    page.on("response", base_on_response)
    plan = {"key": plan_key, "targets": list(targets),
            "started_utc": now(), "stages": [], "status": "NOT_STARTED"}
    try:
        for step, region_key in enumerate(targets):
            region = core.BY_KEY[region_key]
            stage = await sample_document(page, region, args, active, pending,
                                          {"phase": LABELS[step], "plan": plan_key})
            stage["step"] = step + 1
            plan["stages"].append(stage)
            print("{name} [{step}/4] {area}: loader={count}, DOM={dom}, cache={cache}, verified={ok}".format(
                name=plan_key, step=step+1, area=region["label"],
                count=len(stage.get("loader_urls") or []), dom=len(stage.get("dom_visible_urls") or []),
                cache=stage.get("document", {}).get("cache_hint"), ok=phase_ok(stage)))
            if stage.get("blocked"):
                plan["status"] = "STOP_ACCESS_RESTRICTED"
                break
            if not phase_ok(stage):
                plan["status"] = "STOP_SAMPLE_UNVERIFIED"
                break
            if step < 3:
                await page.wait_for_timeout(args.pause_ms)
        if plan["status"] == "NOT_STARTED":
            plan["status"] = "CAPTURED_FOUR_PHASES"
    except Exception as exc:
        plan["status"] = "RUNTIME_ERROR"
        plan["error"] = _safe_info_error(exc)
    finally:
        active["bucket"] = None
        await core.drain(pending)
        await context.close()
    plan["analysis"] = summarize_plan(plan)
    return plan


def report(result: dict) -> str:
    a = result.get("analysis") or {}
    lines = [
        "# 당근 Playwright v4.3.1 — 첫 응답 공통 249개 진단", "",
        "- 검사 시각(UTC): " + result["timestamp_utc"],
        "- 검색어: " + result["keyword"],
        "- 실행 상태: **" + result["status"] + "**",
        "- 최종 유형 판정: **" + a.get("verdict", "NOT_ANALYZED") + "**", "",
        "## 실험 설계", "",
        "- 각각 독립된 새 비로그인 Chromium 컨텍스트에서 4회 전체 문서 탐색(총 최대 12회)합니다.",
        "- 같은 URL 즉시 재방문, 지역 변경 후 첫 요청, 변경한 지역 재방문을 구분합니다.",
        "- HTML 내장 loader 상품 URL·현재 DOM 상품 URL·문서 바이트 해시·응답 캐시 헤더를 비교합니다.",
        "- HTTP 헤더는 캐시 관련 안전한 항목만 허용 목록으로 기록하며, 쿠키·인증정보는 저장하지 않습니다.", "",
        "## 4단계 비교", "",
        "| 컨텍스트 | 1(첫 지역) | 2(동일 URL 반복) | 3(다른 지역) | 4(다른 지역 반복) | Cold/Repeat J | Switch/Repeat J |",
        "|---|---|---|---|---|---:|---:|",
    ]
    for plan in result.get("plans", []):
        cells = []
        for s in plan.get("stages", []):
            if s.get("loader_urls"):
                cells.append("{region} {count}개".format(region=s["target"], count=len(s["loader_urls"])))
            else:
                cells.append("미측정")
        cells += ["-"] * (4 - len(cells))
        an = plan.get("analysis") or {}
        lines.append("| {name} | {s1} | {s2} | {s3} | {s4} | {j1} | {j2} |".format(
            name=plan["key"], s1=cells[0], s2=cells[1], s3=cells[2], s4=cells[3],
            j1=pretty((an.get("cold_vs_repeat_a") or {}).get("jaccard")),
            j2=pretty((an.get("switch_vs_repeat_b") or {}).get("jaccard"))))
    lines.extend(["", "## 최초 응답 집합 충돌", ""])
    collisions = a.get("cold_cross_region_collisions") or []
    if not collisions:
        lines.append("- 서로 다른 지역의 첫 응답 간 완전 동일 상품 집합이 관측되지 않았습니다(또는 관측이 부족).")
    for c in collisions:
        lines.append("- 지역 {}: 동일 상품 집합 {}…; 상품 수 {}, 문서 바이트 해시 종류 {}개, DOM 해시 종류 {}개".format(
            ", ".join(c["regions"]), c["set_sha256"][:16], c["article_counts"],
            c["document_hashes_distinct"], c["dom_hashes_distinct"]))
    lines.extend(["", "## 동일 지역·다른 컨텍스트의 후속 응답", "",
                  "| 지역 | 후속 표본 | 고유 집합 해시 수 | 두 표본 Jaccard |", "|---|---:|---:|---:|"])
    for name, stat in sorted((a.get("warm_same_region_cross_context") or {}).items()):
        lines.append("| {} | {} | {} | {} |".format(name, stat["samples"],
                     stat["unique_set_hashes"], pretty(stat["pairwise_jaccard"])))
    lines.extend(["", "## HTTP 캐시 관련 메타데이터", "",
                  "| 컨텍스트 | 단계 | 지역 | HTML SHA(앞 12) | 상품 SHA(앞 12) | Age | Cache-Control | 캐시 힌트 | route fetch |",
                  "|---|---:|---|---|---|---|---|---|---:|"])
    for plan in result.get("plans", []):
        for s in plan.get("stages", []):
            doc = s.get("document") or {}
            hdr = doc.get("cache_headers") or {}
            lines.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
                plan["key"], s["step"], s["target"], (doc.get("body_sha256") or "-")[:12],
                (s.get("loader_set_sha256") or "-")[:12], str(hdr.get("age", "-"))[:20],
                str(hdr.get("cache-control", "-"))[:50].replace("|", "/"),
                doc.get("cache_hint") or "-", s.get("route_fetch_count")))
    lines.extend(["", "## 해석과 제한", "",
                  "- 동일한 상품 집합과 서로 다른 지역 메타데이터가 함께 존재하면 최초 문서 목록의 지역 특이성이 확인되지 않은 것입니다.",
                  "- 초기 공통 목록이 후속 요청에서 사라지더라도 그 원인이 CDN, 브라우저 캐시, 서버 캐시, 검색 백엔드 초기화 중 무엇인지 이 데이터만으로 확정할 수 없습니다.",
                  "- 캐시 헤더의 HIT 또는 Age는 단서일 뿐 상품 목록 차이에 대한 인과 관계를 증명하지 않습니다.",
                  "- DOM은 보이는 상품의 일부이고, 상품 집합의 지역 차이는 전체 매물 수집률 또는 거래 가능 범위의 입증이 아닙니다.",
                  "- 페이지 탐색은 고정된 12회 이하, 무한 재시도·캐시 우회·로그인 재사용 없이 수행합니다.",
                  "- robots.txt 확인은 이용약관상 자동 수집 허가와 다릅니다.", ""])
    return "\n".join(lines)


def pretty(v: Optional[float]) -> str:
    return "-" if v is None else "{:.4f}".format(v)


def write_artifacts(result: dict, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    p1 = directory / "daangn_browser_v4_3_1_results.json"
    p2 = directory / "daangn_browser_v4_3_1_report.md"
    p1.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    p2.write_text(report(result), encoding="utf-8")
    print("Saved:", p1)
    print("Saved:", p2)


async def run(args) -> int:
    result = {
        "version": "4.3.1", "timestamp_utc": now(), "keyword": args.keyword,
        "headed": args.headed, "new_unauthenticated_context_per_plan": True,
        "credentials_or_cookies_reused": False,
        "collection_mode": "bounded_full_document_four_phase_three_contexts",
        "plans": [], "status": "NOT_STARTED",
    }
    result["robots"] = core.public_robots_check(args.keyword)
    if not result["robots"].get("allowed"):
        result["status"] = "STOP_ROBOTS_UNVERIFIED_OR_DISALLOWED"
        write_artifacts(result, args.output_dir)
        return 2
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        result["status"] = "PLAYWRIGHT_NOT_INSTALLED_IN_VENV"
        write_artifacts(result, args.output_dir)
        return 2
    selected = [p for p in PLANS if args.plan in ("all", p[0])]
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=not args.headed)
            try:
                for i, (key, targets) in enumerate(selected):
                    plan = await run_plan(browser, args, key, targets)
                    result["plans"].append(plan)
                    if plan.get("status") != "CAPTURED_FOUR_PHASES":
                        result["status"] = plan.get("status", "STOP_INCOMPLETE")
                        break
                    if i < len(selected) - 1:
                        await asyncio.sleep(args.pause_ms / 1000)
            finally:
                await browser.close()
    except Exception as exc:
        result["status"] = "BROWSER_RUNTIME_ERROR"
        result["error"] = _safe_info_error(exc)
    result["analysis"] = classify_initial_behavior(result["plans"])
    if result["status"] == "NOT_STARTED":
        result["status"] = "CAPTURED_INITIAL_RESPONSE_DIAGNOSTIC" if len(result["plans"]) == len(selected) else "INCOMPLETE"
    write_artifacts(result, args.output_dir)
    return 0 if result["status"] == "CAPTURED_INITIAL_RESPONSE_DIAGNOSTIC" else 2


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Daangn v4.3.1: diagnose first 249-item common response vs repeated requests")
    p.add_argument("--keyword", default="HDD")
    p.add_argument("--plan", choices=("all", *(x[0] for x in PLANS)), default="all")
    p.add_argument("--headed", action="store_true")
    p.add_argument("--timeout", type=int, default=22)
    p.add_argument("--settle-ms", type=int, default=1300)
    p.add_argument("--pause-ms", type=int, default=1500)
    p.add_argument("--min-dom-overlap", type=float, default=0.80)
    p.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
    return p


def main() -> int:
    p = make_parser()
    args = p.parse_args()
    if not (1 <= len(args.keyword.strip()) <= 60):
        p.error("--keyword must be 1..60 characters")
    if not 0 <= args.min_dom_overlap <= 1:
        p.error("--min-dom-overlap must be within [0,1]")
    args.timeout = max(10, min(args.timeout, 45))
    args.settle_ms = max(500, min(args.settle_ms, 4000))
    args.pause_ms = max(800, min(args.pause_ms, 15000))
    args.scroll = False
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
