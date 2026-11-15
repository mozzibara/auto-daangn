# -*- coding: utf-8 -*-
"""Non-admitting reconciliation of a single browser Remix response and URL.

The response's searchRegion/currentFilters IDs and browser URL 'in' are
independent propositions. A server match cannot waive the URL or UI gate.
"""
from __future__ import annotations

from app_v5.remix_independent_evidence import independent_remix_evidence


def _mapping(obj):
    return obj if type(obj) is dict else {}


def _field(obj, key):
    return _mapping(_mapping(obj).get("fields")).get(key, "UNOBSERVABLE")


def classify_apply_region_correspondence(precollection):
    row = _mapping(precollection)
    scalar = independent_remix_evidence(row)
    req = _mapping(row.get("apply_search_request_diagnostics"))
    page_region = _field(row.get("filtered_url_diagnostics"), "region")
    request_region = _field(req.get("request_url"), "region")
    response_region = _field(req.get("response_url"), "region")
    server_region = scalar["response_region_ids"]
    classification = "UNVERIFIED"
    if scalar["source_provenance"] == "SINGLE_BROWSER_REMIX_DATA_200":
        if server_region in ("OTHER", "AMBIGUOUS"):
            classification = "SERVER_REGION_CONFLICT"
        elif server_region == "MISSING":
            classification = "SERVER_REGION_MISSING"
        elif server_region == "EXPECTED":
            urls = (page_region, request_region, response_region)
            if all(value == "MISSING" for value in urls):
                classification = "SERVER_MATCH_BUT_URL_REGION_MISSING"
            elif any(value in ("OTHER", "DUPLICATE") for value in urls):
                classification = "URL_REGION_CONFLICT"
            elif page_region != request_region:
                classification = "PAGE_URL_REQUEST_DIVERGED"
            else:
                classification = "URL_REGION_INCONCLUSIVE"
    return {
        "schema": "apply_region_correspondence_v1",
        "classification": classification,
        "post_apply_header_target": (
            row.get("post_apply_region_header") == "TARGET"),
        "response_region_matched": (
            scalar["source_provenance"] == "SINGLE_BROWSER_REMIX_DATA_200"
            and server_region == "EXPECTED"),
        "url_region_proven": False,
        "releases_region_mismatch": False,
        "authorizes_listings": False,
    }
