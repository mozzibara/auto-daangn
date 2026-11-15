# -*- coding: utf-8 -*-
"""Independent, non-admitting attestation of an already observed Remix _data.

Consumes ONLY the bounded, sanitized passive V2 observer result.
Never navigates, issues requests, parses articles or changes collection gate.
A response echo or server-declared maximum is NOT backend price enforcement.
"""
from __future__ import annotations

_STATES = ("EXPECTED", "OTHER", "MISSING", "AMBIGUOUS")
_ROUTE = ("SEARCH_PREFIX", "OTHER_ROUTES_NAMESPACE")
_SHAPES = ("DIRECT_ALIAS", "NESTED_PRICE_RANGE_MAX")
_FOUR = ("region", "category", "price_max", "available")
_QUERY = ("keyword", "category", "price_max", "available")


def _mapping(obj):
    return obj if type(obj) is dict else {}


def _state(v):
    return v if type(v) is str and v in _STATES else "UNVERIFIED"


def _unique_browser_response(row):
    """Response fields alone cannot establish request/response provenance."""
    net = _mapping(row.get("filter_transport_diagnostics"))
    req = _mapping(row.get("apply_search_request_diagnostics"))
    source = _mapping(req.get("request_url"))
    response = _mapping(req.get("response_url"))
    source_fields = _mapping(source.get("fields"))
    response_fields = _mapping(response.get("fields"))
    return (
        row.get("region_gate_confirmed") is True
        and row.get("ui_selected_before_apply") is True
        and row.get("filter_apply_returned") is True
        and row.get("apply_request_listener_armed") is True
        and net.get("search_requests") == 1
        and net.get("search_responses") == 1
        and net.get("search_response_200") == 1
        and net.get("search_request_failures") == 0
        and net.get("search_response_restricted") == 0
        and req.get("observation") == "ONE_OBSERVED"
        and req.get("method") == "GET"
        and req.get("transport") == "FETCH_OR_XHR"
        and req.get("outcome") == "HTTP_200"
        and req.get("request_extra_query_family") == "OTHER_REMIX_DATA_ID"
        and req.get("response_extra_query_family") == "OTHER_REMIX_DATA_ID"
        and req.get("request_data_route_family") in _ROUTE
        and req.get("response_data_route_family") in _ROUTE
        and source.get("shape") == "FIRST_PARTY_SEARCH"
        and response.get("shape") == "FIRST_PARTY_SEARCH"
        and source_fields.get("region") == "MISSING"
        and response_fields.get("region") == "MISSING"
        and all(source_fields.get(key) == response_fields.get(key) == "EXPECTED"
                for key in _QUERY)
        and row.get("dynamic_loader_metadata_mode") is True
        and row.get("dynamic_loader_metadata_count") == 1
        and row.get("dynamic_loader_metadata_status") == "ONE_PARSED"
    )


def independent_remix_evidence(precollection):
    """Four independently labeled propositions, never listing permission.

    Source requires one already-browser-initiated first-party Remix GET/200
    response parsed by the approved bounded V2 observer. No server field may
    prove price-cap enforcement without an independent behavioral experiment.
    """
    row = _mapping(precollection)
    body = _mapping(row.get("dynamic_loader_server_filters"))
    verified = _unique_browser_response(row)
    fields = {k: _state(body.get(k)) if verified else "UNVERIFIED"
              for k in _FOUR}
    shape = row.get("dynamic_loader_price_shape")
    echo = row.get("dynamic_loader_price_echo")
    declared = fields["price_max"]
    price = "UNVERIFIED"
    if verified:
        if shape == "MULTIPLE_PRICE_SOURCES":
            price = "AMBIGUOUS_DECLARATION"
        elif shape in _SHAPES:
            if declared == "EXPECTED":
                price = ("DECLARED_CONFLICTING_ECHO"
                         if echo == "ENCODED_MAX_OTHER"
                         else "DECLARED_MAX_MATCH_UNENFORCED")
            elif declared == "OTHER":
                price = "DECLARED_MAX_MISMATCH"
            else:
                price = "AMBIGUOUS_DECLARATION"
        elif declared == "AMBIGUOUS":
            price = "AMBIGUOUS_DECLARATION"
        elif shape == "UNTRUSTED_PRICE_ONLY":
            price = (
                "ENCODED_ECHO_ONLY_MATCH" if echo == "ENCODED_MAX_MATCH"
                else "ENCODED_ECHO_MISMATCH" if echo == "ENCODED_MAX_OTHER"
                else "UNPROVEN_PRICE"
            )
        else:
            price = "UNPROVEN_PRICE"

    gaps = []
    if not verified:
        gaps.append("REMIX_RESPONSE_NOT_UNIQUELY_ATTESTED")
    if fields["region"] != "EXPECTED":
        gaps.append("FILTERED_REGION_NOT_CONFIRMED")
    if fields["category"] != "EXPECTED":
        gaps.append("FILTERED_CATEGORY_NOT_CONFIRMED")
    if fields["available"] != "EXPECTED":
        gaps.append("FILTERED_AVAILABILITY_NOT_CONFIRMED")
    if price != "DECLARED_MAX_MATCH_UNENFORCED":
        gaps.append("PRICE_MAX_DECLARATION_NOT_UNCONTRADICTED")
    gaps.append("BACKEND_PRICE_ENFORCEMENT_NOT_PROVEN")
    return {
        "schema": "remix_independent_filter_evidence_v1",
        "source_provenance": (
            "SINGLE_BROWSER_REMIX_DATA_200" if verified else "UNVERIFIED"),
        "response_region_ids": fields["region"],
        "response_category": fields["category"],
        "response_available_only": fields["available"],
        "response_max_price_declaration": fields["price_max"],
        "response_price_evidence": price,
        "price_cap_enforced": False,
        "url_region_proven": False,
        "post_apply_ui_proven": False,
        "missing_independent_evidence": gaps,
        "authorizes_listings": False,
        "releases_region_mismatch": False,
        "source_body_retained": False,
    }
