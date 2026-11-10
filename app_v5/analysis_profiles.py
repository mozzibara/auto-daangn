# -*- coding: utf-8 -*-
"""Versioned, deterministic product-analysis profiles for pre-OCI alerts.

No marketplace/network calls, LLM, implicit SMART extraction or real prices.
Supplied metadata is never treated as authenticated just because the PRICE event
was signed. Add future keyword analyzers via ANALYZERS, not HDD-specific SQL.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Mapping


@dataclass(frozen=True)
class ProductFacts:
    keyword: str
    previous_price_krw: int
    price_krw: int
    capacity_tb: Decimal | None = None
    capacity_provenance: str = "unknown"  # seller_reported/independent_measurement
    smart_raw: Mapping[int, int] | None = None
    smart_provenance: str = "unknown"  # unknown/seller_reported/independent_measurement


@dataclass(frozen=True)
class SearchProfile:
    """Explicit keyword -> product analyzer routing for future categories."""
    profile_id: str
    keyword: str
    analyzer_id: str = "generic"


@dataclass(frozen=True)
class AnalysisResult:
    profile: str
    score: int  # deterministic ordering heuristic, NOT failure probability
    priority: str
    price_drop_pct: Decimal
    price_per_tb_krw: int | None
    breakdown: dict[str, int]
    confidence: str
    warnings: tuple[str, ...]
    version: str = "pre-oci-1"


def _validate(facts: ProductFacts) -> Decimal:
    if (type(facts.previous_price_krw) is not int
            or type(facts.price_krw) is not int
            or not 0 < facts.price_krw < facts.previous_price_krw <= 1_000_000_000):
        raise ValueError("VERIFIED_PRICE_DROP_REQUIRED")
    if not isinstance(facts.keyword, str) or not 1 <= len(facts.keyword.strip()) <= 100:
        raise ValueError("PROFILE_KEYWORD_REQUIRED")
    if facts.capacity_provenance not in (
            "unknown", "seller_reported", "independent_measurement"):
        raise ValueError("INVALID_CAPACITY_PROVENANCE")
    if facts.capacity_tb is not None:
        if (facts.capacity_provenance == "unknown"
                or not isinstance(facts.capacity_tb, Decimal)
                or not facts.capacity_tb.is_finite()
                or not Decimal("0") < facts.capacity_tb <= Decimal("1000")):
            raise ValueError("INVALID_HDD_CAPACITY")
    elif facts.capacity_provenance != "unknown":
        raise ValueError("CAPACITY_SOURCE_WITHOUT_VALUE")
    if facts.smart_provenance not in (
            "unknown", "seller_reported", "independent_measurement"):
        raise ValueError("INVALID_SMART_PROVENANCE")
    if facts.smart_raw is not None:
        if (not isinstance(facts.smart_raw, Mapping)
                or not facts.smart_raw or facts.smart_provenance == "unknown"):
            raise ValueError("UNTRUSTED_SMART_SOURCE")
        if any(type(k) is not int or type(v) is not int or not 0 <= v <= 2**48-1
               for k, v in facts.smart_raw.items()):
            raise ValueError("INVALID_SMART_RAW_VALUE")
    elif facts.smart_provenance != "unknown":
        raise ValueError("SMART_SOURCE_WITHOUT_VALUES")
    return (Decimal(facts.previous_price_krw - facts.price_krw)
            / Decimal(facts.previous_price_krw) * 100).quantize(Decimal("0.01"))


def _drop_score(pct: Decimal) -> int:
    # 20% drop -> 30 points max; no discount alone constitutes an auto-buy.
    return min(30, int(pct * Decimal("1.5")))


def _generic(facts: ProductFacts, pct: Decimal) -> AnalysisResult:
    score = _drop_score(pct)
    return AnalysisResult(
        profile="generic", score=score, priority="REVIEW",
        price_drop_pct=pct, price_per_tb_krw=None,
        breakdown={"price_drop": score, "category_value": 0,
                   "category_condition": 0, "evidence": 0},
        confidence="INSUFFICIENT_CATEGORY_EVIDENCE",
        warnings=("KEYWORD_SPECIFIC_ANALYZER_NOT_CONFIGURED",)
    )


_SMART_RISK = {5: "REALLOCATED_SECTORS", 187: "REPORTED_UNCORRECTABLE",
               188: "COMMAND_TIMEOUT", 197: "PENDING_SECTORS",
               198: "OFFLINE_UNCORRECTABLE"}
_SMART_REQUIRED = frozenset(_SMART_RISK)


def _hdd(facts: ProductFacts, pct: Decimal) -> AnalysisResult:
    warnings: list[str] = []
    drop = _drop_score(pct)
    price_per_tb = None
    value = 0
    if facts.capacity_tb is None:
        warnings.append("HDD_CAPACITY_UNKNOWN")
    else:
        if facts.capacity_provenance == "seller_reported":
            warnings.append("HDD_CAPACITY_SELLER_REPORTED_NOT_VERIFIED")
        ratio = Decimal(facts.price_krw) / facts.capacity_tb
        price_per_tb = int(ratio.to_integral_value(rounding="ROUND_HALF_UP"))
        # Explicit illustrative thresholds, NOT an assertion of current market.
        if ratio <= 15000:
            value = 30
        elif ratio <= 25000:
            value = 24
        elif ratio <= 40000:
            value = 16
        elif ratio <= 60000:
            value = 8
    health = 0
    confidence = 0
    critical = False
    coverage_complete = False
    if facts.smart_raw is None:
        warnings.append("SMART_UNAVAILABLE")
    else:
        data = facts.smart_raw
        coverage_complete = _SMART_REQUIRED.issubset(data)
        if not coverage_complete:
            warnings.append("SMART_CRITICAL_FIELDS_INCOMPLETE")
        for attribute, name in _SMART_RISK.items():
            if data.get(attribute, 0) > 0:
                critical = True
                warnings.append("SMART_" + name + "_NONZERO_REVIEW")
        if data.get(199, 0) > 0:
            warnings.append("SMART_UDMA_CRC_REVIEW_CABLE_OR_INTERFACE")
        if 9 not in data:
            warnings.append("SMART_POWER_ON_HOURS_UNKNOWN")
        else:
            hours = data[9]
            if hours >= 40000:
                warnings.append("SMART_LONG_POWER_ON_HOURS")
            elif hours >= 20000:
                warnings.append("SMART_MODERATE_POWER_ON_HOURS")
        if not critical and coverage_complete:
            health = 25
            if data.get(9, 0) >= 40000:
                health -= 8
            elif data.get(9, 0) >= 20000:
                health -= 4
        confidence = (15 if facts.smart_provenance == "independent_measurement"
                      else 6)
        if facts.smart_provenance == "seller_reported":
            warnings.append("SMART_SELLER_REPORTED_NOT_INDEPENDENTLY_VERIFIED")
    score = drop + value + health + confidence
    if not coverage_complete or facts.capacity_tb is None:
        score = min(score, 55)
    if critical:
        priority = "RISK_REVIEW"
    elif (not coverage_complete
          or facts.smart_provenance != "independent_measurement"
          or facts.capacity_provenance != "independent_measurement"):
        priority = "NEEDS_EVIDENCE"
    elif score >= 80:
        priority = "HIGH_REVIEW"
    elif score >= 60:
        priority = "MEDIUM_REVIEW"
    else:
        priority = "LOW_REVIEW"
    return AnalysisResult(
        profile="hdd", score=score, priority=priority,
        price_drop_pct=pct, price_per_tb_krw=price_per_tb,
        breakdown={"price_drop": drop, "category_value": value,
                   "category_condition": health, "evidence": confidence},
        confidence=("MEASURED_SMART" if facts.smart_provenance ==
                    "independent_measurement" else "UNVERIFIED_SMART"),
        warnings=tuple(warnings)
    )


ANALYZERS: dict[str, Callable[[ProductFacts, Decimal], AnalysisResult]] = {
    "generic": _generic,
    "hdd": _hdd,
}


def analyze(profile: str, facts: ProductFacts) -> AnalysisResult:
    """Explicit profile selection; unknown keyword defaults to generic safely."""
    pct = _validate(facts)
    selected = ANALYZERS.get(profile, _generic)
    return selected(facts, pct)


def analyze_for_profile(profile: SearchProfile,
                        facts: ProductFacts) -> AnalysisResult:
    """No automatic HDD assumptions solely because a keyword contains 'HDD'."""
    if (not isinstance(profile, SearchProfile)
            or not profile.profile_id.strip()
            or not profile.keyword.strip()
            or profile.keyword != facts.keyword):
        raise ValueError("SEARCH_PROFILE_MISMATCH")
    if profile.analyzer_id not in ANALYZERS:
        raise ValueError("UNKNOWN_CONFIGURED_ANALYZER")
    return analyze(profile.analyzer_id, facts)
