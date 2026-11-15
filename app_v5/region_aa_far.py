# -*- coding: utf-8 -*-
"""Volatile three-arm A1/FAR/A2 cohort comparison, for OCI diagnostics only.

Distinct browser contexts independently select Buldang, Seoul Sadang3 and
Buldang. Each fresh, region-corroborated Route is reduced to per-item locality
counts and random-key HMACs in memory. Neither identity nor digest is emitted.
Two A/A searches give ONE observed noise baseline, not a confidence interval.
No part of this report approves marketplace collection or price enforcement.
"""
from __future__ import annotations

import os

from app_v5.region_ab_sample import (
    _blank, _safe_summary, _REGION_STATUS, _ROUTE_STATUS,
)

_ARMS = ("a1", "far", "a2")
_LABELS = {"a1": "BULDANG_BEFORE", "far": "SEOUL_SADANG3",
           "a2": "BULDANG_AFTER"}
_PAIRS = {"aa": ("a1", "a2"),
          "a1_far": ("a1", "far"),
          "a2_far": ("a2", "far")}


def _observation_status(row):
    data = row if type(row) is dict else {}
    status = data.get("status")
    route = data.get("route_status")
    return {
        "region_status": (status if type(status) is str
                          and status in _REGION_STATUS else "INCONCLUSIVE"),
        "fresh_route": (route if type(route) is str
                        and route in _ROUTE_STATUS else "NONE_FRESH"),
    }


def _pair(left, right, *, valid=False):
    if not valid:
        return {
            "verdict": "INDETERMINATE", "overlap": -1,
            "left_only": -1, "right_only": -1,
            "symmetric_difference": -1, "union": -1,
            "jaccard": None,
        }
    both = len(left & right)
    only_l = len(left - right)
    only_r = len(right - left)
    total = both + only_l + only_r
    return {
        "verdict": (
            "SAME_SET" if only_l == 0 and only_r == 0 else
            "DISJOINT" if both == 0 else "PARTIAL_OVERLAP"
        ),
        "overlap": both, "left_only": only_l, "right_only": only_r,
        "symmetric_difference": only_l + only_r, "union": total,
        "jaccard": round(both / total, 6) if total else None,
    }


class RegionAAFarSession:
    """Only exactly three named independent arm results may be compared."""

    def __init__(self, *, secret=None):
        self.secret = os.urandom(32) if secret is None else secret
        if type(self.secret) is not bytes or len(self.secret) != 32:
            raise ValueError("INVALID_VOLATILE_SECRET")
        self._samples = {}

    def accept(self, key, sample, *, verified):
        if key not in _ARMS or key in self._samples:
            raise ValueError("UNEXPECTED_OR_DUPLICATE_AA_FAR_ARM")
        value = sample if type(sample) is dict else {}
        summary = _safe_summary(value.get("summary"))
        tokens = value.get("tokens")
        if (verified is not True or summary["status"] != "COMPLETE"
                or summary["identity_coverage"] != "COMPLETE"
                or type(tokens) is not frozenset or not tokens
                or len(tokens) != summary["rows"]
                or any(type(t) is not bytes or len(t) != 32 for t in tokens)):
            tokens = frozenset()
            # Keep only a sanitized reason, never unsupported identity proof.
            if summary["status"] == "COMPLETE":
                summary["identity_coverage"] = "PARTIAL"
        self._samples[key] = (summary, tokens)

    def report(self, observations):
        obs = observations if type(observations) is dict else {}
        arms = {}
        usable = {}
        for name in _ARMS:
            state = _observation_status(obs.get(name))
            summary, tokens = self._samples.get(
                name, (_blank("UNOBSERVABLE"), frozenset()))
            state["region"] = _LABELS[name]
            state["item_sample"] = _safe_summary(summary)
            arms[name] = state
            usable[name] = (
                state["region_status"] == "TARGET_REGION_CONFIRMED_DIAGNOSTIC"
                and state["fresh_route"] == "ONE_FRESH"
                and summary["status"] == "COMPLETE"
                and summary["identity_coverage"] == "COMPLETE"
                and bool(tokens)
                and len(tokens) == summary["rows"]
            )

        pairs = {}
        for name, (left, right) in _PAIRS.items():
            tokens_l = self._samples.get(left, ({}, frozenset()))[1]
            tokens_r = self._samples.get(right, ({}, frozenset()))[1]
            pairs[name] = _pair(tokens_l, tokens_r,
                                valid=usable[left] and usable[right])

        complete = all(usable.values())
        aa = pairs["aa"]["symmetric_difference"]
        r1 = pairs["a1_far"]["symmetric_difference"]
        r2 = pairs["a2_far"]["symmetric_difference"]
        far_min = min(r1, r2) if complete else -1
        verdict = (
            "INDETERMINATE" if not complete else
            "FAR_EXCEEDS_OBSERVED_AA_DRIFT" if far_min > aa else
            "FAR_WITHIN_OBSERVED_AA_DRIFT"
        )
        return {
            "schema": "oci_region_aa_far_aggregate_v1",
            "status": "OBSERVED" if complete else "INCOMPLETE",
            "execution_order": "BULDANG_SADANG_BULDANG",
            "arms": arms,
            "pairs": pairs,
            "contrast": {
                "verdict": verdict,
                "aa_drift_count": aa,
                "far_min_difference": far_min,
                "server_region_ids_distinct": complete,
                "backend_geographic_scope_proven": False,
                "causal_region_filter_proven": False,
                "statistical_significance_proven": False,
                "all_marketplace_results_observed": False,
            },
            "ephemeral_identity_scope": "ONE_RUN_ONLY",
            "authorizes_listings": False,
            "collection_started": False,
            "database_written": False,
            "telegram_used": False,
        }
