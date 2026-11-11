# -*- coding: utf-8 -*-
"""Owner-operated, normal-Chrome locality comparison (observation only).

Chrome is launched by the CLI, never by Playwright. No profile reuse, login,
DOM modification, synthetic clicks, HAR or raw listing material. Captured
first-party response bodies exist in RAM only and are immediately reduced to
fixed enumerations. This evidence cannot authorize listings or OCI imports.
"""
from __future__ import annotations

import asyncio
import json
from time import time
from urllib.parse import parse_qs, urlsplit

import daangn_v4_1_core as core
from app_v5.region_lifecycle import _JS as LIFECYCLE_JS, _safe_checkpoint
from app_v5.region_navigation import classify_browser_url
from app_v5.region_suggestion import RegionSuggestionObserver, classify_suggestion_identity

SEARCH_URL = "https://www.daangn.com/kr/search/buy-sell/?q=HDD"
_MAX_ROUTE_BYTES = 2_000_000
_MAX_EVENTS = 12
_SAMPLES = ("BEFORE", "AT_CLICK", "AFTER_200MS",
            "AFTER_800MS", "AFTER_2000MS", "AFTER_4000MS")
_RUN_STATUS = frozenset((
    "MANUAL_CLICK_OBSERVED", "NO_TARGET_CLICK", "MULTIPLE_TARGET_CLICKS",
    "UNTRUSTED_CLICK", "UNEXPECTED_PAGE", "BROWSER_DISCONNECTED",
    "ACCESS_BLOCKED", "OBSERVATION_ERROR",
))
_ROUTE_STATUS = frozenset((
    "NO_POSTCLICK_ROUTE", "UNIQUE_POSTCLICK_ROUTE", "MULTIPLE_POSTCLICK_ROUTES",
    "ROUTE_UNREADABLE", "ACCESS_BLOCKED",
))
_COMPARISONS = frozenset((
    "UI_AND_ROUTE_EXPECTED_DIAGNOSTIC",
    "UI_AND_ROUTE_OTHER", "UI_ROUTE_DISAGREE",
    "INCONCLUSIVE",
))
_REGION_VALUES = frozenset(("EXPECTED", "OTHER", "MISSING", "INVALID"))
_ID_VALUES = frozenset(("EXPECTED", "OTHER", "MISSING"))
_NAME_VALUES = frozenset(("EXACT", "CONTAINS", "OTHER", "MISSING"))
_API_STATES = frozenset((
    "NO_RESOLVER_RESPONSE", "AMBIGUOUS_RESOLVER_RESPONSES",
    "RESOLVER_SCHEMA_UNKNOWN", "NO_EXACT_CITY_TERM_MATCH",
    "AMBIGUOUS_CITY_TERM_MATCH", "POST_CLICK_SEARCH_NOT_UNIQUE",
    "UNIQUE_API_CANDIDATE_CORRELATED",
))
_CLICK_JS = r"""meta => {
  const key=Symbol.for('auto_daangn_manual_chrome_v1');
  try { document[key]?.stop?.(); } catch (_) {}
  const state={count:0,trusted:0,unique:false,city:false,at_ms:0};
  const visible=e=>{
    if(!e?.isConnected)return false;
    try {
      const style=getComputedStyle(e);
      return !!e.getClientRects().length && style.display!=='none' &&
             style.visibility!=='hidden';
    } catch(_){ return false; }
  };
  const onClick=e=>{
    const el=e.target?.closest?.('button,[role="button"],[role="option"]');
    const dialog=el?.closest?.('[role="dialog"]');
    if(!dialog || !visible(el))return;
    const name=(el.textContent||'').replace(/\s+/g,' ').trim().slice(0,200);
    if(!name.includes(meta.term))return;
    const matches=[...dialog.querySelectorAll('button,[role="button"],[role="option"]')]
      .filter(x=>visible(x) && (x.textContent||'').includes(meta.term));
    state.count=Math.min(10,state.count+1);
    if(e.isTrusted)state.trusted=Math.min(10,state.trusted+1);
    if(state.count===1){
      state.unique=matches.length===1 && matches[0]===el;
      state.city=name.includes(meta.city);
      state.at_ms=Date.now();
    }
  };
  document.addEventListener('click',onClick,{capture:true,passive:true});
  document[key]={
    get(){return {...state};},
    stop(){document.removeEventListener('click',onClick,true);
           delete document[key];}
  };
  return true;
}"""
_READ_CLICK_JS = r"""() => {
  const key=Symbol.for('auto_daangn_manual_chrome_v1');
  return document[key]?.get?.() || null;
}"""
_STOP_CLICK_JS = r"""() => {
  const key=Symbol.for('auto_daangn_manual_chrome_v1');
  try{document[key]?.stop?.();}catch(_){}
  return true;
}"""


def is_public_search(url: str) -> bool:
    """Exact https host/path/query only, no custom target or offsite tracking."""
    try:
        p = urlsplit(url)
        qs = parse_qs(p.query)
        return (p.scheme == "https" and p.hostname == "www.daangn.com"
                and p.port is None and p.path == core.SEARCH_PATH
                and qs.get("q") == ["HDD"])
    except (TypeError, ValueError, AttributeError):
        return False


def _region_id(raw, expected) -> str:
    return ("MISSING" if raw is None else
            "EXPECTED" if str(raw) == str(expected) else "OTHER")


def extract_route_summary(body: bytes, region: dict) -> dict | None:
    """Examine the known Route schema, NEVER project product/listing fields."""
    if not isinstance(body, bytes) or len(body) > _MAX_ROUTE_BYTES:
        return None
    try:
        data = json.loads(body)
    except (UnicodeError, ValueError, TypeError):
        return None
    candidates = []
    scanned = 0

    def walk(item, depth=0):
        nonlocal scanned
        scanned += 1
        if scanned > 450 or depth > 7:
            return
        if isinstance(item, dict):
            if (isinstance(item.get("buySellArticles"), list)
                    and (isinstance(item.get("searchRegion"), dict)
                         or isinstance(item.get("currentFilters"), dict))):
                candidates.append(item)
            for k, value in item.items():
                # Listing arrays are deliberately never traversed or extracted.
                if k in ("buySellArticles", "articles", "listings", "items"):
                    continue
                if isinstance(value, (dict, list)):
                    walk(value, depth + 1)
        elif isinstance(item, list):
            for value in item[:30]:
                walk(value, depth + 1)

    walk(data)
    if len(candidates) != 1:
        return None
    model = candidates[0]
    search = model.get("searchRegion")
    filters = model.get("currentFilters")
    search = search if isinstance(search, dict) else {}
    filters = filters if isinstance(filters, dict) else {}
    name = search.get("name")
    term = region["term"]
    name_state = ("MISSING" if not isinstance(name, str) or not name.strip()
                  else "EXACT" if name.strip() == term
                  else "CONTAINS" if term in name else "OTHER")
    sid = search.get("id")
    fid = filters.get("regionId")
    return {
        "search_region": _region_id(sid, region["id"]),
        "filter_region": _region_id(fid, region["id"]),
        "name_state": name_state,
        "ids_agree": (
            "MISSING" if sid is None or fid is None else
            "YES" if str(sid) == str(fid) else "NO"),
    }


class ManualSearchResponses:
    """Watch only existing browser requests; no route or fetch injection."""

    def __init__(self, region):
        self.region = region
        self.starts = {}
        self.events = []
        self.tasks = set()
        self.blocked = False
        self.skipped = 0

    @staticmethod
    def _target(url):
        try:
            p = urlsplit(url)
            return (p.scheme == "https" and p.hostname == "www.daangn.com"
                    and p.port is None and p.path == core.SEARCH_PATH
                    and parse_qs(p.query).get("q") == ["HDD"])
        except (ValueError, AttributeError, TypeError):
            return False

    def on_request(self, request):
        try:
            if (self._target(request.url)
                    and request.resource_type in ("xhr", "fetch")
                    and request.method == "GET" and len(self.starts) < 24):
                self.starts[request] = int(time() * 1000)
        except (TypeError, AttributeError, ValueError):
            pass

    def on_response(self, response):
        try:
            request = response.request
            # Never trust an unobserved request as a post-click request.
            started = self.starts.pop(request, None)
            if started is None:
                return
            if response.status in core.BLOCK_STATUS:
                self.blocked = True
                return
            if len(self.events) + len(self.tasks) >= _MAX_EVENTS:
                self.skipped += 1
                return
            ct = str(response.headers.get("content-type", "")).lower()
            length = response.headers.get("content-length", "")
            if (response.status != 200 or
                    not ("json" in ct or "remix" in ct)):
                return
            if length.isdigit() and int(length) > _MAX_ROUTE_BYTES:
                self.skipped += 1
                return
            req_region = classify_browser_url(response.url, self.region)["region"]

            async def receive():
                state = "ROUTE_UNREADABLE"
                model = None
                try:
                    body = await asyncio.wait_for(response.body(), timeout=8)
                    model = extract_route_summary(body, self.region)
                    if model is not None:
                        state = "OBSERVED"
                except Exception:
                    pass
                self.events.append({
                    "started_ms": started, "state": state,
                    "request_region": req_region,
                    "model": model,
                })

            task = asyncio.create_task(receive())
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        except (ValueError, TypeError, AttributeError):
            return

    async def drain(self):
        if self.tasks:
            try:
                await asyncio.wait_for(asyncio.gather(
                    *list(self.tasks), return_exceptions=True), timeout=9)
            except asyncio.TimeoutError:
                pass

    def after_click(self, click_epoch_ms: int):
        # A response from a request started before a human click is NOT
        # attributable to that click even if its body arrived afterward.
        return [e for e in self.events if type(e.get("started_ms")) is int
                and e["started_ms"] >= click_epoch_ms]


def _enum(value, options, default):
    return value if type(value) is str and value in options else default


def _count(value, maximum=20):
    return value if type(value) is int and 0 <= value <= maximum else -1


def sanitize_manual_report(value) -> dict:
    """Strict allowlist for stdout and optional local JSON; idempotent."""
    src = value if type(value) is dict else {}
    click = src.get("manual_click") if type(src.get("manual_click")) is dict else {}
    api = src.get("region_api") if type(src.get("region_api")) is dict else {}
    route = src.get("route") if type(src.get("route")) is dict else {}
    stages = src.get("stages") if type(src.get("stages")) is dict else {}
    safe = {
        "schema": "manual_chrome_region_v1",
        "status": _enum(src.get("status"), _RUN_STATUS, "OBSERVATION_ERROR"),
        "manual_click": {
            "count": _count(click.get("count"), 10),
            "trusted_count": _count(click.get("trusted_count"), 10),
            "unique_candidate": click.get("unique_candidate") is True,
            "city_hint": click.get("city_hint") is True,
        },
        "region_api": {
            "response_count": _count(api.get("response_count")),
            "state": _enum(api.get("state"), _API_STATES,
                           "NO_RESOLVER_RESPONSE"),
            "preset_id_match": api.get("preset_id_match") is True,
            "exact_candidate_count": _count(api.get("exact_candidate_count"), 3),
        },
        "route": {
            "status": _enum(route.get("status"), _ROUTE_STATUS,
                            "NO_POSTCLICK_ROUTE"),
            "response_count": _count(route.get("response_count")),
            "search_region": _enum(route.get("search_region"),
                                   _ID_VALUES, "MISSING"),
            "filter_region": _enum(route.get("filter_region"),
                                   _ID_VALUES, "MISSING"),
            "name_state": _enum(route.get("name_state"),
                                _NAME_VALUES, "MISSING"),
            "ids_agree": _enum(route.get("ids_agree"),
                               frozenset(("YES", "NO", "MISSING")),
                               "MISSING"),
            "request_region": _enum(route.get("request_region"),
                                    _REGION_VALUES, "INVALID"),
        },
        "page_region": _enum(src.get("page_region"),
                             _REGION_VALUES, "INVALID"),
        "comparison": _enum(src.get("comparison"),
                             _COMPARISONS, "INCONCLUSIVE"),
        "stages": {
            stage: _safe_checkpoint(stages.get(stage))
            for stage in _SAMPLES
        },
        "authorizes_listings": False,
    }
    return safe


async def _read_click(page):
    try:
        x = await page.evaluate(_READ_CLICK_JS)
        return x if type(x) is dict else None
    except Exception:
        return None


async def _stage(page, region):
    try:
        return _safe_checkpoint(await page.evaluate(
            LIFECYCLE_JS, {"term": region["term"], "city": region["label"]}))
    except Exception:
        return _safe_checkpoint(None)


def make_manual_report(region, *, status, click, resolver, routes,
                       page_url, stages):
    """Pure, fail-closed comparison of already-observed manual browser data."""
    click = click if type(click) is dict else {}
    epoch = click.get("at_ms")
    after = routes.after_click(epoch) if type(epoch) is int and epoch > 0 else []
    route_status = ("ACCESS_BLOCKED" if routes.blocked else
                    "NO_POSTCLICK_ROUTE" if not after else
                    "MULTIPLE_POSTCLICK_ROUTES" if len(after) != 1 else
                    "UNIQUE_POSTCLICK_ROUTE" if after[0]["state"] == "OBSERVED"
                    else "ROUTE_UNREADABLE")
    picked = after[0] if len(after) == 1 and route_status == "UNIQUE_POSTCLICK_ROUTE" else {}
    model = picked.get("model") if type(picked.get("model")) is dict else {}
    api_matches = [x for item in resolver.events
                   for x in (item.get("matches", []) if type(item) is dict else [])]
    api_class = classify_suggestion_identity(
        region, resolver.events,
        [{"model": {"region_id": region["id"],
                    "filter_region_id": region["id"],
                    "search_region_name": region["term"]}}]
        if len(resolver.events) == 1 else [])
    safe_stages = {k: _safe_checkpoint(stages.get(k)) for k in _SAMPLES}
    final_ui = safe_stages["AFTER_4000MS"]["selected_control"]
    request_region = picked.get("request_region", "INVALID")
    actual_status = ("ACCESS_BLOCKED" if resolver.blocked or routes.blocked
                     else status)
    if (actual_status == "MANUAL_CLICK_OBSERVED"
            and click.get("count") == 1 and click.get("trusted") == 1
            and click.get("unique") is True
            and route_status == "UNIQUE_POSTCLICK_ROUTE"
            and model.get("search_region") == "EXPECTED"
            and model.get("filter_region") == "EXPECTED"
            and final_ui == "EXPECTED"):
        comparison = "UI_AND_ROUTE_EXPECTED_DIAGNOSTIC"
    elif (actual_status == "MANUAL_CLICK_OBSERVED"
          and route_status == "UNIQUE_POSTCLICK_ROUTE"
          and model.get("search_region") == "OTHER"
          and model.get("filter_region") == "OTHER"
          and final_ui == "OTHER"):
        comparison = "UI_AND_ROUTE_OTHER"
    elif (actual_status == "MANUAL_CLICK_OBSERVED"
          and route_status == "UNIQUE_POSTCLICK_ROUTE"
          and final_ui in ("EXPECTED", "OTHER")
          and model.get("search_region") in ("EXPECTED", "OTHER")
          and ((final_ui == "EXPECTED") !=
               (model.get("search_region") == "EXPECTED"))):
        comparison = "UI_ROUTE_DISAGREE"
    else:
        comparison = "INCONCLUSIVE"
    return sanitize_manual_report({
        "status": actual_status,
        "manual_click": {
            "count": click.get("count"), "trusted_count": click.get("trusted"),
            "unique_candidate": click.get("unique"),
            "city_hint": click.get("city"),
        },
        "region_api": {
            "response_count": resolver.responses,
            "state": api_class.get("state"),
            "preset_id_match": (len(api_matches) == 1 and
                                str(api_matches[0]) == str(region["id"])),
            "exact_candidate_count": len(api_matches),
        },
        "route": {
            "status": route_status, "response_count": len(after),
            "search_region": model.get("search_region"),
            "filter_region": model.get("filter_region"),
            "name_state": model.get("name_state"),
            "ids_agree": model.get("ids_agree"),
            "request_region": request_region,
        },
        "page_region": classify_browser_url(page_url, region)["region"],
        "comparison": comparison, "stages": safe_stages,
    })


async def observe_manual_page(page, region, *, timeout_sec=120):
    """Observe a user interaction only. NO Playwright click/fill/goto methods."""
    resolver = RegionSuggestionObserver(region)
    routes = ManualSearchResponses(region)
    stage = {}
    click = None
    status = "NO_TARGET_CLICK"
    page.on("request", routes.on_request)
    page.on("response", routes.on_response)
    page.on("response", resolver.on_response)
    try:
        armed = await page.evaluate(
            _CLICK_JS, {"term": region["term"], "city": region["label"]})
        if armed is not True:
            status = "OBSERVATION_ERROR"
        else:
            stage["BEFORE"] = await _stage(page, region)
            deadline = asyncio.get_running_loop().time() + timeout_sec
            while asyncio.get_running_loop().time() < deadline:
                if not is_public_search(page.url):
                    status = "UNEXPECTED_PAGE"
                    break
                if resolver.blocked or routes.blocked:
                    status = "ACCESS_BLOCKED"
                    break
                click = await _read_click(page)
                if click is None:
                    status = "BROWSER_DISCONNECTED"
                    break
                if click.get("count", 0) > 0:
                    status = ("MANUAL_CLICK_OBSERVED" if click.get("count") == 1
                              and click.get("trusted") == 1 else
                              "MULTIPLE_TARGET_CLICKS"
                              if click.get("count", 0) > 1 else "UNTRUSTED_CLICK")
                    stage["AT_CLICK"] = await _stage(page, region)
                    for name, delay in (
                        ("AFTER_200MS", .2), ("AFTER_800MS", .6),
                        ("AFTER_2000MS", 1.2), ("AFTER_4000MS", 2.0)
                    ):
                        await asyncio.sleep(delay)
                        new_click = await _read_click(page)
                        if new_click is None:
                            status = "BROWSER_DISCONNECTED"
                            break
                        click = new_click
                        if click.get("count", 0) > 1:
                            status = "MULTIPLE_TARGET_CLICKS"
                        stage[name] = await _stage(page, region)
                        if resolver.blocked or routes.blocked:
                            status = "ACCESS_BLOCKED"
                            break
                    break
                await asyncio.sleep(.2)
            if click is None:
                click = await _read_click(page)
        await resolver.drain()
        await routes.drain()
        return make_manual_report(
            region, status=status, click=click, resolver=resolver,
            routes=routes, page_url=page.url, stages=stage)
    finally:
        try:
            await page.evaluate(_STOP_CLICK_JS)
        except Exception:
            pass
        for name, cb in (("request", routes.on_request),
                         ("response", routes.on_response),
                         ("response", resolver.on_response)):
            try:
                page.remove_listener(name, cb)
            except Exception:
                pass
