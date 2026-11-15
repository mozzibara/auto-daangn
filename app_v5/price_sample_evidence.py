# -*- coding: utf-8 -*-
"""One opt-in price-field-only sample from an existing, attested Remix body.

Only the numeric 'price' scalar of each bounded article is inspected in RAM.
Never retains listings, IDs, URLs, sellers, titles, raw amounts or bodies.
This single response can falsify a claimed cap, NEVER prove enforcement.
"""
from __future__ import annotations

import json

MAX_BODY = 2_000_000
MAX_ROWS = 650
_VERDICTS = frozenset({
    "UNOBSERVABLE", "AMBIGUOUS_MODEL", "EMPTY_SAMPLE", "TOO_MANY_ROWS",
    "INCOMPLETE_PRICE_COVERAGE", "ABOVE_CAP_OBSERVED", "SAMPLE_WITHIN_CAP",
})


def inspect_bounded_price_sample(blob, *, cap=50000):
    if (type(blob) not in (bytes, bytearray) or not 0 < len(blob) <= MAX_BODY
            or type(cap) is not int or cap != 50000):
        return "UNOBSERVABLE"
    try:
        root = json.loads(blob)
    except (ValueError, UnicodeError, TypeError):
        return "UNOBSERVABLE"
    matches = []
    visited = 0

    def walk(node, depth=0):
        nonlocal visited
        visited += 1
        if visited > 400 or depth > 7 or len(matches) > 1:
            return
        if type(node) is dict:
            if (type(node.get("buySellArticles")) is list
                    and type(node.get("searchRegion")) is dict
                    and type(node.get("currentFilters")) is dict):
                matches.append(node["buySellArticles"])
            for key, value in node.items():
                if key in ("buySellArticles", "articles", "listings", "items"):
                    continue
                if type(value) in (list, dict):
                    walk(value, depth + 1)
        elif type(node) is list:
            for child in node[:30]:
                if type(child) in (dict, list):
                    walk(child, depth + 1)

    walk(root)
    if visited > 400 or len(matches) == 0:
        return "UNOBSERVABLE"
    if len(matches) != 1:
        return "AMBIGUOUS_MODEL"
    rows = matches[0]
    if len(rows) > MAX_ROWS:
        return "TOO_MANY_ROWS"
    if not rows:
        return "EMPTY_SAMPLE"
    unknown = False
    above = False
    for row in rows:
        if type(row) is not dict:
            unknown = True
            continue
        value = row.get("price")
        if type(value) is int and 0 <= value < 1_000_000_000:
            amount = value
        elif (type(value) is str and value.isascii()
              and value.isdecimal() and 1 <= len(value) <= 9):
            amount = int(value)
        else:
            unknown = True
            continue
        if amount > cap:
            above = True
    if above:
        return "ABOVE_CAP_OBSERVED"
    if unknown:
        return "INCOMPLETE_PRICE_COVERAGE"
    return "SAMPLE_WITHIN_CAP"


def attest_bounded_price_sample(precollection):
    from app_v5.remix_independent_evidence import independent_remix_evidence

    row = precollection if type(precollection) is dict else {}
    opt_in = row.get("dynamic_price_sample_mode") is True
    provenance = independent_remix_evidence(row).get("source_provenance")
    source_ok = opt_in and provenance == "SINGLE_BROWSER_REMIX_DATA_200"
    raw = row.get("dynamic_price_sample_verdict")
    verdict = (
        "NOT_REQUESTED" if not opt_in else
        raw if source_ok and type(raw) is str and raw in _VERDICTS
        else "UNVERIFIED"
    )
    return {
        "schema": "bounded_price_sample_evidence_v1",
        "source_provenance": provenance if source_ok else "UNVERIFIED",
        "sample_verdict": verdict,
        "price_cap_enforced": False,
        "causal_control_observed": False,
        "authorizes_listings": False,
        "listing_identity_retained": False,
        "requires_independent_control": True,
    }
