#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Daangn public-search Playwright diagnostic v4.1, Python >= 3.9.

Purpose: compare SPA/UI region changes using the public search route JSON,
visible DOM product links, actual URL, and displayed region. The boot-time
window.__remixContext is explicitly *not* an authoritative post-navigation state.

This is a bounded, read-only diagnostic. No credentials, authentication cookie
reuse, proxy, captcha solving, anti-bot workaround, or automated transactions.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
from collections import Counter
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib import request as url_request, robotparser
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse, parse_qsl

BASE = "https://www.daangn.com"
SEARCH_PATH = "/kr/search/buy-sell/"
REGION_API = "/kr/api/v1/regions/keyword"
ROUTE_ID = "routes/kr.search.buy-sell._index"
REGIONS = [
    {"key": "control", "label": "지역 미설정", "slug": None, "term": None, "id": None},
    {"key": "sadang", "label": "사당", "slug": "사당제3동-334", "term": "사당제3동", "id": "334"},
    {"key": "cheonan", "label": "천안", "slug": "불당동-2292", "term": "불당동", "id": "2292"},
    {"key": "asan", "label": "아산", "slug": "배방읍-2333", "term": "배방읍", "id": "2333"},
]
BY_KEY = {x["key"]: x for x in REGIONS}
BLOCK_STATUS = {401, 403, 429}
BLOCK_TEXT = re.compile(r"captcha|verify you are human|access denied|unusual traffic|비정상적인 접근|자동화된 접근", re.I)
LISTING_PATH = re.compile(r"^/kr/buy-sell/[^/]+-[a-zA-Z0-9]{10,}/?$")
MAX_BODY = 2_000_000
MAX_ARTICLES = 650

JS_SNAPSHOT = r"""() => {
  const isProduct = (href) => {
    try {const u=new URL(href,location.href);
      return u.hostname==='www.daangn.com' && /^\/kr\/buy-sell\/[^/]+-[A-Za-z0-9]{10,}\/?$/.test(u.pathname);
    } catch {return false;}
  };
  const links=new Map();
  for (const a of document.querySelectorAll('a[href]')) {
    const href=a.getAttribute('href'); if (!isProduct(href)) continue;
    const u=new URL(href,location.href);
    const normalized=u.origin+u.pathname.replace(/\/$/,'')+'/';
    const s=getComputedStyle(a);
    const visible=a.getClientRects().length>0 && s.display!=='none' && s.visibility!=='hidden';
    if (!links.has(normalized) || (visible && !links.get(normalized).visible))
      links.set(normalized,{url:normalized, visible:visible});
  }
  const state=window.__remixContext?.state?.loaderData || {};
  const loader=state['routes/kr.search.buy-sell._index'] ||
    state[Object.keys(state).find(k=>/search.*buy-sell/.test(k))];
  const snapshotArticles=Array.isArray(loader?.buySellArticles) ? loader.buySellArticles : [];
  const button=[...document.querySelectorAll('button[aria-label]')]
    .map(b=>b.getAttribute('aria-label')||'').find(s=>s.startsWith('지역 선택:')) || '';
  const challenge=/captcha|verify you are human|access denied|unusual traffic|비정상적인 접근|자동화된 접근/i
    .test((document.body?.innerText||'').slice(0,6000));
  const loginWall=/로그인이 필요합니다|로그인 후 이용|로그인이 필요한/i
    .test((document.body?.innerText||'').slice(0,6000));
  return {
    region_button:button,
    title:document.title,
    challenge:challenge, login_wall:loginWall,
    dom_all:[...links.keys()],
    dom_visible:[...links.values()].filter(x=>x.visible).map(x=>x.url),
    initial_loader_region_id:loader?.searchRegion?.id != null ? String(loader.searchRegion.id) : null,
    initial_loader_filter_region_id:loader?.currentFilters?.regionId != null ? String(loader.currentFilters.regionId) : null,
    initial_loader_count:snapshotArticles.length,
    initial_loader_urls:snapshotArticles.slice(0,650).map(x=>String(x.href||'')).filter(Boolean)
  };
}"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def search_url(keyword: str, region: dict) -> str:
    q = {"q": keyword}
    if region["slug"]:
        q["in"] = region["slug"]
    return BASE + SEARCH_PATH + "?" + urlencode(q)


def sanitized_url(url: str) -> str:
    """Keep only known public search arguments, never log arbitrary tokens."""
    try:
        p = urlparse(url)
        allow = {"q", "in", "search", "_data"}
        q = [(k, v[:100]) for k, v in parse_qsl(p.query, keep_blank_values=True) if k in allow]
        return urlunparse((p.scheme, p.netloc, p.path, "", urlencode(q), ""))
    except (ValueError, TypeError):
        return "INVALID_URL"


def normalized_listing(url: str) -> Optional[str]:
    if not isinstance(url, str) or not url:
        return None
    try:
        p = urlparse(url if url.startswith("http") else BASE + (url if url.startswith("/") else "/" + url))
        if p.hostname != "www.daangn.com" or not LISTING_PATH.fullmatch(p.path):
            return None
        return BASE + p.path.rstrip("/") + "/"
    except (ValueError, TypeError):
        return None


def region_id_in_url(url: str) -> Optional[str]:
    try:
        slug = parse_qs(urlparse(url).query).get("in", [None])[0]
        match = re.search(r"-(\d+)$", slug or "")
        return match.group(1) if match else None
    except ValueError:
        return None


def jaccard(a: List[str], b: List[str]) -> Optional[float]:
    a1, b1 = set(a), set(b)
    return round(len(a1 & b1) / len(a1 | b1), 5) if (a1 or b1) else None


def compare_urls(a: List[str], b: List[str]) -> dict:
    left, right = set(a), set(b)
    return {
        "left": len(left), "right": len(right), "overlap": len(left & right),
        "jaccard": jaccard(a, b),
        "left_only_sample": sorted(left - right)[:5],
        "right_only_sample": sorted(right - left)[:5],
    }


def public_robots_check(keyword: str) -> dict:
    """Refuse tests if robots.txt unavailable or disallows relevant paths."""
    urls = [search_url(keyword, r) for r in REGIONS] + [
        BASE + REGION_API + "?keyword=불당동",
        BASE + SEARCH_PATH + "?in=불당동-2292&q=" + keyword + "&_data=" + ROUTE_ID,
    ]
    info = {"checked": False, "allowed": False, "reason": "unverified", "http_status": None}
    try:
        with url_request.urlopen(url_request.Request(BASE + "/robots.txt", headers={
            "User-Agent": "DaangnRegionDiagnostic/4.1"}), timeout=20) as response:
            info["http_status"] = response.status
            if response.status != 200:
                info["reason"] = "robots_http_not_200"
                return info
            body = response.read(400_001)
        if len(body) > 400_000:
            info["reason"] = "robots_too_large"
            return info
        rp = robotparser.RobotFileParser()
        rp.parse(body.decode("utf-8", "replace").splitlines())
        denied = [sanitized_url(url) for url in urls if not rp.can_fetch("DaangnRegionDiagnostic", url)]
        info.update({"checked": True, "allowed": not denied, "reason": "allowed" if not denied else "disallowed",
                     "disallowed": denied})
    except Exception as exc:
        info["reason"] = "robots_request_failed:" + type(exc).__name__
    return info


def _iter_dicts(obj: Any, depth: int = 0):
    """Bounded traversal of a public route's JSON shape; no arbitrary eval."""
    if depth > 7:
        return
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            if isinstance(v, (dict, list)):
                yield from _iter_dicts(v, depth + 1)
    elif isinstance(obj, list):
        for item in obj[:40]:
            if isinstance(item, (dict, list)):
                yield from _iter_dicts(item, depth + 1)


def _extract_article_urls(rows: list) -> List[str]:
    result: Set[str] = set()
    for row in rows[:MAX_ARTICLES]:
        if not isinstance(row, dict):
            continue
        for k in ("href", "url", "link"):
            candidate = normalized_listing(row.get(k, ""))
            if candidate:
                result.add(candidate)
                break
    return sorted(result)


def parse_search_route_json(raw: bytes) -> dict:
    """Extract route-specific region metadata and article URLs from public JSON."""
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return {"parsed": False, "error": "not_json"}
    candidates = []
    for node in _iter_dicts(obj):
        if "buySellArticles" in node and isinstance(node["buySellArticles"], list):
            candidates.append(node)
    if not candidates:
        return {"parsed": True, "route_found": False, "top_level_type": type(obj).__name__}
    # Pick the route object, not a nested item's unrelated data.
    candidates.sort(key=lambda n: (int(isinstance(n.get("searchRegion"), dict)) +
                                  int(isinstance(n.get("currentFilters"), dict)),
                                  len(n["buySellArticles"])), reverse=True)
    node = candidates[0]
    region = node.get("searchRegion") if isinstance(node.get("searchRegion"), dict) else {}
    filters = node.get("currentFilters") if isinstance(node.get("currentFilters"), dict) else {}
    articles = node["buySellArticles"]
    urls = _extract_article_urls(articles)
    names = [str(x.get("region", {}).get("name", "") if isinstance(x.get("region"), dict) else x.get("region", "")).strip()
             for x in articles if isinstance(x, dict)]
    area_counts = Counter(n for n in names if n)
    return {
        "parsed": True, "route_found": True,
        "search_region_id": str(region["id"]) if region.get("id") is not None else None,
        "search_region_name": str(region.get("name", ""))[:90],
        "filter_region_id": str(filters["regionId"]) if filters.get("regionId") is not None else None,
        "query_keyword": str(node.get("keyword") or filters.get("search") or "")[:90],
        "article_count": len(articles), "unique_url_count": len(urls),
        "item_region_known_count": sum(bool(n) for n in names),
        "item_region_histogram": dict(area_counts.most_common(60)),
        "article_urls": urls,
        "article_samples": [{"title": str(x.get("title", ""))[:100],
                             "region": (str(x.get("region", {}).get("name", ""))[:60]
                                        if isinstance(x.get("region"), dict)
                                        else str(x.get("region", ""))[:60]),
                             "price": str(x.get("price", ""))[:25],
                             "url": next((v for k in ("href", "url", "link")
                                          if (v := normalized_listing(x.get(k, "")))), None)}
                            for x in articles[:5] if isinstance(x, dict)]
    }


def classify_ui(target: dict, before: dict, after: dict, route: Optional[dict],
                url: str, block: bool = False) -> dict:
    """All independent signals must corroborate; boot loader never decides success."""
    expected = target["id"]
    button = after.get("region_button") or ""
    url_id = region_id_in_url(url)
    url_match = url_id == expected
    button_match = bool(target["term"] and target["term"] in button)
    # A full success needs both independent region IDs inside the route response.
    fetch_match = bool(route and route.get("route_found") and route.get("search_region_id") == expected and
                       route.get("filter_region_id") == expected)
    fetch_conflict = bool(route and route.get("route_found") and (
        (route.get("search_region_id") is not None and route.get("search_region_id") != expected) or
        (route.get("filter_region_id") is not None and route.get("filter_region_id") != expected)))
    dom_urls = after.get("dom_visible", [])
    fetched = route.get("article_urls", []) if route else []
    overlap = len(set(dom_urls) & set(fetched))
    overlap_ratio = overlap / len(dom_urls) if dom_urls else 0.0
    # A single shared listing is weak evidence. Require >=80% of visible links in fetch.
    dom_correlated = bool(dom_urls and fetched and overlap_ratio >= 0.8)
    initial_id = after.get("initial_loader_region_id")
    stale_boot_loader = bool(initial_id is not None and initial_id != expected)
    signals = {
        "url_region_id": url_id, "url_match": url_match,
        "button_label": button, "button_match": button_match,
        "fetch_search_region_id": route.get("search_region_id") if route else None,
        "fetch_filter_region_id": route.get("filter_region_id") if route else None,
        "fetch_route_found": bool(route and route.get("route_found")),
        "fetch_region_match": fetch_match, "fetch_region_conflict": fetch_conflict,
        "dom_visible_count": len(dom_urls), "fetch_article_count": route.get("article_count") if route else None,
        "dom_fetch_overlap_count": overlap, "dom_fetch_overlap_ratio": round(overlap_ratio, 5) if dom_urls else None,
        "dom_fetch_correlated": dom_correlated,
        "initial_loader_region_id": initial_id,
        "stale_boot_loader_observed": stale_boot_loader,
        "before_vs_after_dom": compare_urls(before.get("dom_visible", []), dom_urls),
    }
    if block or after.get("challenge"):
        verdict = "STOP_ACCESS_RESTRICTED"
    elif after.get("login_wall"):
        verdict = "LOGIN_WALL"
    elif fetch_conflict:
        verdict = "UI_FETCH_REGION_MISMATCH"
    elif url_match and button_match and fetch_match and dom_correlated:
        verdict = "UI_REGION_CHANGE_VERIFIED_FETCH_DOM"
    elif url_match and button_match and fetch_match:
        verdict = "UI_FETCH_REGION_OK_DOM_UNCONFIRMED"
    elif url_match and button_match and route and route.get("route_found"):
        verdict = "UI_FETCH_INCOMPLETE_REGION_METADATA"
    elif url_match and button_match and not route:
        verdict = "UI_CHANGED_FETCH_NOT_CAPTURED"
    elif url_match and fetch_match:
        verdict = "UI_FETCH_OK_BUTTON_NOT_CONFIRMED"
    else:
        verdict = "UI_REGION_CHANGE_NOT_VERIFIED"
    signals["verdict"] = verdict
    signals["verified"] = verdict == "UI_REGION_CHANGE_VERIFIED_FETCH_DOM"
    signals["geographic_completeness_verified"] = False
    return signals


def _is_relevant_first_party(response) -> bool:
    try:
        p = urlparse(response.url)
        return p.hostname == "www.daangn.com" and response.request.resource_type in ("document", "fetch", "xhr") and (
            "/kr/search/buy-sell/" in p.path or "/kr/api/v1/regions/keyword" in p.path)
    except (TypeError, ValueError):
        return False


def _is_search_route_response(url: str) -> bool:
    p = urlparse(url)
    return p.path.startswith(SEARCH_PATH) and ROUTE_ID in parse_qs(p.query).get("_data", [])


async def record_response(response, bucket: dict, stop: dict):
    if not _is_relevant_first_party(response):
        return
    if len(bucket["network"]) >= 40:
        bucket["network_overflow"] = True
        return
    info = {"url": sanitized_url(response.url), "status": response.status,
            "resource_type": response.request.resource_type,
            "content_type": response.headers.get("content-type", "").split(";")[0].lower(),
            "is_search_route": _is_search_route_response(response.url)}
    if response.status in BLOCK_STATUS:
        stop["blocked"] = True
        stop["reason"] = "HTTP_" + str(response.status)
    if info["is_search_route"]:
        if response.status != 200:
            info["route_error"] = "http_" + str(response.status)
        elif "json" not in info["content_type"]:
            info["route_error"] = "not_json_content_type"
            if "html" in info["content_type"]:
                stop["blocked"] = True
                stop["reason"] = "route_json_replaced_by_html"
        else:
            try:
                content_length = response.headers.get("content-length", "")
                if content_length.isdecimal() and int(content_length) > MAX_BODY:
                    info["route_error"] = "oversize_content_length"
                else:
                    body = await asyncio.wait_for(response.body(), timeout=12)
                    info["size_bytes"] = len(body)
                    if len(body) > MAX_BODY:
                        info["route_error"] = "oversize_body"
                    else:
                        info["sha256"] = hashlib.sha256(body).hexdigest()
                        info["route_data"] = parse_search_route_json(body)
            except Exception as exc:
                info["route_error"] = type(exc).__name__
    bucket["network"].append(info)


async def drain(tasks: Set[asyncio.Task]):
    if tasks:
        try:
            await asyncio.wait_for(asyncio.gather(*list(tasks), return_exceptions=True), timeout=15)
        except asyncio.TimeoutError:
            pass


def latest_route(bucket: dict, expected_id: Optional[str] = None) -> Optional[dict]:
    routes = [r["route_data"] for r in bucket.get("network", []) if r.get("is_search_route") and
              r.get("status") == 200 and r.get("route_data", {}).get("route_found")]
    if expected_id is not None:
        matches = [r for r in routes if r.get("search_region_id") == expected_id]
        return matches[-1] if matches else (routes[-1] if routes else None)
    return routes[-1] if routes else None


async def get_snapshot(page) -> dict:
    result = await page.evaluate(JS_SNAPSHOT)
    clean = lambda vals: sorted({x for x in (normalized_listing(v) for v in vals) if x})
    result["dom_visible"] = clean(result.get("dom_visible", []))
    result["dom_all"] = clean(result.get("dom_all", []))
    result["initial_loader_urls"] = clean(result.get("initial_loader_urls", []))
    result["url"] = sanitized_url(page.url)
    result["region_id_from_url"] = region_id_in_url(page.url)
    result["visible_dom_count"] = len(result["dom_visible"])
    result["initial_loader_unique_count"] = len(result["initial_loader_urls"])
    return result


async def observe_selected_region_control(page, region: dict) -> dict:
    """Observe only a visible, localized region control, never page-wide text.

    The result contains fixed booleans/counts, not HTML or seller/listing text.
    A successful region-picker click alone is explicitly not enough.
    """
    try:
        result = await page.evaluate(r"""term => {
          const visible = e => {
            const s = getComputedStyle(e);
            return e.getClientRects().length > 0 &&
                   s.display !== 'none' && s.visibility !== 'hidden';
          };
          const controls = [...document.querySelectorAll(
              'button,[role="button"],[role="combobox"]')]
              .filter(e => visible(e) &&
                  !e.closest('article,[href*="/kr/buy-sell/"]'));
          let matched = 0;
          for (const e of controls.slice(0, 120)) {
            const aria = (e.getAttribute('aria-label') || '').trim();
            const text = (e.innerText || '').trim().replace(/\\s+/g,' ');
            const value = (aria + ' ' + text).slice(0, 180);
            const regionContext = /지역|동네/.test(aria) ||
                  /지역 선택|동네 선택/.test(text) ||
                  (/지역|동네/.test(
                    (e.closest('[aria-label]')?.getAttribute('aria-label') || '')
                  ));
            if (value.includes(term) && regionContext) matched++;
          }
          return {verified: matched === 1,
                  matching_controls: Math.min(matched, 3),
                  classification: matched === 1 ? 'VISIBLE_REGION_CONTROL_MATCH'
                      : matched === 0 ? 'REGION_CONTROL_NOT_OBSERVED'
                      : 'AMBIGUOUS_REGION_CONTROLS'};
        }""", region["term"])
        return result if isinstance(result, dict) and result.get(
            "classification") in (
                "VISIBLE_REGION_CONTROL_MATCH",
                "REGION_CONTROL_NOT_OBSERVED",
                "AMBIGUOUS_REGION_CONTROLS") else {
                    "verified": False,
                    "classification": "REGION_CONTROL_NOT_OBSERVED"}
    except Exception:
        return {"verified": False,
                "classification": "REGION_CONTROL_NOT_OBSERVED"}


async def wait_for_route(bucket: dict, expected_id: str, timeout_seconds: float) -> Optional[dict]:
    """Wait for processed fetch JSON, not for boot-time Remix state."""
    end = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < end:
        found = latest_route(bucket, expected_id)
        if found and found.get("search_region_id") == expected_id:
            return found
        await asyncio.sleep(0.15)
    return latest_route(bucket, expected_id)


async def stable_page_snapshot(page, expected_term: str, settle_ms: int) -> dict:
    """Wait for a live region button, then two short DOM samples."""
    try:
        await page.wait_for_function("term => [...document.querySelectorAll('button[aria-label]')].some(x => (x.getAttribute('aria-label')||'').includes(term))",
                                     arg=expected_term, timeout=8000)
    except Exception:
        pass
    await page.wait_for_timeout(settle_ms)
    first = await get_snapshot(page)
    await page.wait_for_timeout(450)
    second = await get_snapshot(page)
    second["dom_stable_across_samples"] = first["dom_visible"] == second["dom_visible"]
    return second


async def ui_select_region(page, region: dict) -> dict:
    steps = {"target": region["term"], "clicked_region_button": False, "selected_suggestion": False,
             "error": None, "start_url": sanitized_url(page.url)}
    try:
        selector = page.get_by_role("button", name=re.compile(r"지역 선택"))
        await selector.first.click(timeout=5000)
        steps["clicked_region_button"] = True
        await page.wait_for_timeout(500)
        inputs = page.locator('input[placeholder*="지역"], input[placeholder*="동네"], [role="dialog"] input, [role="combobox"]')
        if await inputs.count() == 0:
            steps["error"] = "region_input_not_found"
            return steps
        await inputs.first.fill(region["term"], timeout=4000)
        await page.wait_for_timeout(850)
        choices = page.locator('[role="option"], [role="listbox"] button, [role="dialog"] button, [role="dialog"] [role="option"]')
        matching = choices.filter(has_text=region["term"])
        if await matching.count() == 0:
            steps["error"] = "matching_region_option_not_found"
            return steps
        await matching.first.click(timeout=5000)
        steps["selected_suggestion"] = True
    except Exception as exc:
        steps["error"] = type(exc).__name__ + ":" + str(exc)[:180]
    steps["end_url"] = sanitized_url(page.url)
    return steps


async def url_test(page, region: dict, args, active: dict, pending: Set[asyncio.Task], stop: dict) -> dict:
    bucket = {"network": [], "key": region["key"], "requested_url": search_url(args.keyword, region), "errors": []}
    active["bucket"] = bucket
    active["stop"] = stop
    try:
        res = await page.goto(bucket["requested_url"], wait_until="domcontentloaded", timeout=args.timeout * 1000)
        bucket["http_status"] = res.status if res else None
        if res and res.status in BLOCK_STATUS:
            stop.update({"blocked": True, "reason": "HTTP_" + str(res.status)})
        if not stop["blocked"]:
            await page.wait_for_timeout(args.settle_ms)
            before = await get_snapshot(page)
            if args.scroll:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(800)
            after = await get_snapshot(page)
            bucket["before"] = before
            bucket["after"] = after
            if before.get("challenge") or after.get("challenge"):
                stop.update({"blocked": True, "reason": "challenge_text"})
            bucket["region_metadata_match"] = (after["initial_loader_region_id"] == region["id"] if region["id"] else None)
            bucket["dom_before_after"] = compare_urls(before["dom_visible"], after["dom_visible"])
    except Exception as exc:
        bucket["errors"].append(type(exc).__name__ + ":" + str(exc)[:180])
    await drain(pending)
    active["bucket"] = None
    bucket["blocked"] = stop["blocked"]
    bucket["block_reason"] = stop["reason"]
    bucket["route_fetch_count"] = sum(bool(n["is_search_route"]) for n in bucket["network"])
    return bucket


async def ui_test(page, source: dict, target: dict, args, active: dict, pending: Set[asyncio.Task], stop: dict) -> dict:
    before = await get_snapshot(page)
    entry = {"from": source["label"], "to": target["label"], "before": before,
             "network": [], "errors": []}
    bucket = {"network": entry["network"]}
    active["bucket"] = bucket
    active["stop"] = stop
    entry["action"] = await ui_select_region(page, target)
    if entry["action"].get("selected_suggestion") and not stop["blocked"]:
        await wait_for_route(bucket, target["id"], args.timeout)
    await drain(pending)
    if entry["action"].get("selected_suggestion") and not stop["blocked"]:
        after = await stable_page_snapshot(page, target["term"], args.settle_ms)
    else:
        after = await get_snapshot(page)
    entry["after"] = after
    if after.get("challenge") or stop["blocked"]:
        stop.update({"blocked": True, "reason": stop.get("reason") or "challenge_text"})
    await drain(pending)
    active["bucket"] = None
    route = latest_route(bucket, target["id"])
    entry["fetch_json"] = route
    entry["check"] = classify_ui(target, before, after, route, page.url, stop["blocked"])
    entry["check"]["ui_click_completed"] = bool(entry["action"].get("selected_suggestion"))
    if not entry["action"].get("selected_suggestion") and not stop["blocked"]:
        entry["check"]["verified"] = False
        entry["check"]["verdict"] = "UI_SELECTION_NOT_COMPLETED"
    return entry


def report(result: dict) -> str:
    lines = ["# Daangn Playwright v4.1 - Korean diagnostic report", "",
             "- Timestamp (UTC): " + result["timestamp_utc"],
             "- Keyword: " + result["keyword"],
             "- Status: **" + result["status"] + "**", "",
             "## URL navigation (boot HTML state)", "",
             "| Region | HTTP | DOM visible | Boot loader articles | Boot loader region | Blocked |",
             "|---|---:|---:|---:|---|---|" ]
    for x in result.get("url_tests", []):
        snap = x.get("after") or {}
        lines.append("| {key} | {http} | {dom} | {count} | {reg} | {blocked} |".format(
            key=x["key"], http=x.get("http_status", "-"), dom=snap.get("visible_dom_count", "-"),
            count=snap.get("initial_loader_count", "-"), reg=snap.get("initial_loader_region_id", "-"),
            blocked=x.get("blocked", "-")))
    lines.extend(["", "## UI switch: URL + fetch JSON + rendered DOM", "",
                  "| Switch | URL ID | Button | JSON region/filter | DOM/JSON overlap | Boot loader stale? | Verdict |",
                  "|---|---|---|---|---:|---|---|"])
    for x in result.get("ui_tests", []):
        c = x.get("check", {})
        lines.append("| {switch} | {url} | {btn} | {reg}/{flt} | {overlap} | {stale} | {verdict} |".format(
            switch=x["from"] + "→" + x["to"], url=c.get("url_region_id", "-"),
            btn=c.get("button_label", "-"), reg=c.get("fetch_search_region_id", "-"),
            flt=c.get("fetch_filter_region_id", "-"), overlap=c.get("dom_fetch_overlap_count", "-"),
            stale=c.get("stale_boot_loader_observed", False), verdict=c.get("verdict", "-")))
    lines.extend(["", "## UI details", ""])
    for x in result.get("ui_tests", []):
        c = x.get("check", {})
        lines.append("- **{a} → {b}**: {v}".format(a=x["from"], b=x["to"], v=c.get("verdict")))
        lines.append("  - URL={u}; button={b}; fetch={f}; DOM subset corroboration={d}; overlap={n}; JSON count={cnt}".format(
            u=c.get("url_match"), b=c.get("button_match"), f=c.get("fetch_region_match"),
            d=c.get("dom_fetch_correlated"), n=c.get("dom_fetch_overlap_count"),cnt=c.get("fetch_article_count")))
        if x.get("action", {}).get("error"):
            lines.append("  - UI selection error: " + x["action"]["error"])
    lines.extend(["", "## Limitations", "",
                  "- Boot-time window.__remixContext is retained only as stale-state diagnostics; it does not decide SPA UI success.",
                  "- A matching route fetch and DOM confirms UI region switch, not correct geographic coverage or complete listing recall.",
                  "- The DOM may show only a subset of fetched records, therefore a positive overlap is used as corroboration rather than an equality test.",
                  "- Time-dependent recommendations and nearby/delivery listings can produce overlapping or different candidate sets.",
                  "- This is a bounded public read-only diagnostic, not authorization for unattended scraping.",
                  "- No login credentials, request headers/bodies, or stored browser profiles are saved.", ""])
    return "\n".join(lines)


def write_results(result: dict, directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "daangn_browser_v4_1_results.json"
    md_path = directory / "daangn_browser_v4_1_report.md"
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(report(result), encoding="utf-8")
    print("Saved:", json_path)
    print("Saved:", md_path)


async def run(args) -> int:
    result: Dict[str, Any] = {"version": "4.1", "timestamp_utc": now(), "keyword": args.keyword,
        "mode": args.mode, "headed": args.headed, "new_unauthenticated_context": True,
        "credentials_or_cookies_reused": False, "url_tests": [], "ui_tests": [], "status": "NOT_STARTED"}
    robots = public_robots_check(args.keyword)
    result["robots"] = robots
    if not robots.get("allowed"):
        result["status"] = "STOP_ROBOTS_UNVERIFIED_OR_DISALLOWED"
        write_results(result, args.output_dir)
        return 2
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        result["status"] = "PLAYWRIGHT_NOT_INSTALLED_IN_VENV"
        write_results(result, args.output_dir)
        return 2
    active: Dict[str, Any] = {"bucket": None, "stop": {"blocked": False, "reason": None}}
    pending: Set[asyncio.Task] = set()
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=not args.headed)
            context = await browser.new_context(locale="ko-KR", viewport={"width": 1280, "height": 850})
            page = await context.new_page()
            context.set_default_timeout(args.timeout * 1000)

            def response_handler(resp):
                bucket = active.get("bucket")
                if bucket is None or not _is_relevant_first_party(resp):
                    return
                t = asyncio.create_task(record_response(resp, bucket, active["stop"]))
                pending.add(t)
                t.add_done_callback(pending.discard)

            page.on("response", response_handler)
            if args.mode in ("url", "both"):
                for region in REGIONS:
                    stop = {"blocked": False, "reason": None}
                    row = await url_test(page, region, args, active, pending, stop)
                    result["url_tests"].append(row)
                    print("URL {region}: HTTP={http}, DOM={dom}, initial={initial}, region={r}".format(
                        region=region["label"], http=row.get("http_status"),
                        dom=(row.get("after") or {}).get("visible_dom_count"),
                        initial=(row.get("after") or {}).get("initial_loader_count"),
                        r=(row.get("after") or {}).get("initial_loader_region_id")))
                    if stop["blocked"] or row["errors"] or (row.get("after") or {}).get("login_wall"):
                        result["status"] = "STOP_ACCESS_OR_NAVIGATION_PROBLEM"
                        break
                    await page.wait_for_timeout(900)
            if args.mode in ("ui", "both") and result["status"] == "NOT_STARTED":
                seed = BY_KEY["sadang"]
                stop = {"blocked": False, "reason": None}
                seed_run = await url_test(page, seed, args, active, pending, stop)
                result["ui_seed"] = {"key": "sadang", "http_status": seed_run.get("http_status"),
                                      "visible_dom_count": (seed_run.get("after") or {}).get("visible_dom_count"),
                                      "boot_region": (seed_run.get("after") or {}).get("initial_loader_region_id")}
                if stop["blocked"] or seed_run["errors"]:
                    result["status"] = "STOP_UI_SEED_FAILED"
                else:
                    source = seed
                    for target in (BY_KEY["cheonan"], BY_KEY["asan"]):
                        stop = {"blocked": False, "reason": None}
                        entry = await ui_test(page, source, target, args, active, pending, stop)
                        result["ui_tests"].append(entry)
                        check = entry["check"]
                        print("UI {a} -> {b}: {v}, URL={u}, button={bt}, fetch={f}, overlap={o}, boot_stale={s}".format(
                            a=source["label"],b=target["label"],v=check["verdict"],u=check["url_match"],
                            bt=check["button_match"],f=check["fetch_region_match"],
                            o=check["dom_fetch_overlap_count"],s=check["stale_boot_loader_observed"]))
                        if stop["blocked"]:
                            result["status"] = "STOP_ACCESS_RESTRICTED"
                            break
                        if not check["verified"]:
                            # Important: do not silently substitute a URL navigation and call it UI success.
                            break
                        source = target
                        await page.wait_for_timeout(900)
            if result["status"] == "NOT_STARTED":
                result["status"] = "CAPTURED_UI_AND_URL" if result["ui_tests"] and result["url_tests"] else (
                    "CAPTURED_UI" if result["ui_tests"] else "CAPTURED_URL")
            await context.close()
            await browser.close()
    except Exception as exc:
        result["status"] = "BROWSER_RUNTIME_ERROR"
        result["error"] = type(exc).__name__ + ":" + str(exc)[:250]
        print("Runtime error:", result["error"])
    write_results(result, args.output_dir)
    return 2 if result["status"].startswith("STOP_") or result["status"] == "BROWSER_RUNTIME_ERROR" else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Daangn v4.1: UI region change with fetch JSON + live DOM corroboration")
    ap.add_argument("--keyword", default="HDD")
    ap.add_argument("--mode", choices=("both", "url", "ui"), default="both")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--no-scroll", action="store_false", dest="scroll")
    ap.add_argument("--timeout", type=int, default=22)
    ap.add_argument("--settle-ms", type=int, default=1500)
    ap.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
    args = ap.parse_args()
    if not 1 <= len(args.keyword.strip()) <= 60:
        ap.error("keyword length must be 1 to 60 characters")
    args.timeout = max(10, min(args.timeout, 45))
    args.settle_ms = max(500, min(args.settle_ms, 4000))
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
