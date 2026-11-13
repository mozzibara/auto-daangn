# -*- coding: utf-8 -*-
"""Non-admitting, purely offline summary of OCI precollection evidence.

Uses only existing finite, sanitized evidence. No browser, network,
response-body parsing, listing access, persistence or authorization.
Historical v4.19 distinguishes encoded price-query echoes from
independent backend maximum-price enforcement; preserve that boundary.
"""
from __future__ import annotations

_RESPONSE_KEYS = ("region", "category", "available")
_RESPONSE_VERDICTS = ("EXPECTED", "OTHER", "MISSING", "AMBIGUOUS")
_LOCALITY = ("EXPECTED", "MISSING", "OTHER", "DUPLICATE", "UNOBSERVABLE")
_POST_UI = ("NOT_RUN", "OBSERVED_MATCH", "OBSERVED_MISMATCH",
            "PARTIAL_OBSERVATION", "NOT_OBSERVABLE")
_PRICE_DECLARATION = (
    "DECLARED_MAX_MATCH", "DECLARED_MAX_MISMATCH",
    "DECLARED_MAX_AMBIGUOUS", "ENCODED_ECHO_MATCH_ONLY",
    "ENCODED_ECHO_MISMATCH", "ENCODED_ECHO_UNRECOGNIZED",
    "NO_INDEPENDENT_MAX", "UNVERIFIED",
)
# These are always required independently from an echoed query value.
# None of these gates is waived by this evidence summary.
_HARD_GAPS = (
    "URL_REGION_NOT_VERIFIED",
    "BACKEND_PRICE_ENFORCEMENT_UNPROVEN",
    "POST_APPLY_UI_NOT_VERIFIED",
)


def _mapping(v):
    return v if type(v) is dict else {}


def _choice(v, allowed, default):
    return v if type(v) is str and v in allowed else default


def summarize_precollection_evidence(precollection):
    """Advisory finite-state ledger, never a new permission evaluator.

    The caller must pass sanitized_precollection fields, not raw network
    data. Every positive post-Apply server observation additionally needs
    a single same-window GET fetch/xhr 200 and one parsed dynamic loader.
    """
    row = _mapping(precollection)
    network = _mapping(row.get("filter_transport_diagnostics"))
    request = _mapping(row.get("apply_search_request_diagnostics"))
    request_url = _mapping(request.get("request_url"))
    response_url = _mapping(request.get("response_url"))
    request_fields = _mapping(request_url.get("fields"))
    response_fields = _mapping(response_url.get("fields"))
    body = _mapping(row.get("dynamic_loader_server_filters"))

    # A URL or response-body field by itself cannot assert it belongs to
    # the sole Apply-initiated search. Do not select a favorable response.
    single_transport = (
        network.get("search_requests") == 1
        and network.get("search_responses") == 1
        and network.get("search_request_failures") == 0
        and network.get("search_response_restricted") == 0
        and network.get("search_response_200") == 1
        and request.get("observation") == "ONE_OBSERVED"
        and request.get("method") == "GET"
        and request.get("transport") == "FETCH_OR_XHR"
        and request.get("outcome") == "HTTP_200"
        and all(
            request_fields.get(k) == response_fields.get(k) == "EXPECTED"
            for k in ("keyword", "category", "price_max", "available")
        )
    )
    parsed = (
        single_transport
        and row.get("dynamic_loader_metadata_mode") is True
        and row.get("dynamic_loader_metadata_count") == 1
        and row.get("dynamic_loader_metadata_status") == "ONE_PARSED"
    )

    server = {
        key: _choice(body.get(key), _RESPONSE_VERDICTS, "UNVERIFIED")
             if parsed else "UNVERIFIED"
        for key in _RESPONSE_KEYS
    }
    source = row.get("dynamic_loader_price_shape")
    echo = row.get("dynamic_loader_price_echo")
    max_state = body.get("price_max")
    price = "UNVERIFIED"
    if parsed:
        if source in ("DIRECT_ALIAS", "NESTED_PRICE_RANGE_MAX"):
            if max_state == "EXPECTED":
                price = "DECLARED_MAX_MATCH"
            elif max_state == "OTHER":
                price = "DECLARED_MAX_MISMATCH"
            else:
                price = "DECLARED_MAX_AMBIGUOUS"
        elif source == "MULTIPLE_PRICE_SOURCES" or max_state == "AMBIGUOUS":
            price = "DECLARED_MAX_AMBIGUOUS"
        elif source == "UNTRUSTED_PRICE_ONLY" and max_state == "MISSING":
            if echo == "ENCODED_MAX_MATCH":
                price = "ENCODED_ECHO_MATCH_ONLY"
            elif echo == "ENCODED_MAX_OTHER":
                price = "ENCODED_ECHO_MISMATCH"
            else:
                price = "ENCODED_ECHO_UNRECOGNIZED"
        else:
            price = "NO_INDEPENDENT_MAX"

    locality = _choice(
        _mapping(_mapping(row.get("filtered_url_diagnostics")).get(
            "fields")).get("region"),
        _LOCALITY, "UNOBSERVABLE"
    )
    ui = _choice(row.get("ui_after_apply_recheck_state"),
                 _POST_UI, "NOT_RUN")
    # Hard gaps are explanatory only. Even if empty, listing permission
    # remains false and is controlled by entirely separate code.
    gaps = []
    if locality != "EXPECTED":
        gaps.append(_HARD_GAPS[0])
    # A declared max is not a causal backend enforcement experiment.
    gaps.append(_HARD_GAPS[1])
    if ui != "OBSERVED_MATCH":
        gaps.append(_HARD_GAPS[2])

    # When the requested price has already been echoed, repeating exactly
    # that single response shape cannot establish new backend enforcement.
    same_scope = (
        "ECHO_ONLY_CANNOT_PROVE_ENFORCEMENT"
        if parsed and price == "ENCODED_ECHO_MATCH_ONLY"
        else "UNDETERMINED"
    )
    return {
        "region_selection": (
            "SERVER_CONFIRMED"
            if row.get("region_gate_confirmed") is True
            else "UNVERIFIED"),
        "apply_request": (
            "SINGLE_MATCHING_SEARCH_HTTP_200"
            if single_transport else "NOT_PROVEN_UNIQUE_MATCHING"),
        "filtered_server_metadata": server,
        "response_price_evidence": _choice(
            price, _PRICE_DECLARATION, "UNVERIFIED"),
        "backend_price_enforcement": "NOT_PROVEN",
        "url_region": locality,
        "post_apply_ui": ui,
        "remaining_independent_gaps": gaps,
        "same_scope_repeat": same_scope,
        "authorizes_listings": False,
    }
