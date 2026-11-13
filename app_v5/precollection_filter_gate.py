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
from app_v5.region_baseline_contrast import (
    read_region_header_volatile, classify_region_header_transition,
)
from app_v5.filter_apply_activation import (
    FilterApplyActivationWitness, sanitize_apply_activation,
)

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
_REQUEST_OBSERVATION_STATES = (
    "NOT_OBSERVED", "ONE_OBSERVED", "MULTIPLE_OBSERVED", "UNOBSERVABLE",
)
_REQUEST_TRANSPORT_STATES = ("FETCH_OR_XHR", "DOCUMENT", "UNOBSERVABLE")
_REQUEST_METHOD_STATES = ("GET", "OTHER", "UNOBSERVABLE")
_REQUEST_OUTCOME_STATES = (
    "NOT_OBSERVED", "HTTP_200", "ACCESS_RESTRICTED",
    "OTHER_HTTP", "REQUEST_FAILED",
)
_VERDICT_RELATIONS = ("SAME", "DIFFERENT", "UNOBSERVABLE")


def sanitize_apply_request_diagnostics(raw):
    """Finite field verdicts ONLY; never export a request URL or parameter."""
    src = raw if type(raw) is dict else {}
    relations = (src.get("field_verdict_relationship")
                 if type(src.get("field_verdict_relationship")) is dict else {})
    return {
        "observation": _kind(
            src.get("observation"), _REQUEST_OBSERVATION_STATES,
            "UNOBSERVABLE"),
        "transport": _kind(
            src.get("transport"), _REQUEST_TRANSPORT_STATES,
            "UNOBSERVABLE"),
        "method": _kind(
            src.get("method"), _REQUEST_METHOD_STATES, "UNOBSERVABLE"),
        "request_url": sanitize_filter_url_diagnostic(src.get("request_url")),
        "response_url": sanitize_filter_url_diagnostic(src.get("response_url")),
        "outcome": _kind(src.get("outcome"), _REQUEST_OUTCOME_STATES,
                         "NOT_OBSERVED"),
        # These compare classifications, NOT raw query values or exact URLs.
        "field_verdict_relationship": {
            key: _kind(relations.get(key), _VERDICT_RELATIONS, "UNOBSERVABLE")
            for key in _URL_FIELDS
        },
        "authorizes_listings": False,
    }


_REGIONLESS_ROUTE_STATUSES = (
    "NOT_OBSERVED", "ONE_PARSED", "ONE_UNREADABLE",
    "MULTIPLE_OBSERVED", "UNOBSERVABLE",
)
_HEADER_FAMILIES = (
    "TARGET", "CHEONAN_OTHER", "ASAN", "SEOUL", "OTHER", "UNOBSERVABLE",
)


def _exact_except_missing_region(url):
    """For passive diagnosis only; NEVER a substitute for _unique_query."""
    summary = classify_filter_url(url)
    return (
        summary["shape"] == "FIRST_PARTY_SEARCH"
        and summary["unexpected_keys"] == 0
        and summary["fields"]["region"] == "MISSING"
        and all(summary["fields"][field] == "EXPECTED"
                for field in ("keyword", "category", "price_max", "available"))
    )


def regionless_route_summary(observed, events):
    """Retain only 4 known field verdicts; no listing or raw URL data."""
    if observed == 0:
        return "NOT_OBSERVED", _DEFAULT_FILTER_FIELDS.copy()
    if observed != 1:
        return "MULTIPLE_OBSERVED", _DEFAULT_FILTER_FIELDS.copy()
    if len(events) != 1:
        return "ONE_UNREADABLE", _DEFAULT_FILTER_FIELDS.copy()
    safe = {
        k: _kind(events[0].get(k), _ITEM_STATUS, "MISSING")
        for k in ("region", "category", "price_max", "available")
    }
    return "ONE_PARSED", safe


_APPLY_STAGES = (
    "NOT_STARTED", "LOCATE_FILTER_CONTROLS", "FILTER_CONTROLS_READY",
    "BEFORE_APPLY_CLICK", "AFTER_APPLY_CLICK", "AFTER_APPLY_SETTLE",
    "AFTER_TRANSPORT_DRAIN", "BEFORE_UI_RECHECK", "AFTER_UI_RECHECK",
    "COMPLETE",
)
_APPLY_EXCEPTION_KINDS = ("NONE", "PLAYWRIGHT_TIMEOUT", "OTHER_EXCEPTION")


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
        "apply_action_stage": _kind(
            src.get("apply_action_stage"), _APPLY_STAGES, "NOT_STARTED"),
        "apply_action_exception_kind": _kind(
            src.get("apply_action_exception_kind"),
            _APPLY_EXCEPTION_KINDS, "NONE"),
        "apply_activation": sanitize_apply_activation(src.get("apply_activation")),
        "apply_request_listener_armed": src.get("apply_request_listener_armed") is True,
        "filtered_url_matches": src.get("filtered_url_matches") is True,
        "filtered_url_diagnostics": sanitize_filter_url_diagnostic(
            src.get("filtered_url_diagnostics")),
        "filter_transport_diagnostics": sanitize_filter_transport_diagnostic(
            src.get("filter_transport_diagnostics")),
        "apply_search_request_diagnostics": sanitize_apply_request_diagnostics(
            src.get("apply_search_request_diagnostics")),
        "ui_after_apply_recheck_state": _kind(
            src.get("ui_after_apply_recheck_state"),
            _UI_RECHECK_STATES, "NOT_RUN"),
        "filtered_route_count": _bounded(src.get("filtered_route_count")),
        # The regionless Route is deliberately NON-ADMITTING evidence.
        # Even four EXPECTED fields here cannot waive missing URL 'in'.
        "regionless_route_count": _bounded(src.get("regionless_route_count")),
        "regionless_route_status": _kind(
            src.get("regionless_route_status"),
            _REGIONLESS_ROUTE_STATUSES, "UNOBSERVABLE"),
        "regionless_server_filters": {
            k: _kind(
                (src.get("regionless_server_filters")
                 if type(src.get("regionless_server_filters")) is dict
                 else {}).get(k), _ITEM_STATUS, "MISSING")
            for k in ("region", "category", "price_max", "available")
        },
        "post_apply_region_header": _kind(
            src.get("post_apply_region_header"),
            _HEADER_FAMILIES, "UNOBSERVABLE"),
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
        self.regionless_starts = set()
        self.regionless_events = []
        self.regionless_observed = 0
        self.diagnostics = {key: 0 for key in _TRANSPORT_COUNTS}
        # Bound at 3 browser-generated request objects, never raw URLs or
        # response data in output, and never inspect nonmatching response body.
        self.request_verdicts = {}

    def _increase(self, key):
        self.diagnostics[key] = min(20, self.diagnostics[key] + 1)

    def on_request(self, request):
        try:
            if (not _same_public_search_path(request.url)
                    or request.resource_type not in ("fetch", "xhr", "document")):
                return
            self._increase("search_requests")
            if len(self.request_verdicts) < 3:
                self.request_verdicts[request] = {
                    "transport": (
                        "FETCH_OR_XHR" if request.resource_type in
                        ("fetch", "xhr") else "DOCUMENT"),
                    "method": "GET" if request.method == "GET" else "OTHER",
                    "request_url": classify_filter_url(request.url),
                    "response_url": None,
                    "outcome": "NOT_OBSERVED",
                }
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
                if (request.method == "GET"
                        and request.resource_type in ("fetch", "xhr")
                        and _exact_except_missing_region(request.url)
                        and len(self.regionless_starts) < 4):
                    self.regionless_starts.add(request)
            if len(self.broad_starts) < 20:
                self.broad_starts.add(request)
        except (AttributeError, TypeError, ValueError):
            return

    def on_requestfailed(self, request):
        try:
            if request in self.broad_starts:
                self.broad_starts.discard(request)
                self.starts.discard(request)
                self.regionless_starts.discard(request)
                self._increase("search_request_failures")
                if request in self.request_verdicts:
                    self.request_verdicts[request]["outcome"] = "REQUEST_FAILED"
        except (AttributeError, TypeError, ValueError):
            return

    def on_response(self, response):
        try:
            req = response.request
            if req not in self.broad_starts:
                return
            self.broad_starts.discard(req)
            self._increase("search_responses")
            if req in self.request_verdicts:
                entry = self.request_verdicts[req]
                entry["response_url"] = classify_filter_url(response.url)
                entry["outcome"] = (
                    "ACCESS_RESTRICTED" if response.status in (401, 403, 429)
                    else "HTTP_200" if response.status == 200
                    else "OTHER_HTTP")
            if response.status in (401, 403, 429):
                self._increase("search_response_restricted")
                self.restricted = True
            elif response.status == 200:
                self._increase("search_response_200")
            else:
                self._increase("search_response_other")

            # An exact 4-filter search with only 'in' absent is important
            # evidence, but NOT a valid locality/collection Route.
            if req in self.regionless_starts:
                self.regionless_starts.discard(req)
                self.regionless_observed = min(20, self.regionless_observed + 1)
                if (response.status == 200
                        and _exact_except_missing_region(response.url)
                        and len(self.regionless_events) + len(self.tasks) < 3
                        and ("json" in response.headers.get(
                            "content-type", "").lower()
                            or "remix" in response.headers.get(
                                "content-type", "").lower())):
                    content_length = response.headers.get("content-length", "")
                    if (not content_length.isdecimal()
                            or int(content_length) <= _MAX_BODY):
                        async def read_regionless_metadata():
                            try:
                                body = await asyncio.wait_for(
                                    response.body(), timeout=8)
                                self.regionless_events.append(
                                    inspect_filtered_response(body))
                            except Exception:
                                self.regionless_events.append(
                                    _DEFAULT_FILTER_FIELDS.copy())
                        task = asyncio.create_task(read_regionless_metadata())
                        self.tasks.add(task)
                        task.add_done_callback(self.tasks.discard)
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

    def summarize_request_verdicts(self, public_page_url):
        """One browser search request: request/response/page field classes.

        This does not compare literal URL values; only classification
        verdicts. Multiple requests remain ambiguous, without selecting
        a favorable sample.
        """
        count = self.diagnostics["search_requests"]
        if count == 0:
            return sanitize_apply_request_diagnostics(
                {"observation": "NOT_OBSERVED"})
        if count != 1 or len(self.request_verdicts) != 1:
            return sanitize_apply_request_diagnostics({
                "observation": (
                    "MULTIPLE_OBSERVED" if count > 1 else "UNOBSERVABLE")})
        entry = next(iter(self.request_verdicts.values()))
        page = classify_filter_url(public_page_url)
        url = entry["request_url"]
        relationships = {}
        for key in _URL_FIELDS:
            a = url["fields"][key]
            b = page["fields"][key]
            relationships[key] = (
                "UNOBSERVABLE" if "UNOBSERVABLE" in (a, b)
                else "SAME" if a == b else "DIFFERENT")
        return sanitize_apply_request_diagnostics({
            "observation": "ONE_OBSERVED",
            "transport": entry["transport"],
            "method": entry["method"],
            "request_url": url,
            "response_url": entry["response_url"],
            "outcome": entry["outcome"],
            "field_verdict_relationship": relationships,
        })

    async def drain(self):
        if self.tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*list(self.tasks), return_exceptions=True),
                    timeout=9)
            except asyncio.TimeoutError:
                pass


async def verify_filter_before_collection(page, region=REGION):
    """Fail-closed FILL-only public filter Apply, ending before listing collection.

    After *any* exception, preserve already observed click/URL/request categories.
    Do not replay Apply, force click, infer a server price from URL or inspect
    listing fields. All output passes the fixed privacy sanitizer.
    """
    info = {
        "region_gate_confirmed": True, "status": "BLOCKED_PRECONDITION",
        "server_filters": {}, "filtered_route_count": 0,
        "ui_after_apply_recheck_state": "NOT_RUN",
        "apply_action_stage": "NOT_STARTED",
        "apply_action_exception_kind": "NONE",
    }
    if (region is not REGION and region != REGION) or not page.url.startswith(
            "https://www.daangn.com/kr/search/buy-sell/"):
        return sanitize_precollection(info)

    args = SimpleNamespace(
        category_name="디지털기기", category_id=CATEGORY_ID,
        available_only=True, max_price=MAX_PRICE, min_price=0)
    watcher = PassiveFilteredRoute()
    witness = FilterApplyActivationWitness()
    listeners = []
    try:
        info["apply_action_stage"] = "LOCATE_FILTER_CONTROLS"
        button, selected = await v46.set_filter(page, args, [])
        info["apply_action_stage"] = "FILTER_CONTROLS_READY"
        info["ui_selected_before_apply"] = v46.ui_ok(selected, args)
        if not info["ui_selected_before_apply"] or not await button.is_enabled():
            info["status"] = "BLOCKED_FILTER_CONTROL"
        else:
            # Merely install a read-only witness on the exact, already
            # validated Apply control. An observer failure does not authorize
            # or force a click, or alter default Playwright action behavior.
            await witness.arm(button)
            for name, callback in (
                    ("request", watcher.on_request),
                    ("response", watcher.on_response),
                    ("requestfailed", watcher.on_requestfailed)):
                page.on(name, callback)
                listeners.append((name, callback))
            info["apply_request_listener_armed"] = True
            info["apply_action_stage"] = "BEFORE_APPLY_CLICK"
            await button.click(timeout=6000)
            info["filter_apply_returned"] = True
            info["apply_action_stage"] = "AFTER_APPLY_CLICK"
            await page.wait_for_timeout(1800)
            info["apply_action_stage"] = "AFTER_APPLY_SETTLE"
            await watcher.drain()
            info["apply_action_stage"] = "AFTER_TRANSPORT_DRAIN"

            # Freeze the Apply-attributable request window before the UI
            # recheck, which may itself cause additional browser requests.
            for name, callback in listeners:
                page.remove_listener(name, callback)
            listeners.clear()

            if watcher.restricted:
                info["status"] = "BLOCKED_ACCESS_RESTRICTED"
            else:
                info["filtered_url_matches"] = _unique_query(page.url, region)
                if not info["filtered_url_matches"]:
                    info["status"] = "BLOCKED_FILTER_URL"
                else:
                    info["apply_action_stage"] = "BEFORE_UI_RECHECK"
                    after = await v46.check_after(page, args)
                    info["apply_action_stage"] = "AFTER_UI_RECHECK"
                    info["ui_after_apply_recheck_state"] = _kind(
                        after.get("observation_status"), _UI_RECHECK_STATES,
                        "NOT_OBSERVABLE")
                    info["ui_selected_after_apply"] = (
                        after.get("observation_status") == "OBSERVED_MATCH"
                        and v46.ui_ok(after, args))
                    if not info["ui_selected_after_apply"]:
                        info["status"] = "BLOCKED_UI_RECHECK"
                    elif not watcher.events:
                        info["status"] = "BLOCKED_FILTER_ROUTE_MISSING"
                    elif len(watcher.events) != 1 or watcher.observed != 1:
                        info["status"] = "BLOCKED_FILTER_ROUTE_AMBIGUOUS"
                    else:
                        info["server_filters"] = watcher.events[0]
                        info["strict_filter_evidence"] = all(
                            info["server_filters"].get(key) == "EXPECTED"
                            for key in ("region", "category", "price_max",
                                        "available"))
                        info["status"] = (
                            "PRECOLLECTION_READY_REVIEW"
                            if info["strict_filter_evidence"]
                            else "BLOCKED_FILTER_ROUTE_METADATA")
                        info["apply_action_stage"] = "COMPLETE"
    except Exception as exc:
        # Never export raw Playwright/website exception messages.
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        info["apply_action_exception_kind"] = (
            "PLAYWRIGHT_TIMEOUT" if isinstance(exc, PlaywrightTimeoutError)
            else "OTHER_EXCEPTION")
        info["status"] = (
            "BLOCKED_APPLY_ACTION"
            if info.get("ui_selected_before_apply") is True
            else "BLOCKED_FILTER_CONTROL")
    finally:
        # The previous implementation returned all -1 counters if click()
        # raised. Inspect the already generated browser events *regardless*
        # of whether the Playwright action promise returned successfully.
        if listeners:
            try:
                await watcher.drain()
            except Exception:
                pass
        for name, callback in listeners:
            try:
                page.remove_listener(name, callback)
            except Exception:
                pass
        if info.get("apply_request_listener_armed") is True:
            info["filtered_route_count"] = watcher.observed
            info["regionless_route_count"] = watcher.regionless_observed
            (
                info["regionless_route_status"],
                info["regionless_server_filters"],
            ) = regionless_route_summary(
                watcher.regionless_observed, watcher.regionless_events)
            info["filter_transport_diagnostics"] = watcher.diagnostics.copy()
            info["apply_search_request_diagnostics"] = (
                watcher.summarize_request_verdicts(page.url))
            try:
                info["filtered_url_diagnostics"] = classify_filter_url(
                    page.url, region)
            except Exception:
                pass
        # Read the existing header only. A still-selected target header does
        # not prove the backend search region is correct after Apply.
        if info.get("apply_request_listener_armed") is True:
            try:
                raw_header = await read_region_header_volatile(page)
                state = classify_region_header_transition(
                    raw_header, raw_header, target_term=region["term"])
                info["post_apply_region_header"] = state["after_header_family"]
            except Exception:
                info["post_apply_region_header"] = "UNOBSERVABLE"
        info["apply_activation"] = await witness.sample(page)
        await witness.stop(page)
    return sanitize_precollection(info)
