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
# Historical daangn_v4_5_evidence.public_filters and validated_predicates
# independently support currentFilters.priceRange.max as a server scalar.
# Only the separately approved V2 diagnostic uses this extension.
_PRICE_METADATA_SHAPES = (
    "DIRECT_ALIAS", "NESTED_PRICE_RANGE_MAX",
    "RANGE_WITHOUT_MAX", "MALFORMED_RANGE",
    "MULTIPLE_PRICE_SOURCES", "UNTRUSTED_PRICE_ONLY",
    "ABSENT", "NO_SEARCH_MODEL", "UNOBSERVABLE",
)
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
_REGION_URL_TIMELINE_STAGES = (
    "BEFORE_OPEN_FILTER", "AFTER_OPEN_FILTER", "AFTER_CATEGORY",
    "AFTER_AVAILABLE", "AFTER_MAX_FILL", "AFTER_MAX_TAB",
    "BEFORE_APPLY", "AFTER_CLICK_RETURN", "AFTER_SETTLE",
    "AT_REPORT_SNAPSHOT",
)
_REGION_TIMELINE_FIRST_STATES = (
    "NOT_OBSERVED", "INCONCLUSIVE", *_REGION_URL_TIMELINE_STAGES,
)


def sanitize_region_url_timeline(raw):
    """Fixed stages + redacted URL classifications only; never raw URL."""
    src = raw if type(raw) is dict else {}
    stages = src.get("stage_region") if type(src.get("stage_region")) is dict else {}
    return {
        "stage_region": {
            key: _kind(stages.get(key), _URL_FIELD_STATES, "UNOBSERVABLE")
            for key in _REGION_URL_TIMELINE_STAGES
        },
        "first_missing_stage": _kind(
            src.get("first_missing_stage"), _REGION_TIMELINE_FIRST_STATES,
            "INCONCLUSIVE"),
        "authorizes_listings": False,
    }


def summarize_region_url_timeline(stage_states):
    """Find first observable missing 'in' without assuming missing gaps.

    All stages are read-only observations; this is not proof of a server
    region and it never changes the strict Apply admission gate.
    """
    src = stage_states if type(stage_states) is dict else {}
    observed = {}
    for key in _REGION_URL_TIMELINE_STAGES:
        if key in src:
            entry = sanitize_filter_url_diagnostic(src[key])
            observed[key] = entry["fields"]["region"]
    first = "INCONCLUSIVE"
    if observed.get("BEFORE_OPEN_FILTER") in ("EXPECTED", "MISSING"):
        first = "NOT_OBSERVED"
        previous = observed["BEFORE_OPEN_FILTER"]
        for key in _REGION_URL_TIMELINE_STAGES:
            if key not in observed:
                continue
            state = observed[key]
            if state == "MISSING":
                first = key
                break
            if state != "EXPECTED":
                first = "INCONCLUSIVE"
                break
            previous = state
    return sanitize_region_url_timeline({
        "stage_region": observed,
        "first_missing_stage": first,
    })
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
        "request_extra_query_family": _kind(
            src.get("request_extra_query_family"),
            _EXTRA_QUERY_FAMILIES, "UNOBSERVABLE"),
        "response_extra_query_family": _kind(
            src.get("response_extra_query_family"),
            _EXTRA_QUERY_FAMILIES, "UNOBSERVABLE"),
        "request_data_route_family": _kind(
            src.get("request_data_route_family"),
            _DYNAMIC_ROUTE_FAMILIES, "UNOBSERVABLE"),
        "response_data_route_family": _kind(
            src.get("response_data_route_family"),
            _DYNAMIC_ROUTE_FAMILIES, "UNOBSERVABLE"),
        "request_route_selector": _kind(
            src.get("request_route_selector"),
            _REMIX_SELECTOR_STATES, "UNOBSERVABLE"),
        "response_route_selector": _kind(
            src.get("response_route_selector"),
            _REMIX_SELECTOR_STATES, "UNOBSERVABLE"),
        "outcome": _kind(src.get("outcome"), _REQUEST_OUTCOME_STATES,
                         "NOT_OBSERVED"),
        # These compare classifications, NOT raw query values or exact URLs.
        "field_verdict_relationship": {
            key: _kind(relations.get(key), _VERDICT_RELATIONS, "UNOBSERVABLE")
            for key in _URL_FIELDS
        },
        "authorizes_listings": False,
    }


_EXTRA_QUERY_FAMILIES = (
    "NONE", "EXACT_REMIX_DATA", "OTHER_REMIX_DATA_ID",
    "ROUTES_KEY", "INDEX_KEY", "DUPLICATE_EXTRA_VALUE",
    "OTHER_SINGLE_KEY", "MULTIPLE_EXTRA_KEYS",
    "FILTER_QUERY_MISMATCH", "UNOBSERVABLE",
)


def classify_extra_query_family(url):
    """Known-key family only; never copy arbitrary key names or values.

    This is *not* an authoritative transport or locality proof. It
    categorizes exactly the already-browser-observed public search query,
    after checking its four fixed requested filters and absence of 'in'.
    """
    if type(url) is not str or len(url) > 4096:
        return "UNOBSERVABLE"
    if not _same_public_search_path(url):
        return "FILTER_QUERY_MISMATCH"
    try:
        qs = parse_qs(urlsplit(url).query, keep_blank_values=True)
        fixed = {
            "q": KEYWORD, "category_id": str(CATEGORY_ID),
            "price": "__" + str(MAX_PRICE), "only_on_sale": "true",
        }
        if (qs.get("in") is not None
                or any(qs.get(k) != [v] for k, v in fixed.items())):
            return "FILTER_QUERY_MISMATCH"
        keys = set(qs).difference(fixed)
        if not keys:
            return "NONE"
        if len(keys) != 1:
            return "MULTIPLE_EXTRA_KEYS"
        key = next(iter(keys))
        values = qs[key]
        if len(values) != 1:
            return "DUPLICATE_EXTRA_VALUE"
        if key == "_data":
            return ("EXACT_REMIX_DATA" if values[0] == core.ROUTE_ID
                    else "OTHER_REMIX_DATA_ID")
        if key == "_routes":
            return "ROUTES_KEY"
        if key == "index":
            return "INDEX_KEY"
        return "OTHER_SINGLE_KEY"
    except (ValueError, TypeError, AttributeError):
        return "UNOBSERVABLE"


_REMIX_SELECTOR_STATES = (
    "EXPECTED_SEARCH_LOADER", "OTHER_EXTRA", "NONE",
    "QUERY_MISMATCH", "UNOBSERVABLE",
)


def classify_remix_loader_selector(url):
    """Only a known framework route selector; no unrecognized keys or values."""
    if type(url) is not str or len(url) > 4096:
        return "UNOBSERVABLE"
    if not _same_public_search_path(url):
        return "QUERY_MISMATCH"
    try:
        parsed = urlsplit(url)
        qs = parse_qs(parsed.query, keep_blank_values=True)
        fixed = {
            "q": KEYWORD,
            "category_id": str(CATEGORY_ID),
            "price": "__" + str(MAX_PRICE),
            "only_on_sale": "true",
        }
        if (qs.get("in") is not None or
                any(qs.get(k) != [v] for k, v in fixed.items())):
            return "QUERY_MISMATCH"
        extras = set(qs).difference(fixed)
        if not extras:
            return "NONE"
        if extras == {"_data"} and qs.get("_data") == [core.ROUTE_ID]:
            return "EXPECTED_SEARCH_LOADER"
        return "OTHER_EXTRA"
    except (ValueError, TypeError, AttributeError):
        return "UNOBSERVABLE"


def _changed_search_remix_loader(url):
    """Tight opt-in diagnostic selector, NEVER a trusted Route or URL gate.

    Same first-party search path + exact four known filters + no 'in', and
    precisely one _data with a bounded search-route-like value. Arbitrary
    unknown or duplicate selectors must remain unread.
    """
    if (classify_extra_query_family(url) != "OTHER_REMIX_DATA_ID"
            or type(url) is not str or len(url) > 4096):
        return False
    try:
        u = urlsplit(url)
        if u.username is not None or u.password is not None or u.fragment:
            return False
        qs = parse_qs(u.query, keep_blank_values=True)
        route = qs["_data"][0]
        return (type(route) is str and 10 <= len(route) <= 180
                and route.startswith("routes/kr.search.buy-sell")
                and route != core.ROUTE_ID
                and all(ch.isalnum() or ch in "._/-$" for ch in route))
    except (ValueError, KeyError, TypeError, AttributeError):
        return False


_DYNAMIC_ROUTE_FAMILIES = (
    "LEGACY_EXACT", "SEARCH_PREFIX", "OTHER_ROUTES_NAMESPACE",
    "NOT_ROUTES_NAMESPACE", "MALFORMED_SELECTOR",
    "FILTER_QUERY_MISMATCH", "UNOBSERVABLE",
)


def classify_dynamic_data_route(url):
    """Classify only known _data namespaces; never reveal selector value.

    v4.6's browser-emitted search JSON observer and v4.14 RouteBodies
    did not require a hardcoded route-id prefix. This diagnosis does
    NOT authorize opening an unknown response by itself.
    """
    if type(url) is not str or len(url) > 4096:
        return "UNOBSERVABLE"
    family = classify_extra_query_family(url)
    if family not in ("EXACT_REMIX_DATA", "OTHER_REMIX_DATA_ID"):
        return "FILTER_QUERY_MISMATCH"
    try:
        u = urlsplit(url)
        if u.username is not None or u.password is not None or u.fragment:
            return "MALFORMED_SELECTOR"
        route = parse_qs(u.query, keep_blank_values=True)["_data"][0]
        if (not isinstance(route, str) or not (8 <= len(route) <= 180)
                or not route.isascii()
                or not all(ch.isalnum() or ch in "._/-$" for ch in route)
                or ".." in route or "//" in route):
            return "MALFORMED_SELECTOR"
        if route == core.ROUTE_ID:
            return "LEGACY_EXACT"
        if route.startswith("routes/kr.search.buy-sell"):
            return "SEARCH_PREFIX"
        if route.startswith("routes/") and route[7:]:
            return "OTHER_ROUTES_NAMESPACE"
        return "NOT_ROUTES_NAMESPACE"
    except (KeyError, IndexError, ValueError, TypeError, AttributeError):
        return "UNOBSERVABLE"


def _dynamic_browser_search_loader(url):
    """V2 requires separate owner approval; never used to admit listings."""
    return classify_dynamic_data_route(url) in (
        "SEARCH_PREFIX", "OTHER_ROUTES_NAMESPACE")


def _exact_known_remix_regionless_loader(url):
    """Non-admitting passive probe of an already-browser-generated Route."""
    return classify_remix_loader_selector(url) == "EXPECTED_SEARCH_LOADER"


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
_POST_TIMEOUT_OBSERVATIONS = (
    "NOT_APPLICABLE", "OBSERVED_LATE_RESPONSE", "NO_RESPONSE_IN_WINDOW",
    "SKIPPED_CLICK_NOT_PROVEN", "SKIPPED_REQUEST_NOT_UNIQUE",
    "SKIPPED_ALREADY_RESPONDED", "SKIPPED_RESTRICTED",
    "OBSERVER_ERROR",
)
# One fixed, local event-loop observation window; no navigation/requests.
_POST_TIMEOUT_OBSERVATION_SEC = 2.0


async def passive_posttimeout_request_observation(watcher, witness, page):
    """Observe only an already-started single search request, never re-click.

    The Playwright click promise may timeout *after* a trusted click and
    a browser search request. This read-only wait distinguishes a pending
    request that receives its response after the exception from one still
    unobserved. It never authorizes an Apply action that did not return.
    """
    try:
        snap = await witness.sample(page)
        if snap["one_trusted_click"] is not True:
            return "SKIPPED_CLICK_NOT_PROVEN"
        d = watcher.diagnostics
        if (d["search_requests"] != 1 or
                d["search_request_failures"] != 0):
            return "SKIPPED_REQUEST_NOT_UNIQUE"
        if d["search_response_restricted"] != 0 or watcher.restricted:
            return "SKIPPED_RESTRICTED"
        if d["search_responses"] != 0:
            return "SKIPPED_ALREADY_RESPONDED"
        # Do not wait on an arbitrary page event or issue network calls.
        # Keep the original response/request listeners installed.
        await asyncio.sleep(_POST_TIMEOUT_OBSERVATION_SEC)
        await watcher.drain()
        if watcher.restricted:
            return "SKIPPED_RESTRICTED"
        if d["search_requests"] != 1 or d["search_request_failures"] != 0:
            return "SKIPPED_REQUEST_NOT_UNIQUE"
        return ("OBSERVED_LATE_RESPONSE" if d["search_responses"] == 1
                else "NO_RESPONSE_IN_WINDOW")
    except Exception:
        return "OBSERVER_ERROR"


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
        "posttimeout_passive_observation": _kind(
            src.get("posttimeout_passive_observation"),
            _POST_TIMEOUT_OBSERVATIONS, "NOT_APPLICABLE"),
        "apply_activation": sanitize_apply_activation(src.get("apply_activation")),
        "apply_request_listener_armed": src.get("apply_request_listener_armed") is True,
        "filtered_url_matches": src.get("filtered_url_matches") is True,
        "filtered_url_diagnostics": sanitize_filter_url_diagnostic(
            src.get("filtered_url_diagnostics")),
        "region_url_timeline": sanitize_region_url_timeline(
            src.get("region_url_timeline")),
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
        "remix_regionless_route_count": _bounded(
            src.get("remix_regionless_route_count")),
        "dynamic_loader_price_shape": _kind(
            src.get("dynamic_loader_price_shape"),
            _PRICE_METADATA_SHAPES, "UNOBSERVABLE"),
        "dynamic_loader_metadata_mode": src.get(
            "dynamic_loader_metadata_mode") is True,
        "dynamic_loader_metadata_count": _bounded(
            src.get("dynamic_loader_metadata_count")),
        "dynamic_loader_metadata_status": _kind(
            src.get("dynamic_loader_metadata_status"),
            _REGIONLESS_ROUTE_STATUSES, "UNOBSERVABLE"),
        "dynamic_loader_server_filters": {
            k: _kind(
                (src.get("dynamic_loader_server_filters")
                 if type(src.get("dynamic_loader_server_filters")) is dict
                 else {}).get(k), _ITEM_STATUS, "MISSING")
            for k in ("region", "category", "price_max", "available")
        },
        "changed_loader_metadata_mode": src.get(
            "changed_loader_metadata_mode") is True,
        "changed_loader_metadata_count": _bounded(
            src.get("changed_loader_metadata_count")),
        "changed_loader_metadata_status": _kind(
            src.get("changed_loader_metadata_status"),
            _REGIONLESS_ROUTE_STATUSES, "UNOBSERVABLE"),
        "changed_loader_server_filters": {
            k: _kind(
                (src.get("changed_loader_server_filters")
                 if type(src.get("changed_loader_server_filters")) is dict
                 else {}).get(k), _ITEM_STATUS, "MISSING")
            for k in ("region", "category", "price_max", "available")
        },
        "remix_regionless_route_status": _kind(
            src.get("remix_regionless_route_status"),
            _REGIONLESS_ROUTE_STATUSES, "UNOBSERVABLE"),
        "remix_regionless_server_filters": {
            k: _kind(
                (src.get("remix_regionless_server_filters")
                 if type(src.get("remix_regionless_server_filters")) is dict
                 else {}).get(k), _ITEM_STATUS, "MISSING")
            for k in ("region", "category", "price_max", "available")
        },
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


def _project_filtered_pair(pair):
    """Only four scalar verdicts from one bounded unique search model."""
    if pair is None:
        return _DEFAULT_FILTER_FIELDS.copy()
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


def inspect_filtered_response(blob):
    """Legacy four-field metadata projection; unchanged strict semantics."""
    return _project_filtered_pair(_find_search_model(blob))


def _price_value_and_shape(filters):
    """Source-supported server price fields only; never infer from URL.

    Known historical response paths: a direct maxPrice alias or
    currentFilters.priceRange.max. The browser query 'price=__50000'
    is explicitly NOT server evidence, even if copied into filters.
    A duplicate source is not promoted, even if values seem consistent.
    """
    if type(filters) is not dict:
        return "MISSING", "NO_SEARCH_MODEL"
    direct = [key for key in _PRICES if key in filters]
    has_range = "priceRange" in filters
    if len(direct) > 1 or (direct and has_range):
        return "AMBIGUOUS", "MULTIPLE_PRICE_SOURCES"
    if direct:
        return (_value_state(filters, _PRICES, MAX_PRICE, as_int=True),
                "DIRECT_ALIAS")
    if has_range:
        range_obj = filters["priceRange"]
        if type(range_obj) is not dict:
            return "AMBIGUOUS", "MALFORMED_RANGE"
        if "max" not in range_obj:
            return "MISSING", "RANGE_WITHOUT_MAX"
        return (_value_state(range_obj, ("max",), MAX_PRICE, as_int=True),
                "NESTED_PRICE_RANGE_MAX")
    if "price" in filters:
        # The web UI's max-only query notation has not been shown to be
        # independently validated as a server response metadata field.
        return "MISSING", "UNTRUSTED_PRICE_ONLY"
    return "MISSING", "ABSENT"


def inspect_dynamic_filtered_response(blob):
    """V2-only diagnostic projection with bounded price-source provenance.

    The same already-consented response bytes are decoded once. No new
    site traffic or additional body read; article arrays are not traversed.
    """
    pair = _find_search_model(blob)
    states = _project_filtered_pair(pair)
    if pair is None:
        return states, "NO_SEARCH_MODEL"
    state, shape = _price_value_and_shape(pair[1])
    states["price_max"] = state
    return states, shape


class PassiveFilteredRoute:
    """Only browser-generated first-party filtered Route responses, no fetch."""
    def __init__(self, *, passive_changed_loader=False,
                 passive_dynamic_loader=False):
        # Caller must hold the SEPARATE owner approval token. An ordinary
        # FILL precollection attempt does not read unknown Remix bodies.
        self.passive_changed_loader = passive_changed_loader is True
        self.passive_dynamic_loader = passive_dynamic_loader is True
        self.dynamic_starts = set()
        self.dynamic_observed = 0
        self.dynamic_events = []
        self.dynamic_price_shapes = []
        self.changed_starts = set()
        self.changed_observed = 0
        self.changed_events = []
        self.events = []
        self.tasks = set()
        self.restricted = False
        self.observed = 0
        self.starts = set()
        self.broad_starts = set()
        self.regionless_starts = set()
        self.regionless_events = []
        self.regionless_observed = 0
        self.remix_regionless_starts = set()
        self.remix_regionless_observed = 0
        self.remix_regionless_events = []
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
                    "request_data_route_family": classify_dynamic_data_route(
                        request.url),
                    "response_data_route_family": "UNOBSERVABLE",
                    "request_route_selector": classify_remix_loader_selector(
                        request.url),
                    "request_extra_query_family": classify_extra_query_family(
                        request.url),
                    "response_extra_query_family": "UNOBSERVABLE",
                    "response_url": None,
                    "response_route_selector": "UNOBSERVABLE",
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
                if (self.passive_dynamic_loader
                        and request.method == "GET"
                        and request.resource_type in ("fetch", "xhr")
                        and _dynamic_browser_search_loader(request.url)
                        and len(self.dynamic_starts) < 4):
                    self.dynamic_starts.add(request)
                if (self.passive_changed_loader
                        and request.method == "GET"
                        and request.resource_type in ("fetch", "xhr")
                        and _changed_search_remix_loader(request.url)
                        and len(self.changed_starts) < 4):
                    self.changed_starts.add(request)
                if (request.method == "GET"
                        and request.resource_type in ("fetch", "xhr")
                        and _exact_known_remix_regionless_loader(request.url)
                        and len(self.remix_regionless_starts) < 4):
                    self.remix_regionless_starts.add(request)
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
                self.remix_regionless_starts.discard(request)
                self.changed_starts.discard(request)
                self.dynamic_starts.discard(request)
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
                entry["response_data_route_family"] = (
                    classify_dynamic_data_route(response.url))
                entry["response_route_selector"] = classify_remix_loader_selector(
                    response.url)
                entry["response_extra_query_family"] = classify_extra_query_family(
                    response.url)
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

            # Source-grounded v4.6/v4.14 dynamic first-party search Route
            # variant: V2 standalone approval permits an already initiated
            # public browser request with one bounded routes/* _data selector
            # regardless of the legacy Route ID. This does not authorize
            # listings, URL-region inference or search acceptance.
            if req in self.dynamic_starts:
                self.dynamic_starts.discard(req)
                self.dynamic_observed = min(20, self.dynamic_observed + 1)
                if (self.passive_dynamic_loader
                        and self.diagnostics["search_requests"] == 1
                        and response.status == 200
                        and req.url == response.url
                        and _dynamic_browser_search_loader(response.url)
                        and len(self.dynamic_events) + len(self.tasks) < 3):
                    ctype = str(
                        response.headers.get("content-type", "")).lower()
                    size = str(response.headers.get("content-length", ""))
                    if (("json" in ctype or "remix" in ctype)
                            and (not size.isdecimal()
                                 or int(size) <= _MAX_BODY)):
                        async def read_dynamic_metadata_only():
                            try:
                                blob = await asyncio.wait_for(
                                    response.body(), timeout=8)
                                verdicts, shape = inspect_dynamic_filtered_response(
                                    blob)
                                self.dynamic_events.append(verdicts)
                                self.dynamic_price_shapes.append(shape)
                            except Exception:
                                self.dynamic_events.append(
                                    _DEFAULT_FILTER_FIELDS.copy())
                                self.dynamic_price_shapes.append(
                                    "UNOBSERVABLE")
                        task = asyncio.create_task(
                            read_dynamic_metadata_only())
                        self.tasks.add(task)
                        task.add_done_callback(self.tasks.discard)

            # Explicitly owner-approved, metadata-only diagnostic:
            # a changed but search-prefix-constrained _data query may
            # carry exactly the already known searchRegion/currentFilters
            # schema. This response is NEVER an admitted collector Route.
            if req in self.changed_starts:
                self.changed_starts.discard(req)
                self.changed_observed = min(20, self.changed_observed + 1)
                # Require a single first-party request/response pair, no
                # redirect, matching safe query and JSON content type.
                if (self.passive_changed_loader
                        and self.diagnostics["search_requests"] == 1
                        and response.status == 200
                        and req.url == response.url
                        and _changed_search_remix_loader(response.url)
                        and len(self.changed_events) + len(self.tasks) < 3):
                    ctype = str(
                        response.headers.get("content-type", "")).lower()
                    size = str(
                        response.headers.get("content-length", ""))
                    if (("json" in ctype or "remix" in ctype)
                            and (not size.isdecimal()
                                 or int(size) <= _MAX_BODY)):
                        async def read_changed_metadata_only():
                            try:
                                blob = await asyncio.wait_for(
                                    response.body(), timeout=8)
                                # inspect_filtered_response excludes item
                                # arrays entirely from the model traversal;
                                # only four finite verdicts may be retained.
                                self.changed_events.append(
                                    inspect_filtered_response(blob))
                            except Exception:
                                self.changed_events.append(
                                    _DEFAULT_FILTER_FIELDS.copy())
                        task = asyncio.create_task(
                            read_changed_metadata_only())
                        self.tasks.add(task)
                        task.add_done_callback(self.tasks.discard)

            # A known first-party Remix loader may carry the exact four
            # filters plus _data=<known search route>. It cannot admit
            # collection because the required region query 'in' is absent.
            if req in self.remix_regionless_starts:
                self.remix_regionless_starts.discard(req)
                self.remix_regionless_observed = min(
                    20, self.remix_regionless_observed + 1)
                if (response.status == 200
                        and _exact_known_remix_regionless_loader(response.url)
                        and len(self.remix_regionless_events) +
                            len(self.tasks) < 3):
                    ctype = response.headers.get(
                        "content-type", "").lower()
                    length = response.headers.get("content-length", "")
                    if (("json" in ctype or "remix" in ctype)
                            and (not length.isdecimal()
                                 or int(length) <= _MAX_BODY)):
                        async def read_known_remix_metadata():
                            try:
                                body = await asyncio.wait_for(
                                    response.body(), timeout=8)
                                self.remix_regionless_events.append(
                                    inspect_filtered_response(body))
                            except Exception:
                                self.remix_regionless_events.append(
                                    _DEFAULT_FILTER_FIELDS.copy())
                        task = asyncio.create_task(
                            read_known_remix_metadata())
                        self.tasks.add(task)
                        task.add_done_callback(self.tasks.discard)

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
            "request_extra_query_family": entry["request_extra_query_family"],
            "response_extra_query_family": entry["response_extra_query_family"],
            "request_data_route_family": entry["request_data_route_family"],
            "response_data_route_family": entry["response_data_route_family"],
            "request_route_selector": entry["request_route_selector"],
            "response_route_selector": entry["response_route_selector"],
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


async def verify_filter_before_collection(
        page, region=REGION, *, passive_changed_loader=False,
        passive_dynamic_loader=False):
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
        "posttimeout_passive_observation": "NOT_APPLICABLE",
        "changed_loader_metadata_mode": passive_changed_loader is True,
        "dynamic_loader_metadata_mode": passive_dynamic_loader is True,
    }
    if (region is not REGION and region != REGION) or not page.url.startswith(
            "https://www.daangn.com/kr/search/buy-sell/"):
        return sanitize_precollection(info)

    args = SimpleNamespace(
        category_name="디지털기기", category_id=CATEGORY_ID,
        available_only=True, max_price=MAX_PRICE, min_price=0)
    watcher = PassiveFilteredRoute(
        passive_changed_loader=passive_changed_loader,
        passive_dynamic_loader=passive_dynamic_loader)
    witness = FilterApplyActivationWitness()
    url_stage_states = {}

    def record_url_stage(stage, current_page=page):
        if stage in _REGION_URL_TIMELINE_STAGES:
            try:
                url_stage_states[stage] = classify_filter_url(
                    current_page.url, region)
            except Exception:
                # Observability errors stay unknown; never generate a URL.
                pass

    listeners = []
    try:
        info["apply_action_stage"] = "LOCATE_FILTER_CONTROLS"
        button, selected = await v46.set_filter(
            page, args, [], on_diagnostic_checkpoint=record_url_stage)
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
            record_url_stage("AFTER_CLICK_RETURN")
            info["filter_apply_returned"] = True
            info["apply_action_stage"] = "AFTER_APPLY_CLICK"
            await page.wait_for_timeout(1800)
            record_url_stage("AFTER_SETTLE")
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
        if (isinstance(exc, PlaywrightTimeoutError)
                and info.get("apply_action_stage") == "BEFORE_APPLY_CLICK"
                and info.get("apply_request_listener_armed") is True):
            info["posttimeout_passive_observation"] = (
                await passive_posttimeout_request_observation(
                    watcher, witness, page))
        # Irrespective of this extra observation, Playwright Apply failed:
        # never retry the button or advance to after-Apply UI checks.
    finally:
        record_url_stage("AT_REPORT_SNAPSHOT")
        info["region_url_timeline"] = summarize_region_url_timeline(
            url_stage_states)
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
            info["dynamic_loader_metadata_count"] = (
                watcher.dynamic_observed)
            # Any competing search or rejected access nullifies potentially
            # favorable metadata from an earlier response in the same window.
            if (watcher.diagnostics["search_requests"] != 1
                    or watcher.diagnostics["search_responses"] != 1
                    or watcher.diagnostics["search_request_failures"] != 0
                    or watcher.restricted):
                info["dynamic_loader_metadata_status"] = (
                    "MULTIPLE_OBSERVED"
                    if watcher.diagnostics["search_requests"] > 1
                    else "ONE_UNREADABLE")
                info["dynamic_loader_server_filters"] = (
                    _DEFAULT_FILTER_FIELDS.copy())
                info["dynamic_loader_price_shape"] = "UNOBSERVABLE"
            else:
                (
                    info["dynamic_loader_metadata_status"],
                    info["dynamic_loader_server_filters"],
                ) = regionless_route_summary(
                    watcher.dynamic_observed, watcher.dynamic_events)
                if (info["dynamic_loader_metadata_status"] == "ONE_PARSED"
                        and len(watcher.dynamic_price_shapes) == 1):
                    info["dynamic_loader_price_shape"] = (
                        watcher.dynamic_price_shapes[0])
            info["changed_loader_metadata_count"] = (
                watcher.changed_observed)
            # Ambiguous, failed, or restricted overall request windows
            # cannot be represented as one authoritative metadata sample.
            if (watcher.diagnostics["search_requests"] != 1
                    or watcher.diagnostics["search_responses"] != 1
                    or watcher.diagnostics["search_request_failures"] != 0
                    or watcher.restricted):
                info["changed_loader_metadata_status"] = (
                    "MULTIPLE_OBSERVED"
                    if watcher.diagnostics["search_requests"] > 1
                    else "ONE_UNREADABLE")
                info["changed_loader_server_filters"] = (
                    _DEFAULT_FILTER_FIELDS.copy())
            else:
                (
                    info["changed_loader_metadata_status"],
                    info["changed_loader_server_filters"],
                ) = regionless_route_summary(
                    watcher.changed_observed, watcher.changed_events)
            info["regionless_route_count"] = watcher.regionless_observed
            info["remix_regionless_route_count"] = (
                watcher.remix_regionless_observed)
            (
                info["remix_regionless_route_status"],
                info["remix_regionless_server_filters"],
            ) = regionless_route_summary(
                watcher.remix_regionless_observed,
                watcher.remix_regionless_events)
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
