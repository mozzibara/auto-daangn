# -*- coding: utf-8 -*-
"""Offline-only appraisal of archived v4.18/v4.19 price research.

Archival files are optional and are NOT in the public Git repository.
The original v4.18 export discards per-listing HMAC tokens, preventing
independent recomputation of Jaccard/repeat sets. An archived claim of
behavioral support cannot authorize today's regionless OCI collector.
This module never imports the network runner or opens a browser.
"""
from __future__ import annotations

EXPECTED = {
    ("cheonan_a", "cap_20000"): 20000,
    ("cheonan_a", "cap_50000"): 50000,
    ("cheonan_a", "cap_100000"): 100000,
    ("asan_control", "cap_50000"): 50000,
    ("cheonan_b", "cap_100000"): 100000,
    ("cheonan_b", "cap_50000"): 50000,
    ("cheonan_b", "cap_20000"): 20000,
}
_ALLOWED_TIERS = (
    "SERVER_DECLARED_AND_BEHAVIORAL",
    "BEHAVIORAL_ROUTE_CORROBORATED",
    "UI_AND_ROUTE_OBSERVED_NOT_CAUSALLY_ESTABLISHED",
    "CONTRADICTED_BY_ITEM_PRICE",
    "CONTRADICTED_BY_RESPONSE_METADATA",
    "CONTRADICTED_BY_RETURNED_PRICE_ECHO",
    "INSUFFICIENT_STRUCTURAL_EVIDENCE",
    "STOP_ACCESS_RESTRICTION",
    "INSUFFICIENT",
)
_ARCHIVE = ("NOT_PROVIDED", "PAIR_MISSING", "INVALID_STRUCTURE",
            "CONTRADICTED", "SELF_REPORTED_COMPLETE", "SELF_REPORTED_PARTIAL")
_PRICE = ("ARCHIVED_BEHAVIORAL_CLAIM_UNVERIFIABLE",
          "ARCHIVED_BEHAVIORAL_CLAIM_CONTRADICTED",
          "ARCHIVED_BEHAVIORAL_CLAIM_INCOMPLETE",
          "NOT_AVAILABLE")


def _mapping(obj):
    return obj if type(obj) is dict else {}


def _observations(report, is_v418):
    """Require exactly the source-defined seven public research profiles."""
    rows = _mapping(report).get("observations")
    if type(rows) is not list or len(rows) != len(EXPECTED):
        return None
    result = {}
    for row in rows:
        if type(row) is not dict:
            return None
        key = (row.get("context"), row.get("profile"))
        if (type(key[0]) is not str or type(key[1]) is not str
                or key not in EXPECTED or key in result
                or type(row.get("max_price_krw")) is not int
                or row["max_price_krw"] != EXPECTED[key]):
            return None
        if is_v418:
            region = "asan" if key[0] == "asan_control" else "cheonan"
            if row.get("region") != region:
                return None
            shape = _mapping(row.get("price_shape"))
            ui = _mapping(row.get("ui"))
            # Reported only; the original export does not retain tokens
            # needed to independently recompute sample-set comparisons.
            complete = (
                row.get("status") == "CAPTURED_ROUTE_AND_UI"
                and row.get("route_correlated") is True
                and row.get("observed_url_shape") is True
                and row.get("matched_ui_route_count") == 1
                and ui.get("verified_both") is True
                and ui.get("spa_maximum_krw") == EXPECTED[key]
                and ui.get("reload_maximum_krw") == EXPECTED[key]
                and type(row.get("raw_route_rows")) is int
                and row["raw_route_rows"] > 0
                and type(shape.get("raw_array_rows")) is int
                and shape["raw_array_rows"] == row["raw_route_rows"]
                and type(shape.get("unknown_price_rows")) is int
                and shape["unknown_price_rows"] == 0
                and type(shape.get("above_requested_cap")) is int
                and shape["above_requested_cap"] == 0
                and row.get("access_restricted") is not True
            )
            conflict = (
                row.get("access_restricted") is True
                or (type(shape.get("above_requested_cap")) is int
                    and shape["above_requested_cap"] > 0)
            )
        else:
            shape = _mapping(row.get("structure"))
            complete = (
                row.get("status") == "OBSERVED"
                and shape.get("status") == "OBSERVED"
                and shape.get("item_rows_not_inspected") is True
                and shape.get("response_body_persisted") is False
                and shape.get("traversal_truncated") is False
                and type(row.get("verdict")) is str
                and row["verdict"] not in (
                    "INCONCLUSIVE_TRAVERSAL_LIMIT",
                    "RAW_RESPONSE_MAX_CONFLICT",
                    "CURRENT_FILTERS_ENCODED_PRICE_ECHO_MISMATCH")
            )
            conflict = row.get("verdict") in (
                "RAW_RESPONSE_MAX_CONFLICT",
                "CURRENT_FILTERS_ENCODED_PRICE_ECHO_MISMATCH")
        result[key] = {"complete": complete, "conflict": conflict}
    return result


def audit_archived_price_reports(v418=None, v419=None):
    """Return sanitized, *non-admitting* classification only.

    Never trusts a reported positive result as independent historical
    verification or as evidence of current OCI backend price enforcement.
    """
    first, second = _mapping(v418), _mapping(v419)
    state = "NOT_PROVIDED" if not first and not second else (
        "PAIR_MISSING" if not first or not second else "INVALID_STRUCTURE")
    tier = "UNVERIFIED"
    claim = "NOT_AVAILABLE"
    if first and second:
        rows18 = _observations(first, True)
        rows19 = _observations(second, False)
        ev18 = _mapping(first.get("evaluation"))
        cross19 = _mapping(second.get("crosscheck"))
        grade19 = _mapping(second.get("independent_evidence_grade"))
        if (first.get("version") == "4.18" and second.get("version") == "4.19"
                and rows18 is not None and rows19 is not None):
            raw_tier = grade19.get("tier")
            tier = raw_tier if type(raw_tier) is str and raw_tier in _ALLOWED_TIERS else "UNVERIFIED"
            contraindication = (
                any(item["conflict"] for item in rows18.values())
                or any(item["conflict"] for item in rows19.values())
                or ev18.get("price_cap_violations") not in ([], None)
                or cross19.get("price_cap_violations") not in ([], None)
                or tier.startswith("CONTRADICTED_")
                or tier == "STOP_ACCESS_RESTRICTION"
            )
            if contraindication:
                state = "CONTRADICTED"
                claim = "ARCHIVED_BEHAVIORAL_CLAIM_CONTRADICTED"
            elif (all(item["complete"] for item in rows18.values())
                  and all(item["complete"] for item in rows19.values())
                  and ev18.get("capture_complete") is True
                  and cross19.get("capture_complete") is True
                  and ev18.get("behavioral_server_price_cap_supported") is True
                  and cross19.get("behavioral_server_price_cap_supported") is True
                  and tier in ("SERVER_DECLARED_AND_BEHAVIORAL",
                               "BEHAVIORAL_ROUTE_CORROBORATED")):
                state = "SELF_REPORTED_COMPLETE"
                claim = "ARCHIVED_BEHAVIORAL_CLAIM_UNVERIFIABLE"
            else:
                state = "SELF_REPORTED_PARTIAL"
                claim = "ARCHIVED_BEHAVIORAL_CLAIM_INCOMPLETE"

    return {
        "archival_record_status": state if state in _ARCHIVE else "INVALID_STRUCTURE",
        "archival_claim": claim if claim in _PRICE else "NOT_AVAILABLE",
        "historical_v419_tier": tier,
        "archival_provenance": "UNVERIFIED",
        "jaccard_independently_recomputable": False,
        "current_oci_price_enforcement": "NOT_PROVEN",
        "current_oci_regionless_transfer": "NOT_VALIDATED",
        "separate_live_owner_approval_required": True,
        "authorizes_listings": False,
        "collection_started": False,
        "database_written": False,
    }
