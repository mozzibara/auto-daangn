# -*- coding: utf-8 -*-
"""Independent region provenance for a *fresh UI-triggered* public Route.

Never accept the original navigation URL, a Remix boot loader, an inferred
neighborhood from listing cards, or a successful click alone as locality proof.
No network access or raw listing data is exported by this module.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

import daangn_v4_1_core as core

_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def _search_query(url: str, expected_keyword: str, expected_slug: str):
    """Return normalized URL location proof without returning raw URLs."""
    try:
        u = urlsplit(url)
        q = parse_qs(u.query, keep_blank_values=True)
        if (u.scheme != "https" or u.hostname != "www.daangn.com"
                or u.port is not None or u.path != core.SEARCH_PATH
                or q.get("q") != [expected_keyword] or
                len(q.get("in", [])) > 1):
            return "INVALID", False
        if "in" not in q:
            return "MISSING", True
        if q["in"] == [expected_slug]:
            return "EXPECTED", True
        return "OTHER", True
    except (ValueError, TypeError, AttributeError):
        return "INVALID", False


def verified_region(region: dict, page_url: str, route_event: dict | None,
                    ui_witness: dict | None, *,
                    picker_selected: bool = False, keyword: str = "HDD") -> dict:
    """Fail-closed locality proof. Returns only allowlisted statuses/booleans.

    route_event MUST originate from a response listener installed immediately
    around the *current* filter-Apply UI action (not window.__remixContext).
    The caller independently compares the body SHA with the passive collector.
    """
    expected_id = region["id"]
    expected_slug = region["slug"]
    url_state, url_valid = _search_query(page_url, keyword, expected_slug)
    ev = route_event if isinstance(route_event, dict) else {}
    request = ev.get("public_request")
    request = request if isinstance(request, dict) else {}
    response_url = request.get("url")
    # Do not trust a URL reconstructed from a dictionary of filtered values.
    # evidence.public_url stores the normalized first-party response URL.
    request_state, request_valid = _search_query(
        response_url, keyword, expected_slug)
    model = ev.get("model")
    model = model if isinstance(model, dict) else {}
    ui = ui_witness if isinstance(ui_witness, dict) else {}
    visible_ui = ui.get("verified") is True
    unique_ui_action = (picker_selected is True
                        and ui.get("unique_option_clicked") is True)
    # A uniquely identified public suggestion selected by the actual browser
    # is an independent UI action witness when the selected locality label
    # disappears from the page. Neither witness substitutes for Route IDs.
    selected_ui = visible_ui or unique_ui_action
    ui_source = ("VISIBLE_REGION_CONTROL" if visible_ui else
                 "UNIQUE_REGION_OPTION" if unique_ui_action else "NONE")
    ids_match = (str(model.get("region_id")) == expected_id
                 and str(model.get("filter_region_id")) == expected_id)
    digest = ev.get("digest")
    digest_valid = isinstance(digest, str) and bool(_HEX64.fullmatch(digest))
    response_status = ev.get("status")
    response_trusted = (response_status == 200 and digest_valid
                        and request.get("valid") is True)
    omitted = url_state == "MISSING" or request_state == "MISSING"
    mismatched_url = url_state == "OTHER" or request_state == "OTHER"
    if not url_valid or url_state == "OTHER" or request_state == "OTHER":
        status = "REGION_URL_INVALID"
    elif not selected_ui:
        status = "REGION_UI_NOT_VERIFIED"
    elif not response_trusted:
        # An absent response has no request URL to classify, and must not be
        # confused with an observed mismatched region or malformed query.
        status = "FRESH_ROUTE_NOT_VERIFIED"
    elif not request_valid:
        status = "REGION_URL_INVALID"
    elif model.get("region_id") is None or model.get("filter_region_id") is None:
        # A parsed search model may omit one or both region fields.
        # Missing metadata is not equivalent to a verified wrong region.
        status = "ROUTE_REGION_METADATA_MISSING"
    elif not ids_match:
        status = "ROUTE_REGION_CONFLICT"
    elif url_state != request_state:
        status = "REGION_URL_RESPONSE_DISAGREEMENT"
    elif omitted and not picker_selected:
        status = "REGION_OMISSION_WITHOUT_UI_SELECTION"
    else:
        status = "UI_FRESH_ROUTE_REGION_VERIFIED"
    return {
        "status": status,
        "verified": status == "UI_FRESH_ROUTE_REGION_VERIFIED",
        "ui_witness": selected_ui,
        "ui_source": ui_source,
        "route_ids_match": ids_match,
        "fresh_response_authenticated": response_trusted,
        "url_region": url_state,
        "response_region": request_state,
        "region_param_missing": omitted,
        "picker_selected": picker_selected is True,
    }
