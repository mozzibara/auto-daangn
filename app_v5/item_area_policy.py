# -*- coding: utf-8 -*-
"""Verified, configurable municipality + dong/eup/myeon admission.

Read only a SAME-LISTING first-party Route row's own 'region' object.
No address geocoding, fuzzy text, searchRegion substitution, or region-ID
arithmetic. Only finite status enums leave the public capture pipeline.
Allowlist keys can enter a sealed owner-only manifest after exact identity
and cross-context consistency checks.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

SCHEMA = "daangn_item_area_allowlist_v1"
CONFIG = Path(__file__).resolve().parents[1] / "config" / "item_area_allowlist.json"
ALLOWED = "ITEM_DISTRICT_ALLOWED"
OUTSIDE = "ITEM_DISTRICT_OUTSIDE_ALLOWLIST"
UNKNOWN = "ITEM_DISTRICT_UNVERIFIED"
STATUSES = frozenset((ALLOWED, OUTSIDE, UNKNOWN))
_CITY = frozenset(("천안시", "아산시"))
_KEY = re.compile(r"^[a-z][a-z0-9_]{2,47}$")
_DISTRICT = re.compile(r"^[가-힣0-9]{2,18}(?:동|읍|면)$")


def _id(value):
    if type(value) is int and 1 <= value <= 999999:
        return str(value)
    if type(value) is str and value.isascii() and value.isdecimal() and (
            1 <= len(value) <= 6 and int(value) > 0):
        return str(int(value))
    return None


def _name(value):
    if type(value) is dict:
        value = value.get("name")
    if type(value) is str and 1 <= len(value) <= 60:
        return value.strip()
    return None


def _one(values):
    """None denotes unavailable or conflicting evidence, not an empty string."""
    observed = [v for v in values if v is not None]
    if not observed or len(set(observed)) != 1:
        return None
    return observed[0]


def load_allowlist(path=None):
    """Reject ambiguous, overly broad, or malformed configuration."""
    source = Path(path) if path is not None else CONFIG
    try:
        doc = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError("ITEM_AREA_CONFIG_UNREADABLE") from exc
    if type(doc) is not dict or set(doc) != {"schema", "allowed_areas"} or (
            doc["schema"] != SCHEMA or type(doc["allowed_areas"]) is not list or
            not 1 <= len(doc["allowed_areas"]) <= 100):
        raise ValueError("ITEM_AREA_CONFIG_SCHEMA_INVALID")
    seen_keys, seen_pairs, seen_ids = set(), set(), set()
    areas = []
    for entry in doc["allowed_areas"]:
        if type(entry) is not dict or set(entry) != (
                {"key", "city", "district", "region_id"}):
            raise ValueError("ITEM_AREA_CONFIG_ENTRY_INVALID")
        key, city, district, raw_id = (
            entry["key"], entry["city"], entry["district"], entry["region_id"])
        rid = None if raw_id is None else _id(raw_id)
        if (type(key) is not str or not _KEY.fullmatch(key) or
                type(city) is not str or city not in _CITY or
                type(district) is not str or not _DISTRICT.fullmatch(district) or
                (raw_id is not None and rid is None) or
                key in seen_keys or (city, district) in seen_pairs or
                (rid is not None and rid in seen_ids)):
            raise ValueError("ITEM_AREA_CONFIG_CONFLICT")
        seen_keys.add(key)
        seen_pairs.add((city, district))
        if rid is not None:
            seen_ids.add(rid)
        areas.append({"key": key, "city": city,
                      "district": district, "region_id": rid})
    # No glob, city-wide wildcard, unknown city, or implicit radius is allowed.
    return tuple(areas)


def configured_label(key, policy=None):
    """Owner-facing only; never include this in a public listing artifact."""
    if type(key) is not str:
        return None
    matches = [a for a in (policy if policy is not None else load_allowlist())
               if a["key"] == key]
    return (matches[0]["city"] + " " + matches[0]["district"]
            if len(matches) == 1 else None)


def classify_area(article_region, policy):
    """Return only verified area key or status (no raw source values).

    Valid positive proof:
      - an allowlisted, pinned item region ID with no conflicting fields; or
      - explicit structured municipality + leaf dong/eup/myeon, with a
        missing ID or unpinned config entry (never override a pinned mismatch).

    An explicitly different structured municipality or leaf within a known
    municipality may be excluded; incomplete/contradictory evidence is HELD.
    """
    def result(status, key=None):
        return {"status": status, "area_key": key if status == ALLOWED else None,
                "item_location_verified": status in (ALLOWED, OUTSIDE),
                "search_region_gate_overridden": False,
                "direct_trade_confirmed": False, "authorizes_listings": False}

    if type(article_region) is not dict or not isinstance(policy, (tuple, list)):
        return result(UNKNOWN)
    if not policy or any(type(a) is not dict for a in policy):
        return result(UNKNOWN)
    rid = _id(article_region.get("id"))
    # Reject malformed or out-of-domain claimed ID rather than quietly
    # turning it into an unknown ID accepted via text.
    if article_region.get("id") is not None and rid is None:
        return result(UNKNOWN)
    city_values = []
    for key in ("city", "municipality", "cityName"):
        if key in article_region:
            city_values.append(_name(article_region[key]))
    district_values = []
    for key in ("district", "neighborhood", "dongName", "name"):
        if key in article_region:
            district_values.append(_name(article_region[key]))
    # Explicit fields that cannot be normalized are conflicts, never absence.
    if (any(v is None for v in city_values) or
            any(v is None for v in district_values)):
        return result(UNKNOWN)
    city = _one(city_values)
    leaf = _one(district_values)
    if len(set(city_values)) > 1 or len(set(district_values)) > 1:
        return result(UNKNOWN)
    if leaf is not None and not _DISTRICT.fullmatch(leaf):
        return result(UNKNOWN)
    id_match = [a for a in policy if a.get("region_id") == rid] if rid else []
    if len(id_match) > 1:
        return result(UNKNOWN)
    if id_match:
        area = id_match[0]
        if (city is not None and city != area["city"]) or (
                leaf is not None and leaf != area["district"]):
            return result(UNKNOWN)
        return result(ALLOWED, area["key"])
    if city is not None and leaf is not None:
        pair = [a for a in policy if a["city"] == city and
                a["district"] == leaf]
        if len(pair) == 1:
            area = pair[0]
            # Never accept a stale/mismatched item ID just on a name match.
            if rid is not None and area["region_id"] is not None:
                return result(UNKNOWN)
            return result(ALLOWED, area["key"])
        if not pair:
            return result(OUTSIDE)
    # A different *explicit municipality* is sufficient for outside,
    # but don't derive it from name-only or a different neighborhood ID.
    if city is not None and city not in {a["city"] for a in policy}:
        return result(OUTSIDE)
    return result(UNKNOWN)


def sanitize_area_status(value):
    return value if type(value) is str and value in STATUSES else UNKNOWN
