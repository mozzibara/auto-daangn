# -*- coding: utf-8 -*-
"""Bounded legacy-search compatibility probe (research evidence only).

Integrates the *approaches* of used-notifier (SSR), k-skill (legacy _data)
and daangn-crawler (browser-emitted search API). Never admits listings.
Public outputs contain fixed enums, booleans and bounded counts only.
"""
from __future__ import annotations

import asyncio
import json
import re
import urllib.request
import urllib.robotparser
from urllib.parse import parse_qs, urlencode, urlsplit

from daangn_v4_1_core import BASE, BLOCK_STATUS

AGENT = "DaangnRegionDiagnostic/4.1"
SURFACES = ("legacy_ssr", "legacy_all_data", "modern_s")
PATHS = {
    "legacy_ssr": "/kr/buy-sell/",
    "legacy_all_data": "/kr/buy-sell/all/",
    "modern_s": "/kr/buy-sell/s/",
}
BODY_LIMIT = 1_500_000
DATA_LIMIT = 512_000
COUNT_LIMIT = 650


def surface_url(surface: str, region: dict) -> str:
    if surface not in SURFACES or region.get("key") not in ("cheonan", "asan"):
        raise ValueError("UNKNOWN_PROBE_SURFACE_OR_REGION")
    params = {"search": "HDD", "in": region["slug"]}
    if surface != "legacy_ssr":
        params["only_on_sale"] = "true"
    if surface == "legacy_all_data":
        params["_data"] = "routes/kr.buy-sell._index"
    return BASE + PATHS[surface] + "?" + urlencode(params)


def check_surface_robots(region: dict, *, getter=None) -> dict:
    """Check each exact research URL before browsing; failure denies all."""
    getter = getter or urllib.request.urlopen
    verdict = {name: False for name in SURFACES}
    try:
        req = urllib.request.Request(BASE + "/robots.txt",
                                     headers={"User-Agent": AGENT})
        with getter(req, timeout=20) as response:
            if response.status != 200:
                return {"state": "ROBOTS_UNAVAILABLE", "allowed": verdict}
            raw = response.read(400_001)
        if len(raw) > 400_000:
            return {"state": "ROBOTS_UNAVAILABLE", "allowed": verdict}
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(raw.decode("utf-8", "replace").splitlines())
        for name in SURFACES:
            verdict[name] = bool(parser.can_fetch(AGENT, surface_url(name, region)))
        return {"state": "CHECKED", "allowed": verdict}
    except (OSError, TypeError, ValueError):
        return {"state": "ROBOTS_UNAVAILABLE", "allowed": verdict}


def classify_final_url(raw_url: str, surface: str, region: dict) -> dict:
    """No raw URL or unknown IDs are returned."""
    result = {"host": "OTHER", "path": "OTHER", "region": "INVALID",
              "keyword": "MISSING"}
    try:
        u = urlsplit(raw_url)
        if u.scheme != "https" or u.hostname != "www.daangn.com" or u.port:
            return result
        result["host"] = "EXPECTED"
        result["path"] = "EXPECTED" if u.path == PATHS[surface] else "OTHER"
        p = parse_qs(u.query, keep_blank_values=True)
        words = p.get("search", []) + p.get("q", [])
        result["keyword"] = ("EXPECTED" if words == ["HDD"]
                             else "MISSING" if not words else "OTHER")
        area = p.get("in", [])
        result["region"] = ("MISSING" if not area
                            else "EXPECTED" if area == [region["slug"]]
                            else "OTHER")
        if len(area) > 1:
            result["region"] = "INVALID"
    except (ValueError, TypeError, AttributeError):
        pass
    return result


def _region_state(obj, region: dict) -> dict:
    """Fresh response-region metadata is diagnostic, NEVER admission proof."""
    ids = obj.get("searchRegion") if isinstance(obj.get("searchRegion"), dict) else {}
    filters = obj.get("currentFilters") if isinstance(obj.get("currentFilters"), dict) else {}
    expected = str(region["id"])
    def match(value):
        return "MISSING" if value is None else ("EXPECTED" if str(value) == expected else "OTHER")
    return {"server_region": match(ids.get("id")),
            "filter_region": match(filters.get("regionId"))}


def classify_surface_body(raw: bytes, content_type: str, region: dict) -> dict:
    """Extract only shape and bounded count; discard titles/URLs/IDs immediately."""
    unknown = {"shape": "UNRECOGNIZED", "article_count": 0,
               "server_region": "MISSING", "filter_region": "MISSING"}
    if type(raw) is not bytes or len(raw) > BODY_LIMIT:
        return {**unknown, "shape": "BODY_LIMIT"}
    if "json" in content_type.lower():
        if len(raw) > DATA_LIMIT:
            return {**unknown, "shape": "BODY_LIMIT"}
        try:
            doc = json.loads(raw)
        except (UnicodeError, ValueError, TypeError):
            return unknown
        if not isinstance(doc, dict):
            return unknown
        choices = [doc]
        for name in ("allPage", "data", "search", "result"):
            value = doc.get(name)
            if isinstance(value, dict):
                choices.append(value)
        for obj in choices:
            for key, shape in (("buySellArticles", "MODERN_ROUTE"),
                               ("fleamarketArticles", "FLEAMARKET_API")):
                items = obj.get(key)
                if isinstance(items, list):
                    if len(items) > COUNT_LIMIT:
                        return {**unknown, "shape": "BODY_LIMIT"}
                    return {"shape": shape, "article_count": len(items),
                            **_region_state(obj, region)}
        return unknown
    if "html" in content_type.lower() or raw.lstrip().startswith(b"<!"):
        # Only an aggregate presence signal, not article identities.
        text = raw.decode("utf-8", "replace")
        if "captcha" in text[:12000].lower() or "verify you are human" in text[:12000].lower():
            return {**unknown, "shape": "CHALLENGE"}
        itemlist = bool(re.search(r'"@type"\s*:\s*"ItemList"', text))
        return {**unknown, "shape": "SSR_ITEMLIST" if itemlist else "HTML_NO_ITEMLIST"}
    return unknown


def sanitize_surface_probe(value) -> dict:
    """Revalidate ALL fields before leaving trusted capture memory."""
    obj = value if type(value) is dict else {}
    states = {"ROBOTS_UNAVAILABLE", "CHECKED", "NOT_ATTEMPTED"}
    statuses = {"NOT_RUN", "ROBOTS_DENIED", "HTTP_OK", "HTTP_NON_200",
                "ACCESS_BLOCKED", "REQUEST_ERROR", "BODY_ERROR"}
    shapes = {"UNRECOGNIZED", "BODY_LIMIT", "MODERN_ROUTE", "FLEAMARKET_API",
              "CHALLENGE", "SSR_ITEMLIST", "HTML_NO_ITEMLIST"}
    result = {"robots": obj.get("robots") if obj.get("robots") in states else "NOT_ATTEMPTED",
              "blocked": obj.get("blocked") is True,
              "authorization": False,
              "surfaces": {}}
    src = obj.get("surfaces") if type(obj.get("surfaces")) is dict else {}
    for surface in SURFACES:
        row = src.get(surface)
        row = row if type(row) is dict else {}
        out = {"status": row.get("status") if row.get("status") in statuses else "NOT_RUN",
               "shape": row.get("shape") if row.get("shape") in shapes else "UNRECOGNIZED"}
        for key in ("server_region", "filter_region"):
            out[key] = row.get(key) if row.get(key) in ("EXPECTED", "OTHER", "MISSING") else "MISSING"
        for key in ("host", "path"):
            out[key] = row.get(key) if row.get(key) in ("EXPECTED", "OTHER") else "OTHER"
        for key in ("region", "keyword"):
            allowed = ("EXPECTED", "OTHER", "MISSING", "INVALID") if key == "region" else ("EXPECTED", "OTHER", "MISSING")
            out[key] = row.get(key) if row.get(key) in allowed else "MISSING"
        for key in ("article_count", "api_emitted"):
            val = row.get(key)
            out[key] = val if type(val) is int and 0 <= val <= COUNT_LIMIT else 0
        result["surfaces"][surface] = out
    return result


async def run_surface_probe(browser, region: dict, *, timeout_ms: int = 16000,
                            settle_ms: int = 900, checker=check_surface_robots) -> dict:
    """One bounded, robots-first diagnostic on first Cheonan failure only.

    Each surface starts from a clean guest browser context. GET and passive
    responses only; no scrolling, login, retries, detail pages or exports.
    """
    outcome = {"robots": "NOT_ATTEMPTED", "blocked": False,
               "authorization": False, "surfaces": {}}
    try:
        decision = await asyncio.to_thread(checker, region)
        outcome["robots"] = decision.get("state", "ROBOTS_UNAVAILABLE")
        allowed = decision.get("allowed") if type(decision) is dict else {}
        allowed = allowed if type(allowed) is dict else {}
    except Exception:
        allowed = {}
        outcome["robots"] = "ROBOTS_UNAVAILABLE"
    for name in SURFACES:
        if outcome["blocked"]:
            break
        if allowed.get(name) is not True:
            outcome["surfaces"][name] = {"status": "ROBOTS_DENIED"}
            continue
        context = None
        try:
            context = await browser.new_context(locale="ko-KR")
            page = await context.new_page()
            observed = []
            tasks = set()
            blocked = [False]
            def on_response(response):
                try:
                    u = urlsplit(response.url)
                    if (u.scheme != "https" or u.hostname != "www.daangn.com"
                            or u.path != "/kr/api/v1/fleamarket/search"
                            or response.request.resource_type not in ("fetch", "xhr")):
                        return
                    if response.status in BLOCK_STATUS:
                        blocked[0] = True
                        return
                    if response.status != 200 or len(tasks) + len(observed) >= 2:
                        return
                    async def read_api():
                        try:
                            body = await asyncio.wait_for(response.body(), timeout=8)
                            value = classify_surface_body(body, response.headers.get("content-type", ""),
                                                          region)
                            observed.append(value)
                        except Exception:
                            pass
                    task = asyncio.create_task(read_api())
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
                except Exception:
                    pass
            page.on("response", on_response)
            response = await page.goto(surface_url(name, region), wait_until="domcontentloaded",
                                       timeout=timeout_ms)
            if response is None:
                outcome["surfaces"][name] = {"status": "REQUEST_ERROR"}
                continue
            url_flags = classify_final_url(page.url, name, region)
            if response.status in BLOCK_STATUS:
                outcome["blocked"] = True
                outcome["surfaces"][name] = {"status": "ACCESS_BLOCKED", **url_flags}
                continue
            if response.status != 200:
                outcome["surfaces"][name] = {"status": "HTTP_NON_200", **url_flags}
                continue
            try:
                body = await asyncio.wait_for(response.body(), timeout=10)
                detail = classify_surface_body(body, response.headers.get("content-type", ""),
                                               region)
                if detail["shape"] == "CHALLENGE":
                    outcome["blocked"] = True
                await page.wait_for_timeout(settle_ms)
                if tasks:
                    await asyncio.wait_for(asyncio.gather(*list(tasks), return_exceptions=True),
                                           timeout=9)
                if blocked[0]:
                    outcome["blocked"] = True
                api_count = sum(x.get("article_count", 0) for x in observed[:2])
                outcome["surfaces"][name] = {
                    **url_flags, **detail,
                    "api_emitted": min(api_count, COUNT_LIMIT),
                    "status": "ACCESS_BLOCKED" if outcome["blocked"] else "HTTP_OK",
                }
            except Exception:
                outcome["surfaces"][name] = {"status": "BODY_ERROR", **url_flags}
        except Exception:
            outcome["surfaces"][name] = {"status": "REQUEST_ERROR"}
        finally:
            if context is not None:
                await context.close()
    return sanitize_surface_probe(outcome)
