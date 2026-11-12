# -*- coding: utf-8 -*-
"""OCI FILL-only precollection filter gate: control/Route metadata, NOT listings.

One first-party UI Apply after already validated target locality. Reads only
known server filter fields from the browser-observed Route, never projects,
persists, exports or iterates buySellArticles. No listing/detail navigation.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import daangn_v4_1_core as core
import daangn_browser_v4_6 as v46

REGION = core.BY_KEY["cheonan"]
CATEGORY_ID = 1
MAX_PRICE = 50000
KEYWORD = "HDD"
_CATS = ("categoryId", "category_id", "categoryIds")
_PRICES = ("maxPrice", "max_price", "priceMax", "priceTo", "price_to", "maximumPrice")
_AVAILABLE = ("onlyOnSale", "only_on_sale", "onlyAvailable", "availableOnly")
_ITEM_STATUS = ("EXPECTED", "MISSING", "OTHER", "AMBIGUOUS")
_REPORT_STATUS = (
    "BLOCKED_PRECONDITION", "BLOCKED_FILTER_CONTROL",
    "BLOCKED_APPLY_ACTION", "BLOCKED_ACCESS_RESTRICTED",
    "BLOCKED_FILTER_ROUTE_MISSING", "BLOCKED_FILTER_ROUTE_AMBIGUOUS",
    "BLOCKED_FILTER_ROUTE_METADATA", "BLOCKED_FILTER_URL",
    "BLOCKED_UI_RECHECK", "PRECOLLECTION_READY_REVIEW",
)
_MAX_BODY = 2_000_000
_URL_FIELDS = ("keyword", "region", "category", "price_max", "available")
_URL_FIELD_STATES = ("EXPECTED", "MISSING", "OTHER", "DUPLICATE", "UNOBSERVABLE")
_URL_SHAPES = ("FIRST_PARTY_SEARCH", "OTHER_PATH_OR_ORIGIN", "UNOBSERVABLE")
_UI_RECHECK_STATES = (
    "NOT_RUN", "OBSERVED_MATCH", "OBSERVED_MISMATCH",
    "PARTIAL_OBSERVATION", "NOT_OBSERVABLE",
)
_TRANSPORT_COUNTS = (
    "search_requests", "search_fetch_requests", "search_document_requests",
    "search_other_method_requests", "search_exact_query_requests",
    "search_different_query_requests", "search_responses",
    "search_response_200", "search_response_restricted",
    "search_response_other", "search_request_failures",
)
_DEFAULT_FILTER_FIELDS = {key: "MISSING" for key in
                          ("region", "category", "price_max", "available")}


def _same_public_search_path(url):
    try:
        u = urlsplit(url)
        return (
            u.scheme == "https" and u.hostname == "www.daangn.com"
            and u.port is None and u.path == core.SEARCH_PATH
        )
    except (ValueError, AttributeError, TypeError):
        return False


def classify_filter_url(url, expected_region=REGION):
    """Only finite comparisons; never emit a raw URL/key/value or query."""
    result = {
        "shape": "UNOBSERVABLE", "unexpected_keys": -1,
        "fields": {name: "UNOBSERVABLE" for name in _URL_FIELDS},
    }
    if type(url) is not str or len(url) > 4096:
        return result
    result["shape"] = (
        "FIRST_PARTY_SEARCH" if _same_public_search_path(url)
        else "OTHER_PATH_OR_ORIGIN"
    )
    if result["shape"] != "FIRST_PARTY_SEARCH":
        return result
    try:
        params = parse_qs(urlsplit(url).query, keep_blank_values=True)
    except (ValueError, AttributeError, TypeError):
        result["shape"] = "UNOBSERVABLE"
        return result
    expected = {
        "keyword": ("q", KEYWORD),
        "region": ("in", expected_region["slug"]),
        "category": ("category_id", str(CATEGORY_ID)),
        "price_max": ("price", "__" + str(MAX_PRICE)),
        "available": ("only_on_sale", "true"),
    }
    known = {p for p, _ in expected.values()}
    result["unexpected_keys"] = min(20, sum(k not in known for k in params))
    for label, (key, value) in expected.items():
        choices = params.get(key)
        result["fields"][label] = (
            "MISSING" if choices is None else
            "DUPLICATE" if len(choices) != 1 else
            "EXPECTED" if choices[0] == value else "OTHER"
        )
    return result


def sanitize_filter_url_diagnostic(raw):
    src = raw if type(raw) is dict else {}
    f = src.get("fields") if type(src.get("fields")) is dict else {}
    return {
        "shape": _kind(src.get("shape"), _URL_SHAPES, "UNOBSERVABLE"),
        "unexpected_keys": _bounded(src.get("unexpected_keys")),
        "fields": {
            k: _kind(f.get(k), _URL_FIELD_STATES, "UNOBSERVABLE")
            for k in _URL_FIELDS
        },
    }


def sanitize_filter_transport_diagnostic(raw):
    src = raw if type(raw) is dict else {}
    return {k: _bounded(src.get(k)) for k in _TRANSPORT_COUNTS}




def _kind(value, allowed, default):
    return value if type(value) is str and value in allowed else default


def _bounded(value):
    return value if type(value) is int and 0 <= value <= 20 else -1


def sanitize_precollection(value):
    src = value if type(value) is dict else {}
    states = src.get("server_filters")
    states = states if type(states) is dict else {}
    return {
        "schema": "oci_fill_precollection_v1",
        "status": _kind(src.get("status"), _REPORT_STATUS, "BLOCKED_PRECONDITION"),
        "region_gate_confirmed": src.get("region_gate_confirmed") is True,
        "fill_only": True,
        "requested_keyword": "HDD",
        "requested_region": "CHEONAN_BULDANG",
        "requested_category": "DIGITAL_DEVICES",
        "requested_max_price_krw": MAX_PRICE,
        "requested_available_only": True,
        "ui_selected_before_apply": src.get("ui_selected_before_apply") is True,
        "ui_selected_after_apply": src.get("ui_selected_after_apply") is True,
        "filter_apply_returned": src.get("filter_apply_returned") is True,
        "filtered_url_matches": src.get("filtered_url_matches") is True,
        "filtered_url_diagnostics": sanitize_filter_url_diagnostic(
            src.get("filtered_url_diagnostics")),
        "filter_transport_diagnostics": sanitize_filter_transport_diagnostic(
            src.get("filter_transport_diagnostics")),
        "ui_after_apply_recheck_state": _kind(
            src.get("ui_after_apply_recheck_state"),
            _UI_RECHECK_STATES, "NOT_RUN"),
        "filtered_route_count": _bounded(src.get("filtered_route_count")),
        "server_filters": {
            k: _kind(states.get(k), _ITEM_STATUS, "MISSING")
            for k in ("region", "category", "price_max", "available")
        },
        "strict_filter_evidence": src.get("strict_filter_evidence") is True,
        "collection_started": False,
        "listing_detail_visited": False,
        "listing_fields_read_or_exported": False,
        "database_written": False,
        "authorizes_listings": False,
    }


def _unique_query(url, expected_region=REGION):
    try:
        u = urlsplit(url)
        if not _same_public_search_path(url):
            return False
        q = parse_qs(u.query, keep_blank_values=True)
        if any(k not in {"q", "in", "category_id", "price",
                         "only_on_sale"} for k in q):
            return False
        return all(q.get(k) == [val] for k, val in (
            ("q", KEYWORD), ("in", expected_region["slug"]),
            ("category_id", str(CATEGORY_ID)), ("price", "__" + str(MAX_PRICE)),
            ("only_on_sale", "true"),
        ))
    except (ValueError, TypeError, AttributeError):
        return False


def _value_state(fields, names, expected, *, as_int=False, as_bool=False):
    present = [fields[k] for k in names if k in fields]
    if not present:
        return "MISSING"
    if len(present) != 1:
        return "AMBIGUOUS"
    val = present[0]
    if as_bool:
        matched = val is True or (type(val) is int and val == 1) or (
            type(val) is str and val.lower() == "true")
    elif as_int:
        matched = (type(val) is int and val == expected
                   or type(val) is str and val == str(expected))
    else:
        matched = str(val) == str(expected)
    return "EXPECTED" if matched else "OTHER"


def _find_search_model(blob):
    """Bounded traversal; NEVER recurse into article/listing arrays."""
    if not isinstance(blob, (bytes, bytearray)) or len(blob) > _MAX_BODY:
        return None
    try:
        value = json.loads(blob)
    except (UnicodeError, ValueError, TypeError):
        return None
    matches = []
    visited = 0

    def walk(x, depth=0):
        nonlocal visited
        visited += 1
        if visited > 400 or depth > 7 or len(matches) > 1:
            return
        if type(x) is dict:
            if (isinstance(x.get("buySellArticles"), list)
                    and isinstance(x.get("currentFilters"), dict)
                    and isinstance(x.get("searchRegion"), dict)):
                matches.append((x["searchRegion"], x["currentFilters"]))
            for k, v in x.items():
                if k in ("buySellArticles", "articles", "listings", "items"):
                    continue
                if type(v) in (dict, list):
                    walk(v, depth + 1)
        elif type(x) is list:
            for v in x[:30]:
                if type(v) in (dict, list):
                    walk(v, depth + 1)

    walk(value)
    return matches[0] if len(matches) == 1 else None


def inspect_filtered_response(blob):
    pair = _find_search_model(blob)
    if pair is None:
        return {k: "MISSING" for k in (
            "region", "category", "price_max", "available")}
    search, filters = pair
    region_a = _value_state(search, ("id",), int(REGION["id"]), as_int=True)
    region_b = _value_state(filters, ("regionId",), int(REGION["id"]), as_int=True)
    region_state = (
        "EXPECTED" if region_a == region_b == "EXPECTED"
        else "OTHER" if "OTHER" in (region_a, region_b)
        else "AMBIGUOUS" if "AMBIGUOUS" in (region_a, region_b)
        else "MISSING")
    return {
        "region": region_state,
        "category": _value_state(filters, _CATS, CATEGORY_ID, as_int=True),
        "price_max": _value_state(filters, _PRICES, MAX_PRICE, as_int=True),
        "available": _value_state(filters, _AVAILABLE, True, as_bool=True),
    }


class PassiveFilteredRoute:
    """Only browser-generated first-party filtered Route responses, no fetch."""
    def __init__(self):
        self.events = []
        self.tasks = set()
        self.restricted = False
        self.observed = 0
        self.starts = set()
        self.broad_starts = set()
        self.diagnostics = {key: 0 for key in _TRANSPORT_COUNTS}

    def _increase(self, key):
        self.diagnostics[key] = min(20, self.diagnostics[key] + 1)

    def on_request(self, request):
        try:
            if (not _same_public_search_path(request.url)
                    or request.resource_type not in ("fetch", "xhr", "document")):
                return
            self._increase("search_requests")
            if request.resource_type in ("fetch", "xhr"):
                self._increase("search_fetch_requests")
            else:
                self._increase("search_document_requests")
            if request.method != "GET":
                self._increase("search_other_method_requests")
            if _unique_query(request.url):
                self._increase("search_exact_query_requests")
                if (request.method == "GET"
                        and request.resource_type in ("fetch", "xhr")
                        and len(self.starts) < 4):
                    self.starts.add(request)
            else:
                self._increase("search_different_query_requests")
            if len(self.broad_starts) < 20:
                self.broad_starts.add(request)
        except (AttributeError, TypeError, ValueError):
            return

    def on_requestfailed(self, request):
        try:
            if request in self.broad_starts:
                self.broad_starts.discard(request)
                self.starts.discard(request)
                self._increase("search_request_failures")
        except (AttributeError, TypeError, ValueError):
            return

    def on_response(self, response):
        try:
            req = response.request
            if req not in self.broad_starts:
                return
            self.broad_starts.discard(req)
            self._increase("search_responses")
            if response.status in (401, 403, 429):
                self._increase("search_response_restricted")
                self.restricted = True
            elif response.status == 200:
                self._increase("search_response_200")
            else:
                self._increase("search_response_other")
            if req not in self.starts:
                return
            self.starts.discard(req)
            if (req.resource_type not in ("fetch", "xhr")
                    or req.method != "GET"
                    or not _unique_query(response.url)):
                return
            self.observed = min(20, self.observed + 1)
            if response.status != 200 or len(self.events) + len(self.tasks) >= 3:
                return
            ctype = response.headers.get("content-type", "").lower()
            if "json" not in ctype and "remix" not in ctype:
                return
            size = response.headers.get("content-length", "")
            if size.isdecimal() and int(size) > _MAX_BODY:
                return

            async def read_metadata_only():
                try:
                    body = await asyncio.wait_for(response.body(), timeout=8)
                    # Blob remains in task RAM until returned, never on disk.
                    self.events.append(inspect_filtered_response(body))
                except Exception:
                    self.events.append({k: "MISSING" for k in (
                        "region", "category", "price_max", "available")})
            task = asyncio.create_task(read_metadata_only())
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        except (AttributeError, TypeError, ValueError):
            return

    async def drain(self):
        if self.tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*list(self.tasks), return_exceptions=True),
                    timeout=9)
            except asyncio.TimeoutError:
                pass


async def verify_filter_before_collection(page, region=REGION):
    """Only run on *already confirmed* same-page FILL locality.

    Public UI filter Apply is allowed; all listing/detail collection is blocked.
    Any missing source metadata means READY is denied, even when the URL looks
    correctly filtered. No use of the production keyring or database.
    """
    info = {
        "region_gate_confirmed": True, "status": "BLOCKED_PRECONDITION",
        "server_filters": {}, "filtered_route_count": 0,
        "ui_after_apply_recheck_state": "NOT_RUN",
    }
    if (region is not REGION and region != REGION) or not page.url.startswith(
            "https://www.daangn.com/kr/search/buy-sell/"):
        return sanitize_precollection(info)
    args = SimpleNamespace(
        category_name="디지털기기", category_id=CATEGORY_ID,
        available_only=True, max_price=MAX_PRICE, min_price=0)
    watcher = PassiveFilteredRoute()
    try:
        button, selected = await v46.set_filter(page, args, [])
        info["ui_selected_before_apply"] = v46.ui_ok(selected, args)
        if not info["ui_selected_before_apply"]:
            info["status"] = "BLOCKED_FILTER_CONTROL"
            return sanitize_precollection(info)
        if not await button.is_enabled():
            info["status"] = "BLOCKED_FILTER_CONTROL"
            return sanitize_precollection(info)
        page.on("request", watcher.on_request)
        page.on("response", watcher.on_response)
        page.on("requestfailed", watcher.on_requestfailed)
        try:
            await button.click(timeout=6000)
            info["filter_apply_returned"] = True
            await page.wait_for_timeout(1800)
            await watcher.drain()
        finally:
            page.remove_listener("request", watcher.on_request)
            page.remove_listener("response", watcher.on_response)
            page.remove_listener("requestfailed", watcher.on_requestfailed)
        info["filtered_route_count"] = watcher.observed
        info["filter_transport_diagnostics"] = watcher.diagnostics.copy()
        info["filtered_url_diagnostics"] = classify_filter_url(page.url, region)
        if watcher.restricted:
            info["status"] = "BLOCKED_ACCESS_RESTRICTED"
            return sanitize_precollection(info)
        info["filtered_url_matches"] = _unique_query(page.url, region)
        if not info["filtered_url_matches"]:
            info["status"] = "BLOCKED_FILTER_URL"
            return sanitize_precollection(info)
        after = await v46.check_after(page, args)
        info["ui_after_apply_recheck_state"] = _kind(
            after.get("observation_status"), _UI_RECHECK_STATES,
            "NOT_OBSERVABLE")
        info["ui_selected_after_apply"] = (
            after.get("observation_status") == "OBSERVED_MATCH"
            and v46.ui_ok(after, args))
        if not info["ui_selected_after_apply"]:
            info["status"] = "BLOCKED_UI_RECHECK"
            return sanitize_precollection(info)
        if len(watcher.events) == 0:
            info["status"] = "BLOCKED_FILTER_ROUTE_MISSING"
            return sanitize_precollection(info)
        if len(watcher.events) != 1 or watcher.observed != 1:
            info["status"] = "BLOCKED_FILTER_ROUTE_AMBIGUOUS"
            return sanitize_precollection(info)
        info["server_filters"] = watcher.events[0]
        info["strict_filter_evidence"] = all(
            info["server_filters"].get(k) == "EXPECTED"
            for k in ("region", "category", "price_max", "available"))
        info["status"] = (
            "PRECOLLECTION_READY_REVIEW" if info["strict_filter_evidence"]
            else "BLOCKED_FILTER_ROUTE_METADATA")
    except Exception:
        info["status"] = "BLOCKED_APPLY_ACTION" if (
            info.get("ui_selected_before_apply")) else "BLOCKED_FILTER_CONTROL"
    return sanitize_precollection(info)
