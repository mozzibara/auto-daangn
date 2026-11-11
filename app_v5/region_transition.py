# -*- coding: utf-8 -*-
"""Privacy-bounded, diagnostic-only region-picker transition evidence.

Never upgrades region authority, changes preset IDs or exports response bodies.
The caller must collect only browser-emitted responses after the actual click.
"""
from __future__ import annotations

from app_v5.region_proof import classify_region_correspondence


def _id_state(value, expected):
    return ("MISSING" if value is None else
            "EXPECTED" if str(value) == str(expected) else "OTHER")


def classify_picker_transition(region: dict, steps: dict, events: list,
                               *, fetch_count: int = 0) -> dict:
    """Classify immediate post-selection Route without trusting a click."""
    safe_steps = steps if isinstance(steps, dict) else {}
    safe_events = events if isinstance(events, list) else []
    selected = safe_steps.get("selected_suggestion") is True
    count = min(max(fetch_count, 0), 20) if type(fetch_count) is int else -1
    result = {
        "selection_clicked": selected,
        "option_city_hint": safe_steps.get("option_city_hint") is True,
        "option_exact_term": safe_steps.get("option_exact_term") is True,
        "option_metadata": (safe_steps.get("option_metadata")
                            if safe_steps.get("option_metadata") in
                            ("OBSERVED", "UNAVAILABLE") else "UNAVAILABLE"),
        "option_data_id": (safe_steps.get("option_data_id")
                           if safe_steps.get("option_data_id") in
                           ("EXPECTED", "OTHER", "MISSING") else "MISSING"),
        "option_still_visible": safe_steps.get("option_still_visible") is True,
        "post_click_search_fetch_count": count,
        "post_click_model_count": min(len(safe_events), 20),
        "post_click_route_status": "NO_FRESH_ROUTE",
        "search_region_state": "MISSING",
        "filter_region_state": "MISSING",
        "server_name_state": "MISSING",
        "server_ids_agree": "MISSING",
        "request_keyword_matches": False,
        "request_region_missing": False,
    }
    if not selected:
        result["post_click_route_status"] = "SELECTION_NOT_CONFIRMED"
    elif len(safe_events) == 0 and count > 0:
        result["post_click_route_status"] = "UNPARSED_POST_CLICK_ROUTE"
    elif len(safe_events) > 1:
        result["post_click_route_status"] = "AMBIGUOUS_FRESH_ROUTES"
    elif len(safe_events) == 1:
        event = safe_events[0] if isinstance(safe_events[0], dict) else {}
        model = event.get("model")
        model = model if isinstance(model, dict) else {}
        request = event.get("public_request") if isinstance(event, dict) else None
        request = request if isinstance(request, dict) else {}
        params = request.get("public_params")
        params = params if isinstance(params, dict) else {}
        concordance = classify_region_correspondence(model, region)
        result.update({
            "post_click_route_status": (
                "FRESH_ROUTE_OBSERVED"
                if (event.get("status") == 200
                    and request.get("valid") is True
                    and params.get("q") == "HDD")
                else "POST_CLICK_QUERY_OR_ROUTE_INVALID"),
            "search_region_state": _id_state(model.get("region_id"), region["id"]),
            "filter_region_state": _id_state(model.get("filter_region_id"), region["id"]),
            "server_name_state": concordance["search_region_name_state"],
            "server_ids_agree": concordance["server_region_ids_agree"],
            "request_keyword_matches": params.get("q") == "HDD",
            "request_region_missing": "in" not in params,
        })
    return result


def classify_filter_transition(picker: dict, applied: dict) -> str:
    """Identify where locality stopped matching; no promotion or ID inference."""
    pre = picker if isinstance(picker, dict) else {}
    post = applied if isinstance(applied, dict) else {}
    if pre.get("post_click_route_status") != "FRESH_ROUTE_OBSERVED":
        return "POST_CLICK_ROUTE_NOT_OBSERVABLE"
    pre_pair = (pre.get("search_region_state"),
                pre.get("filter_region_state"))
    post_pair = (post.get("last_route_search_region_state"),
                 post.get("last_route_filter_region_state"))
    if any(v not in ("EXPECTED", "OTHER") for v in post_pair):
        return "FILTER_APPLY_ROUTE_NOT_OBSERVABLE"
    if pre_pair == ("EXPECTED", "EXPECTED") and post_pair == ("EXPECTED", "EXPECTED"):
        return "EXPECTED_REGION_PERSISTED"
    if pre_pair == ("EXPECTED", "EXPECTED") and post_pair != ("EXPECTED", "EXPECTED"):
        return "REGION_LOST_AT_FILTER_APPLY"
    if pre_pair != ("EXPECTED", "EXPECTED"):
        return "REGION_NOT_VERIFIED_AFTER_CLICK"
    return "NOT_OBSERVABLE"


_PICKER_ENUMS = {
    "option_metadata": {"OBSERVED", "UNAVAILABLE"},
    "option_data_id": {"EXPECTED", "OTHER", "MISSING"},
    "post_click_route_status": {"SELECTION_NOT_CONFIRMED", "NO_FRESH_ROUTE",
                                "AMBIGUOUS_FRESH_ROUTES", "FRESH_ROUTE_OBSERVED",
                                "UNPARSED_POST_CLICK_ROUTE",
                                "POST_CLICK_QUERY_OR_ROUTE_INVALID"},
    "search_region_state": {"EXPECTED", "OTHER", "MISSING"},
    "filter_region_state": {"EXPECTED", "OTHER", "MISSING"},
    "server_name_state": {"EXACT", "CONTAINS", "OTHER", "MISSING"},
    "server_ids_agree": {"YES", "NO", "MISSING"},
    "filter_apply_relation": {"POST_CLICK_ROUTE_NOT_OBSERVABLE",
                              "EXPECTED_REGION_PERSISTED",
                              "REGION_LOST_AT_FILTER_APPLY",
                              "REGION_NOT_VERIFIED_AFTER_CLICK",
                              "FILTER_APPLY_ROUTE_NOT_OBSERVABLE",
                              "NOT_OBSERVABLE"},
}
_PICKER_BOOLEANS = (
    "selection_clicked", "option_city_hint", "option_exact_term",
    "option_still_visible", "request_keyword_matches",
    "request_region_missing",
)
_PICKER_COUNTS = ("post_click_search_fetch_count", "post_click_model_count")


def sanitize_picker_transition(value: dict | None) -> dict:
    """Allowlist every value before it crosses the public report boundary."""
    source = value if type(value) is dict else {}
    result = {}
    for field, valid in _PICKER_ENUMS.items():
        raw = source.get(field)
        result[field] = raw if type(raw) is str and raw in valid else "UNKNOWN"
    for field in _PICKER_BOOLEANS:
        result[field] = source.get(field) is True
    for field in _PICKER_COUNTS:
        raw = source.get(field)
        result[field] = raw if type(raw) is int and 0 <= raw <= 20 else -1
    return result
