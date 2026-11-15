# -*- coding: utf-8 -*-
"""RAM-only, bounded Route item-region histogram and paired-region comparison.

This is an observability tool, never a collection gate. Article identifiers
and URLs are HMACed using a single short-lived in-process secret; only
aggregate counts leave this module. No raw listing fields, region names,
hashes, HMAC keys, or source bodies are exported.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os

import daangn_v4_1_core as core
from app_v5.listing_locality import (
    classify_item_region, LOCAL_EXACT, LOCAL_CITY, OUTSIDE_CITY, UNVERIFIED,
)

_MAX_BODY = 2_000_000
_MAX_ROWS = 650
_KEYS = ("cheonan", "asan")
_STATES = frozenset(("COMPLETE", "EMPTY_SAMPLE", "UNOBSERVABLE",
                     "AMBIGUOUS_MODEL", "TOO_MANY_ROWS",
                     "SERVER_REGION_CONFLICT"))
_COVERAGE = frozenset(("COMPLETE", "PARTIAL", "NONE", "UNOBSERVABLE"))
_REGION_STATUS = frozenset((
    "TARGET_REGION_CONFIRMED_DIAGNOSTIC", "REGION_NOT_COMMITTED",
    "REGION_NOT_COMMITTED_AFTER_CLICK", "REGION_HEADER_ACTION_EXCEPTION",
    "REGION_OPTION_ACTION_EXCEPTION", "CLICK_NOT_TRUSTED",
    "API_OR_DOM_NOT_READY", "ACCESS_RESTRICTED", "BASELINE_INVALID",
    "UNEXPECTED_EXCEPTION", "INCONCLUSIVE",
))
_ROUTE_STATUS = frozenset((
    "ONE_FRESH", "NONE_FRESH", "MULTIPLE_FRESH", "UNREADABLE_FRESH",
))


def _target(region, *, distant_control=False):
    # The long-distance control is a distinct opt-in diagnostic only.
    if type(distant_control) is not bool or type(region) is not dict:
        return False
    keys = ("sadang",) if distant_control else _KEYS
    return any(region == core.BY_KEY[key] for key in keys)


def _blank(status):
    return {"status": status, "rows": 0,
            "local_exact": 0, "same_city": 0, "outside_city": 0,
            "unverified": 0, "location_coverage": "UNOBSERVABLE",
            "identity_coverage": "UNOBSERVABLE",
            "region_object_rows": 0, "region_name_only_rows": 0,
            "region_name_only_target_rows": 0,
            "region_name_only_other_rows": 0,
            "region_id_rows": 0, "region_city_rows": 0}


def _safe_summary(value):
    v = value if type(value) is dict else {}
    out = {k: (v[k] if type(v.get(k)) is int
               and 0 <= v[k] <= _MAX_ROWS else -1)
           for k in ("rows", "local_exact", "same_city", "outside_city",
                     "unverified", "region_object_rows",
                     "region_name_only_rows", "region_name_only_target_rows",
                     "region_name_only_other_rows", "region_id_rows",
                     "region_city_rows")}
    return {
        "status": v.get("status") if type(v.get("status")) is str
                  and v["status"] in _STATES else "UNOBSERVABLE",
        **out,
        "location_coverage": (
            v.get("location_coverage") if type(v.get("location_coverage")) is str
            and v["location_coverage"] in _COVERAGE else "UNOBSERVABLE"),
        "identity_coverage": (
            v.get("identity_coverage") if type(v.get("identity_coverage")) is str
            and v["identity_coverage"] in _COVERAGE else "UNOBSERVABLE"),
    }


def sample_region_articles(body, region, secret, *, distant_control=False):
    """Project ONE browser-observed search Route into aggregate locality bins.

    Returns ephemeral HMAC tokens to the in-process caller only; the public
    diagnostic calls `_safe_summary` before any JSON output.
    """
    if (type(body) not in (bytes, bytearray)
            or not 0 < len(body) <= _MAX_BODY
            or not _target(region, distant_control=distant_control)
            or type(secret) is not bytes or len(secret) != 32):
        return {"summary": _blank("UNOBSERVABLE"), "tokens": frozenset()}
    try:
        root = json.loads(body)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return {"summary": _blank("UNOBSERVABLE"), "tokens": frozenset()}

    candidates = []
    examined = 0

    def walk(value, depth):
        nonlocal examined
        examined += 1
        if examined > 400 or depth > 7 or len(candidates) > 1:
            return
        if type(value) is dict:
            if (type(value.get("buySellArticles")) is list
                    and type(value.get("searchRegion")) is dict
                    and type(value.get("currentFilters")) is dict):
                candidates.append(value)
            for key, child in value.items():
                if key in ("buySellArticles", "articles", "listings", "items"):
                    continue
                if type(child) in (dict, list):
                    walk(child, depth + 1)
        elif type(value) is list:
            for child in value[:30]:
                if type(child) in (dict, list):
                    walk(child, depth + 1)

    walk(root, 0)
    if examined > 400 or not candidates:
        return {"summary": _blank("UNOBSERVABLE"), "tokens": frozenset()}
    if len(candidates) != 1:
        return {"summary": _blank("AMBIGUOUS_MODEL"), "tokens": frozenset()}
    node = candidates[0]
    expected = str(region["id"])
    def matches(raw):
        return type(raw) in (str, int) and str(raw) == expected
    if (not matches(node["searchRegion"].get("id")) or
            not matches(node["currentFilters"].get("regionId"))):
        return {"summary": _blank("SERVER_REGION_CONFLICT"), "tokens": frozenset()}
    rows = node["buySellArticles"]
    if len(rows) > _MAX_ROWS:
        return {"summary": _blank("TOO_MANY_ROWS"), "tokens": frozenset()}
    if not rows:
        return {"summary": _blank("EMPTY_SAMPLE"), "tokens": frozenset()}

    counts = {LOCAL_EXACT: 0, LOCAL_CITY: 0,
              OUTSIDE_CITY: 0, UNVERIFIED: 0}
    tokens = set()
    invalid_identity = 0
    region_object_rows = region_name_only_rows = 0
    region_name_only_target_rows = region_name_only_other_rows = 0
    region_id_rows = region_city_rows = 0
    for row in rows:
        if type(row) is not dict:
            counts[UNVERIFIED] += 1
            invalid_identity += 1
            continue
        # Article-own 'region', NOT outer searchRegion/currentFilters.
        article_region = row.get("region")
        counts[classify_item_region(article_region, region)] += 1
        if type(article_region) is dict:
            region_object_rows += 1
            raw_id = article_region.get("id")
            has_id = (
                (type(raw_id) is int and 0 <= raw_id <= 999999)
                or (type(raw_id) is str and raw_id.isascii()
                    and raw_id.isdecimal() and 1 <= len(raw_id) <= 6))
            if has_id:
                region_id_rows += 1
            cities = [article_region.get(key) for key in (
                "city", "municipality", "cityName")]
            has_city = any(
                type(v) is str and 0 < len(v) <= 60
                or (type(v) is dict and type(v.get("name")) is str
                    and 0 < len(v["name"]) <= 60)
                for v in cities)
            if has_city:
                region_city_rows += 1
            name = article_region.get("name")
            # A name-only label is observational evidence, NEVER
            # proof of the municipality or exact neighborhood identity.
            if (not has_id and not has_city and type(name) is str
                    and 1 <= len(name) <= 60 and name.strip()):
                region_name_only_rows += 1
                if name.strip() == region["term"]:
                    region_name_only_target_rows += 1
                else:
                    region_name_only_other_rows += 1
        # No identifiers survive this loop: only a secret-keyed digest
        # of an explicitly normalized first-party listing href.
        href = row.get("href")
        uri = core.normalized_listing(href) if type(href) is str else None
        if uri is None:
            invalid_identity += 1
            continue
        token = hmac.digest(secret, uri.encode("utf-8"), hashlib.sha256)
        if token in tokens:
            invalid_identity += 1
        tokens.add(token)
    verified_count = len(rows) - counts[UNVERIFIED]
    return {
        "summary": {
            "status": "COMPLETE", "rows": len(rows),
            "local_exact": counts[LOCAL_EXACT],
            "same_city": counts[LOCAL_CITY],
            "outside_city": counts[OUTSIDE_CITY],
            "unverified": counts[UNVERIFIED],
            "region_object_rows": region_object_rows,
            "region_name_only_rows": region_name_only_rows,
            "region_name_only_target_rows": region_name_only_target_rows,
            "region_name_only_other_rows": region_name_only_other_rows,
            "region_id_rows": region_id_rows,
            "region_city_rows": region_city_rows,
            "location_coverage": (
                "COMPLETE" if verified_count == len(rows) else
                "NONE" if verified_count == 0 else "PARTIAL"),
            "identity_coverage": (
                "COMPLETE" if not invalid_identity and len(tokens) == len(rows)
                else "NONE" if not tokens else "PARTIAL"),
        },
        "tokens": frozenset(tokens),
    }


class RegionABSession:
    """One volatile HMAC scope for exactly two browser-initiated arms."""

    def __init__(self, *, secret=None):
        self.secret = os.urandom(32) if secret is None else secret
        if type(self.secret) is not bytes or len(self.secret) != 32:
            raise ValueError("INVALID_VOLATILE_SECRET")
        self._samples = {}

    def accept(self, key, sample, *, verified):
        if key not in _KEYS or key in self._samples:
            raise ValueError("UNEXPECTED_OR_DUPLICATE_AB_ARM")
        entry = sample if type(sample) is dict else {}
        summary = _safe_summary(entry.get("summary"))
        tokens = entry.get("tokens")
        if (verified is not True or summary["status"] != "COMPLETE"
                or type(tokens) is not frozenset
                or any(type(v) is not bytes or len(v) != 32 for v in tokens)):
            summary = _blank("UNOBSERVABLE")
            tokens = frozenset()
        self._samples[key] = (summary, tokens)

    def summarize(self, a, b):
        def arm(key, observed):
            row = observed if type(observed) is dict else {}
            status = row.get("status")
            route = row.get("route_status")
            sample = self._samples.get(key, (_blank("UNOBSERVABLE"), frozenset()))[0]
            return {
                "region": "CHEONAN_BULDANG" if key == "cheonan" else "ASAN_BAEBANG",
                "region_status": status if type(status) is str
                                  and status in _REGION_STATUS else "INCONCLUSIVE",
                "fresh_route": route if type(route) is str
                               and route in _ROUTE_STATUS else "NONE_FRESH",
                "item_sample": _safe_summary(sample),
            }

        left, right = arm("cheonan", a), arm("asan", b)
        sa, tokens_a = self._samples.get(
            "cheonan", (_blank("UNOBSERVABLE"), frozenset()))
        sb, tokens_b = self._samples.get(
            "asan", (_blank("UNOBSERVABLE"), frozenset()))
        both_region_proven = all(
            arm["region_status"] == "TARGET_REGION_CONFIRMED_DIAGNOSTIC"
            and arm["fresh_route"] == "ONE_FRESH"
            for arm in (left, right))
        usable = (both_region_proven
                  and sa["status"] == sb["status"] == "COMPLETE"
                  and sa["identity_coverage"] == sb["identity_coverage"] == "COMPLETE"
                  and bool(tokens_a) and bool(tokens_b))
        overlap = len(tokens_a & tokens_b) if usable else -1
        only_a = len(tokens_a - tokens_b) if usable else -1
        only_b = len(tokens_b - tokens_a) if usable else -1
        verdict = (
            "INDETERMINATE" if not usable else
            "SAME_SET" if only_a == 0 and only_b == 0 else
            "DISTINCT_SETS" if overlap == 0 else "PARTIAL_OVERLAP")
        return {
            "schema": "oci_region_ab_aggregate_v1",
            "status": "OBSERVED" if usable else "INCOMPLETE",
            "left": left, "right": right,
            "comparison": {
                "verdict": verdict,
                "overlap": overlap, "left_only": only_a,
                "right_only": only_b,
                "response_region_ids_distinct": both_region_proven,
                "full_result_set_proven": False,
                "backend_geographic_scope_proven": False,
            },
            "no_raw_article_data_retained": True,
            "authorizes_listings": False,
            "collection_started": False,
            "database_written": False,
            "telegram_used": False,
        }
