#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Daangn Playwright v4.3.2: bounded cold/repeat session-state diagnostic.

Observational only: fresh anonymous contexts, 3 x 4 first-party document
navigations, no state modification, no cache busting, no login or bypass.

Critical privacy guarantee: cookie names, domains, paths and VALUES are read
only into ephemeral Python memory to count transitions. NONE are serialized.
No raw Cookie/Set-Cookie headers, local/sessionStorage keys/values, or session
IDs are written into reports, stdout, logs or artifacts.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

import daangn_browser_v4_3_1 as prior
import daangn_v4_1_core as core

VERSION = "4.3.2"
PLANS = prior.PLANS
PHASES = prior.LABELS
JS_STORAGE_COUNTS = r"""() => {
  let localCount = null;
  let sessionCount = null;
  try { localCount = window.localStorage.length; } catch (e) {}
  try { sessionCount = window.sessionStorage.length; } catch (e) {}
  return {
    local_storage_key_count: localCount,
    session_storage_key_count: sessionCount,
    navigator_cookie_enabled: Boolean(navigator.cookieEnabled)
  };
}"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_first_party_domain(domain: str) -> bool:
    host = str(domain or "").strip(".").lower()
    return host == "daangn.com" or host.endswith(".daangn.com")


def cookie_private_map(cookies: List[dict]) -> Dict[tuple, tuple]:
    """Transient only. MUST NEVER include this map in result/stage objects."""
    mapped = {}
    for item in cookies:
        identity = (str(item.get("name", "")), str(item.get("domain", "")),
                    str(item.get("path", "")), str(item.get("partitionKey", "")))
        attributes = (bool(item.get("httpOnly", False)), bool(item.get("secure", False)),
                      str(item.get("sameSite", "")), item.get("expires"))
        mapped[identity] = (str(item.get("value", "")), attributes)
    return mapped


def cookie_public_summary(cookies: List[dict]) -> dict:
    """Aggregate attributes, NEVER cookie identifiers or values."""
    same_site = Counter(str(x.get("sameSite", "Unspecified")) for x in cookies)
    exp = [x.get("expires") for x in cookies]
    return {
        "available": True,
        "cookie_count": len(cookies),
        "first_party_cookie_count": sum(is_first_party_domain(x.get("domain", "")) for x in cookies),
        "third_party_cookie_count": sum(not is_first_party_domain(x.get("domain", "")) for x in cookies),
        "http_only_count": sum(bool(x.get("httpOnly")) for x in cookies),
        "secure_count": sum(bool(x.get("secure")) for x in cookies),
        "session_expiry_count": sum(e in (-1, 0, None) for e in exp),
        "same_site_counts": {k: same_site[k] for k in ("Strict", "Lax", "None", "Unspecified") if same_site[k]},
    }


def cookie_delta(before: Optional[dict], after: Optional[dict]) -> dict:
    """Compare cookie values in memory, persist ONLY aggregate change counts."""
    if before is None or after is None:
        return {"available": False, "added_count": None, "removed_count": None,
                "value_changed_count": None, "attributes_changed_count": None,
                "unchanged_count": None, "any_cookie_state_change": None}
    ka, kb = set(before), set(after)
    common = ka & kb
    value_changed = sum(before[k][0] != after[k][0] for k in common)
    attribute_changed = sum(before[k][1] != after[k][1] for k in common)
    unchanged = sum(before[k] == after[k] for k in common)
    return {
        "available": True,
        "added_count": len(kb - ka),
        "removed_count": len(ka - kb),
        "value_changed_count": value_changed,
        "attributes_changed_count": attribute_changed,
        "unchanged_count": unchanged,
        "any_cookie_state_change": before != after,
    }


async def state_snapshot(context, page) -> Tuple[Optional[dict], dict]:
    """Read browser state, without persisting cookie contents or storage keys."""
    private = None
    try:
        cookies = await context.cookies()
        private = cookie_private_map(cookies)
        summary = cookie_public_summary(cookies)
    except Exception:
        summary = {"available": False, "cookie_count": None}
    storage = {"local_storage_key_count": None, "session_storage_key_count": None,
               "navigator_cookie_enabled": None}
    try:
        if urlparse(page.url).hostname == "www.daangn.com":
            raw = await page.evaluate(JS_STORAGE_COUNTS)
            if isinstance(raw, dict):
                storage = {k: raw.get(k) for k in storage}
    except Exception:
        pass
    summary.update(storage)
    return private, summary


def storage_count_change(before: dict, after: dict) -> dict:
    output = {}
    for k in ("local_storage_key_count", "session_storage_key_count"):
        a, b = before.get(k), after.get(k)
        output[k + "_delta"] = b - a if isinstance(a, int) and isinstance(b, int) else None
    return output


def count_cookie_header_pairs(header: Optional[str]) -> int:
    """Count Cookie header pairs; do not preserve names or values."""
    if not header:
        return 0
    return sum(1 for part in header.split(";") if "=" in part)


def sanitize_document_cookie_evidence(*, request_cookie_pair_count: Optional[int],
                                      set_cookie_header_count: Optional[int],
                                      http_status: Optional[int], errors: List[str]) -> dict:
    """Only scalar counts/statuses; accepts no raw sensitive headers."""
    return {
        "document_observed": http_status is not None,
        "http_status": http_status,
        "request_cookie_header_present": (request_cookie_pair_count > 0
                                          if request_cookie_pair_count is not None else None),
        "request_cookie_pair_count": request_cookie_pair_count,
        "response_set_cookie_header_count": set_cookie_header_count,
        "error_types": sorted(set(errors))[:3],
    }


async def cookie_document_trace(response) -> dict:
    """Observe only main search document's cookie header PRESENCE and COUNT."""
    req_count = None
    set_count = None
    errors = []
    try:
        # Playwright returns the raw string transiently; NEVER store/print it.
        req_count = count_cookie_header_pairs(await response.request.header_value("cookie"))
    except Exception as exc:
        errors.append("REQUEST_COOKIE_HEADER_" + type(exc).__name__)
    try:
        # Playwright returns the raw Set-Cookie strings transiently; do not store.
        headers = await response.header_values("set-cookie")
        set_count = len(headers) if headers is not None else 0
    except Exception as exc:
        errors.append("SET_COOKIE_HEADER_" + type(exc).__name__)
    return sanitize_document_cookie_evidence(
        request_cookie_pair_count=req_count, set_cookie_header_count=set_count,
        http_status=response.status, errors=errors)


async def sample_with_state(context, page, region, args, active, pending, phase, plan_key) -> dict:
    """Extend proven v4.3.1 sampler with privacy-preserving before/after telemetry."""
    private_before, before = await state_snapshot(context, page)
    doc_tasks: Set[asyncio.Task] = set()
    document_trace: List[dict] = []

    def on_response(response):
        try:
            parsed = urlparse(response.url)
            if (parsed.hostname != "www.daangn.com" or parsed.path != core.SEARCH_PATH or
                    response.request.resource_type != "document"):
                return

            async def trace_work():
                data = await cookie_document_trace(response)
                document_trace.append(data)

            task = asyncio.create_task(trace_work())
            doc_tasks.add(task)
            task.add_done_callback(doc_tasks.discard)
        except Exception:
            pass

    page.on("response", on_response)
    try:
        stage = await prior.sample_document(page, region, args, active, pending,
                                            {"phase": phase, "plan": plan_key})
        if doc_tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*list(doc_tasks), return_exceptions=True), timeout=8)
            except asyncio.TimeoutError:
                stage.setdefault("errors", []).append("DOCUMENT_COOKIE_TRACE_TIMEOUT")
        private_after, after = await state_snapshot(context, page)
        stage["session_state"] = {
            "before": before,
            "after": after,
            "cookie_change": cookie_delta(private_before, private_after),
            "storage_count_change": storage_count_change(before, after),
            "main_document_cookie_headers": document_trace[-1] if document_trace else
              sanitize_document_cookie_evidence(request_cookie_pair_count=None,
                  set_cookie_header_count=None, http_status=None, errors=["DOCUMENT_TRACE_MISSING"]),
        }
        stage["session_state_observed"] = bool(before.get("available") and after.get("available"))
        stage["cookie_and_storage_values_persisted"] = False
        return stage
    finally:
        page.remove_listener("response", on_response)
        if doc_tasks:
            # Only telemetry tasks; bounded and never background-persisted.
            for task in list(doc_tasks):
                task.cancel()
            await asyncio.gather(*list(doc_tasks), return_exceptions=True)


def pair_comparison(first: dict, repeat: dict) -> dict:
    """One cold->repeat or switched->repeat comparison: descriptive, not causal."""
    if not prior.phase_ok(first) or not prior.phase_ok(repeat):
        return {"verdict": "INDETERMINATE_INVALID_SEARCH_SAMPLE"}
    p = (first.get("session_state") or {})
    q = (repeat.get("session_state") or {})
    first_delta, repeat_delta = p.get("cookie_change") or {}, q.get("cookie_change") or {}
    d1, d2 = p.get("main_document_cookie_headers") or {}, q.get("main_document_cookie_headers") or {}
    similarity = prior.metric(first["loader_urls"], repeat["loader_urls"])
    j = similarity.get("jaccard")
    if (not first_delta.get("available") or not repeat_delta.get("available") or
            d1.get("request_cookie_pair_count") is None or
            d2.get("request_cookie_pair_count") is None):
        verdict = "INDETERMINATE_COOKIE_OBSERVATION_INCOMPLETE"
    else:
        listing_change = bool(j is not None and j < 0.98)
        cookie_change = (bool(first_delta.get("any_cookie_state_change")) or
                         bool(repeat_delta.get("any_cookie_state_change")) or
                         d1["request_cookie_pair_count"] != d2["request_cookie_pair_count"])
        if listing_change and cookie_change:
            verdict = "LISTING_CHANGE_WITH_COOKIE_STATE_TRANSITION_OBSERVED"
        elif listing_change:
            verdict = "LISTING_CHANGE_WITHOUT_OBSERVED_COOKIE_STATE_TRANSITION"
        elif cookie_change:
            verdict = "COOKIE_STATE_TRANSITION_WITH_STABLE_LISTINGS"
        else:
            verdict = "STABLE_LISTINGS_AND_NO_COOKIE_STATE_TRANSITION_OBSERVED"
    return {
        "verdict": verdict,
        "listing_set_comparison": similarity,
        "listing_substantial_change_threshold": 0.98,
        "first_request_cookie_pair_count": d1.get("request_cookie_pair_count"),
        "repeat_request_cookie_pair_count": d2.get("request_cookie_pair_count"),
        "first_response_set_cookie_header_count": d1.get("response_set_cookie_header_count"),
        "repeat_response_set_cookie_header_count": d2.get("response_set_cookie_header_count"),
        "first_navigation_cookie_state_change": first_delta,
        "repeat_navigation_cookie_state_change": repeat_delta,
        "cookie_count_after_first": (p.get("after") or {}).get("cookie_count"),
        "cookie_count_after_repeat": (q.get("after") or {}).get("cookie_count"),
        "storage_key_counts_after_first": {
            k: (p.get("after") or {}).get(k)
            for k in ("local_storage_key_count", "session_storage_key_count")},
        "storage_key_counts_after_repeat": {
            k: (q.get("after") or {}).get(k)
            for k in ("local_storage_key_count", "session_storage_key_count")},
        "cookie_causality_proven": False,
        "server_side_session_inferred": False,
    }


def analyze(plans: list, selected_count: int) -> dict:
    """Use the v4.3.1 collision detector plus cookie-transition evidence."""
    initial = prior.classify_initial_behavior(plans)
    cases = []
    for plan in plans:
        stages = plan.get("stages", [])
        if len(stages) != 4:
            cases.append({"plan": plan.get("key"), "first_vs_repeat": {"verdict": "INDETERMINATE"},
                          "switched_vs_repeat": {"verdict": "INDETERMINATE"}})
            continue
        cases.append({"plan": plan.get("key"),
                      "first_vs_repeat": pair_comparison(stages[0], stages[1]),
                      "switched_vs_repeat": pair_comparison(stages[2], stages[3])})
    firsts = [x["first_vs_repeat"] for x in cases]
    labels = [x.get("verdict", "INDETERMINATE") for x in firsts]
    with_cookies = labels.count("LISTING_CHANGE_WITH_COOKIE_STATE_TRANSITION_OBSERVED")
    without_cookies = labels.count("LISTING_CHANGE_WITHOUT_OBSERVED_COOKIE_STATE_TRANSITION")
    incomplete = sum(x.startswith("INDETERMINATE") for x in labels)
    if incomplete or len(cases) != selected_count:
        verdict = "INDETERMINATE_INCOMPLETE_STATE_EVIDENCE"
    elif with_cookies and without_cookies:
        verdict = "MIXED_COOKIE_ASSOCIATION_ACROSS_CONTEXTS"
    elif with_cookies:
        verdict = "COOKIE_CHANGE_CO_OCCURS_WITH_COLD_LISTING_SHIFT"
    elif without_cookies:
        verdict = "COLD_LISTING_SHIFT_WITHOUT_OBSERVED_COOKIE_CHANGE"
    else:
        verdict = "NO_SUBSTANTIAL_COLD_LISTING_SHIFT_IN_THIS_RUN"
    return {
        "verdict": verdict,
        "initial_listing_behavior": initial,
        "per_plan": cases,
        "substantial_shift_with_cookie_transition": with_cookies,
        "substantial_shift_without_cookie_transition": without_cookies,
        "incomplete_cookie_observations": incomplete,
        "browser_cookie_causality_proven": False,
        "backend_session_causality_proven": False,
        "note": "Cookie changes are correlations only; unchanged client cookies do not exclude server-side state.",
    }


def safe_error(exc: Exception) -> str:
    return type(exc).__name__


async def run_plan(browser, args, key: str, targets: tuple) -> dict:
    context = await browser.new_context(locale="ko-KR", viewport={"width": 1280, "height": 850})
    page = await context.new_page()
    context.set_default_timeout(args.timeout * 1000)
    active: Dict[str, Any] = {"bucket": None, "stop": None}
    pending: Set[asyncio.Task] = set()

    def record_standard(response):
        if not core._is_relevant_first_party(response) or active.get("bucket") is None:
            return
        task = asyncio.create_task(core.record_response(response, active["bucket"], active["stop"]))
        pending.add(task)
        task.add_done_callback(pending.discard)

    page.on("response", record_standard)
    plan = {"key": key, "targets": list(targets), "started_utc": now(),
            "stages": [], "status": "NOT_STARTED"}
    try:
        for i, target in enumerate(targets):
            region = core.BY_KEY[target]
            stage = await sample_with_state(context, page, region, args, active, pending,
                                            PHASES[i], key)
            stage["step"] = i + 1
            plan["stages"].append(stage)
            cookie_info = (stage.get("session_state") or {}).get("after") or {}
            doc_trace = (stage.get("session_state") or {}).get("main_document_cookie_headers") or {}
            print("{name} [{step}/4] {area}: listings={count}, cookies={cookies}, "
                  "sent-cookie-pairs={sent}, verified={ok}".format(
                      name=key, step=i+1, area=region["label"],
                      count=len(stage.get("loader_urls") or []),
                      cookies=cookie_info.get("cookie_count"),
                      sent=doc_trace.get("request_cookie_pair_count"), ok=prior.phase_ok(stage)))
            if stage.get("blocked"):
                plan["status"] = "STOP_ACCESS_RESTRICTED"
                break
            if not prior.phase_ok(stage):
                plan["status"] = "STOP_SAMPLE_UNVERIFIED"
                break
            if not stage.get("session_state_observed"):
                plan["status"] = "STOP_STATE_CAPTURE_UNVERIFIED"
                break
            if i < 3:
                await page.wait_for_timeout(args.pause_ms)
        if plan["status"] == "NOT_STARTED":
            plan["status"] = "CAPTURED_FOUR_PHASES"
    except Exception as exc:
        plan["status"] = "RUNTIME_ERROR"
        plan["error_type"] = safe_error(exc)
    finally:
        active["bucket"] = None
        await core.drain(pending)
        await context.close()
    plan["listing_analysis"] = prior.summarize_plan(plan)
    if len(plan["stages"]) == 4:
        plan["session_pair_analyses"] = {
            "cold_to_repeat": pair_comparison(plan["stages"][0], plan["stages"][1]),
            "switch_to_repeat": pair_comparison(plan["stages"][2], plan["stages"][3]),
        }
    return plan


def fmt(v: Any) -> str:
    return "-" if v is None else str(v)


def report(data: dict) -> str:
    a = data.get("analysis") or {}
    lines = [
        "# 당근 Playwright v4.3.2 — 최초 요청과 쿠키·세션 상태 진단", "",
        "- 실행 시각(UTC): " + data["timestamp_utc"],
        "- 검색어: " + data["keyword"],
        "- 실행 상태: **" + data["status"] + "**",
        "- 상태 관련성 판정: **" + a.get("verdict", "NOT_ANALYZED") + "**",
        "- 초기 응답 판정: **" + (a.get("initial_listing_behavior") or {}).get("verdict", "NOT_ANALYZED") + "**", "",
        "## 실험: 새 비로그인 컨텍스트에서 최초/재방문/지역변경/재방문", "",
        "| 컨텍스트 | 단계 | 지역 | 매물 수 | 쿠키 전→후 | 쿠키 값 변경 개수 | 요청 Cookie 쌍 | 응답 Set-Cookie 헤더 | localStorage 키 | sessionStorage 키 |",
        "|---|---:|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    for p in data.get("plans", []):
        for s in p.get("stages", []):
            state = s.get("session_state") or {}
            bef, aft = state.get("before") or {}, state.get("after") or {}
            delta = state.get("cookie_change") or {}
            doc = state.get("main_document_cookie_headers") or {}
            lines.append("| {} | {} | {} | {} | {}→{} | {} | {} | {} | {} | {} |".format(
                p["key"], s.get("step", "-"), s.get("target", "-"),
                len(s.get("loader_urls") or []), fmt(bef.get("cookie_count")),
                fmt(aft.get("cookie_count")), fmt(delta.get("value_changed_count")),
                fmt(doc.get("request_cookie_pair_count")),
                fmt(doc.get("response_set_cookie_header_count")),
                fmt(aft.get("local_storage_key_count")), fmt(aft.get("session_storage_key_count"))))
    lines.extend(["", "## 첫 요청 대비 동일 URL 재방문", "",
                  "| 실험 | 첫↔재방문 Jaccard | Cookie 상태 전환 관련성 | 초기 응답 Set-Cookie | 재요청 Cookie 쌍 |",
                  "|---|---:|---|---:|---:|"])
    for x in a.get("per_plan", []):
        comp = x.get("first_vs_repeat") or {}
        m = comp.get("listing_set_comparison") or {}
        j = m.get("jaccard")
        lines.append("| {} | {} | {} | {} | {} |".format(
            x.get("plan"), "-" if j is None else "{:.4f}".format(j),
            comp.get("verdict", "INDETERMINATE"),
            fmt(comp.get("first_response_set_cookie_header_count")),
            fmt(comp.get("repeat_request_cookie_pair_count"))))
    collisions = (a.get("initial_listing_behavior") or {}).get("cold_cross_region_collisions") or []
    lines.extend(["", "## 교차 지역 동일 최초 응답", ""])
    if not collisions:
        lines.append("- 이번 실행에서 첫 문서의 지역 간 완전 동일 매물 집합은 관측되지 않았거나 표본이 부족합니다.")
    for c in collisions:
        lines.append("- 지역 {}: {}개 그룹, 집합 지문 {}…".format(
            ", ".join(c["regions"]), ",".join(map(str, c["article_counts"])), c["set_sha256"][:16]))
    lines.extend(["", "## 해석상의 제약", "",
                  "- 쿠키 수·속성·변경 여부·요청 헤더 존재·Set-Cookie 헤더 개수만 저장합니다. 쿠키 이름/값/도메인/경로, 인증 토큰, 저장소 키/값은 출력하지 않습니다.",
                  "- 쿠키 값의 변경 여부는 일시적으로 메모리에서만 비교합니다. 키 개수 관측은 localStorage/sessionStorage 내용의 변화까지 입증하지 않습니다.",
                  "- 최초 요청 이후 쿠키가 생기고 상품이 달라져도 인과관계는 입증되지 않습니다. 서버 내부 상태, 추천·시각 효과도 남습니다.",
                  "- 쿠키 상태 변화가 관측되지 않아도 서버 측 비쿠키 상태가 사용됐을 가능성은 배제할 수 없습니다.",
                  "- 실험은 3개 독립 컨텍스트의 최대 12회 공개 문서 탐색이며, 우회·로그인·쿠키 주입·강제 캐시 무효화가 없습니다.",
                  "- 지역별 전체 매물 수집률이나 거래 가능한 실제 거리, 서비스의 자동 수집 허가를 입증하지 않습니다.", ""])
    return "\n".join(lines)


def write_artifacts(data: dict, folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    json_path = folder / "daangn_browser_v4_3_2_results.json"
    report_path = folder / "daangn_browser_v4_3_2_report.md"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(report(data), encoding="utf-8")
    print("Saved:", json_path)
    print("Saved:", report_path)


async def run(args) -> int:
    data = {
        "version": VERSION, "timestamp_utc": now(), "keyword": args.keyword,
        "headed": args.headed, "new_unauthenticated_context_per_plan": True,
        "cookies_read_only": True, "no_cookie_values_saved": True,
        "storage_key_counts_only": True,
        "collection_mode": "bounded_3_context_4_phase_first_party_observational",
        "plans": [], "status": "NOT_STARTED",
    }
    data["robots"] = core.public_robots_check(args.keyword)
    if not data["robots"].get("allowed"):
        data["status"] = "STOP_ROBOTS_UNVERIFIED_OR_DISALLOWED"
        write_artifacts(data, args.output_dir)
        return 2
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        data["status"] = "PLAYWRIGHT_NOT_INSTALLED_IN_VENV"
        write_artifacts(data, args.output_dir)
        return 2
    selected = [p for p in PLANS if args.plan in ("all", p[0])]
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=not args.headed)
            try:
                for i, (key, targets) in enumerate(selected):
                    plan = await run_plan(browser, args, key, targets)
                    data["plans"].append(plan)
                    if plan.get("status") != "CAPTURED_FOUR_PHASES":
                        data["status"] = plan.get("status", "STOP_INCOMPLETE")
                        break
                    if i < len(selected) - 1:
                        await asyncio.sleep(args.pause_ms / 1000)
            finally:
                await browser.close()
    except Exception as exc:
        data["status"] = "BROWSER_RUNTIME_ERROR"
        data["error_type"] = safe_error(exc)
    data["analysis"] = analyze(data["plans"], len(selected))
    if data["status"] == "NOT_STARTED":
        data["status"] = ("CAPTURED_SESSION_STATE_DIAGNOSTIC"
                          if len(data["plans"]) == len(selected) else "INCOMPLETE")
    write_artifacts(data, args.output_dir)
    return 0 if data["status"] == "CAPTURED_SESSION_STATE_DIAGNOSTIC" else 2


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Daangn v4.3.2: compare cold and repeat listing sets with cookie/session state")
    p.add_argument("--keyword", default="HDD")
    p.add_argument("--plan", choices=("all", *(x[0] for x in PLANS)), default="all")
    p.add_argument("--headed", action="store_true")
    p.add_argument("--timeout", type=int, default=22)
    p.add_argument("--settle-ms", type=int, default=1300)
    p.add_argument("--pause-ms", type=int, default=1500)
    p.add_argument("--min-dom-overlap", type=float, default=0.8)
    p.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
    return p


def main() -> int:
    p = parser()
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
