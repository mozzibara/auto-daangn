# -*- coding: utf-8 -*-
"""Observe Buy Now *without* treating shipping eligibility as remote locality.

The buy-now indicator and the article's own geographic region are separate
facts. Local Buy Now items stay eligible for further consideration after
reliable same-item locality proof. Meeting in person remains seller-dependent.
"""
from __future__ import annotations

from app_v5.listing_locality import (
    LOCAL_EXACT, LOCAL_CITY, OUTSIDE_CITY, UNVERIFIED as LOCATION_UNVERIFIED,
    sanitize_item_locality,
)

PRESENT = "BUY_NOW_VISIBLE"
NO_MARKER = "NO_BUY_NOW_UI_OBSERVED"
UNVERIFIED = "UNVERIFIED_BUY_NOW_UI"
MAX_UI_COUNT = 3500

LOCAL_RETAIN = "RETAIN_LOCAL_BUY_NOW_FOR_REVIEW"
OUTSIDE = "EXCLUDE_VERIFIED_OUT_OF_AREA"
HOLD = "HOLD_ITEM_LOCALITY_OR_BUY_NOW_PROOF"
ORDINARY = "ORDINARY_ITEM_NOT_EXCLUDED"


def classify_source_buy_now(diagnostic) -> dict:
    """Require a visible, exact primary-item label, not a generic CTA."""
    source = diagnostic if type(diagnostic) is dict else {}
    probe = source.get("probe") if type(source.get("probe")) is dict else {}
    valid = (
        source.get("role") == "SOURCE"
        and source.get("dom_capture_status") == "CAPTURED"
        and probe.get("primary_valid") is True
    )
    counts = [probe.get("primary_buy_now_label"),
              probe.get("primary_purchase_cta")]
    counts_ok = all(type(n) is int and 0 <= n <= MAX_UI_COUNT for n in counts)
    complete = (
        valid and counts_ok and probe.get("scan_complete") is True
        and probe.get("status") in (
            "DIRECT_FOR_SALE_UI", "DIRECT_OTHER_TRANSACTION_UI",
            "NO_DIRECT_FOR_SALE_UI", "AMBIGUOUS_DIRECT_UI")
    )
    # Generic "구매하기" is not synonymous with "바로구매", and neither
    # button necessarily means that direct local trade is impossible.
    explicit = valid and counts_ok and counts[0] > 0
    status = (
        PRESENT if explicit else
        NO_MARKER if complete and counts[1] == 0 else
        UNVERIFIED
    )
    return {
        "status": status,
        "buy_now_detected": status == PRESENT,
        "buyer_choice_eligible": status == NO_MARKER,
        "absence_is_location_proof": False,
        "search_region_gate_overridden": False,
        "item_location_verified": False,
        "direct_trade_confirmed": False,
        "authorizes_listings": False,
    }


def assess_local_buy_now(buy_now_status, item_locality_status) -> dict:
    """Independent buyer-choice gate; no seller meetup assumption.

    An exact current-item region/city match can retain a buy-now offer,
    but whether the seller will meet in person must still be confirmed.
    """
    region = sanitize_item_locality(item_locality_status)
    valid_marker = buy_now_status in (PRESENT, NO_MARKER)
    if region == OUTSIDE_CITY:
        decision = OUTSIDE
    elif not valid_marker:
        decision = HOLD
    elif buy_now_status == PRESENT and region in (LOCAL_EXACT, LOCAL_CITY):
        decision = LOCAL_RETAIN
    elif buy_now_status == PRESENT:
        decision = HOLD
    else:
        decision = ORDINARY
    return {
        "decision": decision,
        "item_locality_status": region,
        "retain_for_review": decision in (LOCAL_RETAIN, ORDINARY),
        "verified_local_buy_now": decision == LOCAL_RETAIN,
        "direct_trade_confirmed": False,
        "search_region_gate_overridden": False,
        "authorizes_listings": False,
    }


def assess_configured_district(buy_now_status, item_area_status, area_key=None,
                               *, area_token=None) -> dict:
    """District-specific admission; legacy city-wide status never suffices.

    Search locality and shipping toggle are independent. Unknown regions and
    malformed allowlist keys stay review-hold rather than deleted or promoted.
    """
    from app_v5.item_area_policy import (
        ALLOWED as DISTRICT_ALLOWED, OUTSIDE as DISTRICT_OUTSIDE,
        sanitize_area_status, configured_label,
    )
    area = sanitize_area_status(item_area_status)
    import re
    valid_key=(type(area_key) is str and
               configured_label(area_key) is not None)
    valid_token=(type(area_token) is str and
                 re.fullmatch(r'[a-f0-9]{20}',area_token) is not None)
    valid_witness=valid_key or valid_token
    if area == DISTRICT_OUTSIDE:
        decision = OUTSIDE
    elif area != DISTRICT_ALLOWED or not valid_witness:
        decision = HOLD
    elif buy_now_status == UNVERIFIED:
        decision = HOLD
    elif buy_now_status == PRESENT:
        decision = LOCAL_RETAIN
    elif buy_now_status == NO_MARKER:
        decision = ORDINARY
    else:
        decision = HOLD
    return {
        "decision": decision,
        "item_area_status": area,
        "area_key": area_key if valid_key and decision in
                    (LOCAL_RETAIN, ORDINARY) else None,
        "area_token": area_token if valid_token and decision in
                      (LOCAL_RETAIN, ORDINARY) else None,
        "retain_for_review": decision in (LOCAL_RETAIN, ORDINARY),
        "direct_trade_confirmed": False,
        "search_region_gate_overridden": False,
        "authorizes_listings": False,
    }
