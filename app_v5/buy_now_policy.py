# -*- coding: utf-8 -*-
"""Strict buyer-choice policy: exclude current-item buy-now delivery offers.

This policy is independent of the *search context* locality gate.
A nationwide buy-now card can appear even in a valid local search. Conversely,
excluding those cards cannot repair a wrong searchRegion/currentFilters value.

Only bounded, item-scoped, visible UI counts may prove a buy-now exclusion.
Unknown status is not a pass. No seller location or delivery address is read.
"""
from __future__ import annotations

EXCLUDED = "EXCLUDED_BUY_NOW_OR_PURCHASE_CTA"
NO_MARKER = "NO_BUY_NOW_UI_OBSERVED"
UNVERIFIED = "UNVERIFIED_BUY_NOW_UI"
MAX_UI_COUNT = 3500


def classify_source_buy_now(diagnostic) -> dict:
    """Fail closed on incomplete or legacy v4.28 diagnostics."""
    source = diagnostic if type(diagnostic) is dict else {}
    probe = source.get("probe") if type(source.get("probe")) is dict else {}
    valid = (
        source.get("role") == "SOURCE"
        and source.get("dom_capture_status") == "CAPTURED"
        and probe.get("primary_valid") is True
    )
    # Both fields are mandatory; their provenance is the same exact primary
    # article UI.  A legacy capture lacking either cannot prove non-buy-now.
    counts = [probe.get("primary_buy_now_label"),
              probe.get("primary_purchase_cta")]
    counts_ok = all(type(n) is int and 0 <= n <= MAX_UI_COUNT for n in counts)
    marker = valid and counts_ok and any(n > 0 for n in counts)
    complete = (
        valid and counts_ok and probe.get("scan_complete") is True
        and probe.get("status") in (
            "DIRECT_FOR_SALE_UI", "DIRECT_OTHER_TRANSACTION_UI",
            "NO_DIRECT_FOR_SALE_UI", "AMBIGUOUS_DIRECT_UI")
    )
    status = EXCLUDED if marker else NO_MARKER if complete else UNVERIFIED
    return {
        "status": status,
        "buyer_choice_eligible": status == NO_MARKER,
        "buy_now_detected": status == EXCLUDED,
        "absence_is_location_proof": False,
        "search_region_gate_overridden": False,
        "item_location_verified": False,
        "authorizes_listings": False,
    }
