# -*- coding: utf-8 -*-
"""Privacy-safe *per-item* locality witness from a correlated search Route.

Never use the query's searchRegion/currentFilters as an item's own location.
Do not infer an out-of-area result merely because another neighborhood ID
differs from the selected neighborhood ID: both can belong to the same city.

Only a directly observed region object from the exact Route article is input.
The output has no raw region names, numeric IDs, addresses, or seller details.
"""
from __future__ import annotations

LOCAL_EXACT = "LOCAL_EXACT_REGION"
LOCAL_CITY = "LOCAL_SAME_CITY"
OUTSIDE_CITY = "OUTSIDE_TARGET_CITY"
UNVERIFIED = "ITEM_LOCALITY_UNVERIFIED"
ITEM_LOCALITIES = frozenset((LOCAL_EXACT, LOCAL_CITY, OUTSIDE_CITY, UNVERIFIED))

# Strict municipality labels used solely in RAM for the configured target
# research contexts; never export these mappings as observations.
_TARGET_CITY_BY_REGION_ID = {"2292": "천안시", "2333": "아산시"}


def _region_id(v):
    if type(v) is int and 0 <= v <= 999999:
        return str(v)
    if type(v) is str and v.isascii() and v.isdecimal() and 1 <= len(v) <= 6:
        return v
    return None


def _city_label(value):
    if type(value) is dict:
        value = value.get("name")
    if type(value) is not str or len(value) > 60:
        return None
    # No prefix/fuzzy matching ("천안" alone isn't enough).
    return value.strip() or None


def classify_item_region(article_region, target) -> str:
    """Conservatively classify the *article's* own region object.

    An exact region ID or explicit municipality proves in-scope locality.
    An explicit different municipality proves out-of-city. Unknown fields,
    free-form location strings, mismatched identity or conflicts do NOT.
    """
    if type(article_region) is not dict or type(target) is not dict:
        return UNVERIFIED
    region_id = _region_id(article_region.get("id"))
    expected = _region_id(target.get("id"))
    if not expected:
        return UNVERIFIED
    target_city = _TARGET_CITY_BY_REGION_ID.get(expected)
    # Municipality must be an explicit item-scoped field; text fragments
    # in title or body, the search query, delivery address aren't valid.
    names = [_city_label(article_region.get(k))
             for k in ("city", "municipality", "cityName")]
    names = [name for name in names if name]
    if len(set(names)) > 1:
        return UNVERIFIED
    city = names[0] if names else None
    if target_city and city and city != target_city:
        # A contradictory exact ID signals corrupt/ambiguous metadata, not
        # a trustworthy remote address.
        return UNVERIFIED if region_id == expected else OUTSIDE_CITY
    if region_id == expected:
        return LOCAL_EXACT
    if target_city and city == target_city:
        return LOCAL_CITY
    # Distinct neighborhood IDs do not imply distinct municipalities.
    return UNVERIFIED


def sanitize_item_locality(status):
    return status if type(status) is str and status in ITEM_LOCALITIES else UNVERIFIED
