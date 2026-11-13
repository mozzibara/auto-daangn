# -*- coding: utf-8 -*-
"""Read-only region-selection URL/Route provenance, no listing authority.

Observe only the public search page URL at pre-existing region-picker
checkpoints and the already correlated postclick browser Route response
request's region-query classification. Never save a URL, slug, key, seller,
body, browser storage, cookie, DOM text, or timestamp.
"""
from __future__ import annotations

from app_v5.region_navigation import classify_browser_url

_STAGES = (
    "BEFORE_OPTION_CLICK",
    "AFTER_OPTION_CLICK",
    "AFTER_CORE_RETURN",
    "AFTER_SETTLE",
    "BEFORE_FILTER",
)
_STATES = ("EXPECTED", "MISSING", "OTHER", "INVALID", "UNOBSERVABLE")
_FIRST = ("NOT_OBSERVED", "INCONCLUSIVE", *_STAGES)
_ROUTE = ("EXPECTED", "MISSING", "OTHER", "INVALID", "UNOBSERVABLE")


def _strict(raw, allow, default="UNOBSERVABLE"):
    return raw if type(raw) is str and raw in allow else default


def classify_page_region(url, region):
    """Check exact first-party search host/path/keyword before reading 'in'."""
    try:
        result = classify_browser_url(url, region)
        if (result.get("host") != "EXPECTED"
                or result.get("path") != "EXPECTED"
                or result.get("keyword") != "EXPECTED"):
            return "INVALID"
        return _strict(result.get("region"), _STATES)
    except (TypeError, AttributeError, ValueError):
        return "UNOBSERVABLE"


def sanitize_region_url_provenance(raw):
    data = raw if type(raw) is dict else {}
    checkpoints = (data.get("checkpoints")
                   if type(data.get("checkpoints")) is dict else {})
    return {
        "checkpoints": {
            stage: _strict(checkpoints.get(stage), _STATES)
            for stage in _STAGES
        },
        "first_observed_missing_stage": _strict(
            data.get("first_observed_missing_stage"), _FIRST,
            "INCONCLUSIVE"),
        # This is request-URL evidence linked to the selected postclick
        # server Route, and NOT a server-locality assertion.
        "fresh_route_request_region": _strict(
            data.get("fresh_route_request_region"), _ROUTE),
        "authorizes_listings": False,
    }


class RegionURLProvenance:
    def __init__(self, region):
        self.region = region
        self.observations = {}

    def checkpoint(self, stage, url):
        if stage in _STAGES:
            # Immediately reduce URL to one enum; raw URL never retained.
            self.observations[stage] = classify_page_region(url, self.region)

    def export(self, *, route_status="NONE_FRESH",
               postclick_route=None):
        route = "UNOBSERVABLE"
        if (route_status == "ONE_FRESH"
                and type(postclick_route) is dict):
            route = _strict(postclick_route.get("request_region"), _ROUTE)
        # The first *observed* missing stage is not necessarily the
        # causal mutation point. Missing gaps are inconclusive.
        prior_ambiguous = False
        first = "INCONCLUSIVE"
        seen = False
        for stage in _STAGES:
            value = self.observations.get(stage, "UNOBSERVABLE")
            if value == "MISSING":
                first = "INCONCLUSIVE" if prior_ambiguous else stage
                seen = True
                break
            if value != "EXPECTED":
                prior_ambiguous = True
        if not seen and not prior_ambiguous:
            first = "NOT_OBSERVED"
        return sanitize_region_url_provenance({
            "checkpoints": self.observations,
            "first_observed_missing_stage": first,
            "fresh_route_request_region": route,
        })
