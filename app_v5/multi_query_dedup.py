# -*- coding: utf-8 -*-
"""Aggregate independently validated keyword captures with SAME-RUN item IDs.

No network, URLs, titles, or fuzzy identity matching. The 20-hex HMAC must
be produced using the *same random key for all keywords in the capture*.
Different captures use different keys and cannot be HMAC-joined.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from app_v5.query_expansion import ValidatedPlan, MAX_SOURCE_VISITS

TOKEN = re.compile(r"[a-f0-9]{20}\Z")
RUN = re.compile(r"[A-Za-z0-9_.:-]{1,80}\Z")
STATUSES = frozenset({"COMPLETE", "PARTIAL", "BLOCKED"})
RELEVANCE = frozenset({"RELEVANT", "IRRELEVANT", "UNKNOWN"})


@dataclass(frozen=True)
class Observation:
    listing_run_hmac: str | None
    price_krw: int
    rank: int
    relevance: str
    source_verified: bool


@dataclass(frozen=True)
class QueryCapture:
    query_id: str
    run_id: str
    status: str
    visits_spent: int
    rows: tuple[Observation, ...]


@dataclass(frozen=True)
class QueryYield:
    query_id: str
    observed: int
    relevant_exclusive: int
    relevant_shared: int
    irrelevant: int
    unknown: int


@dataclass(frozen=True)
class DedupResult:
    run_id: str
    plan_sha256: str
    status: str
    raw_observations: int
    unique_listings: int
    duplicate_observations_removed: int
    quarantined_groups: int
    quarantined_observations: int
    visits_spent: int
    per_query: tuple[QueryYield, ...]
    # Private in-memory run-scoped pseudonyms only; never log/upload these.
    unique_run_hmacs: tuple[str, ...]


def aggregate_one_run(plan: ValidatedPlan,
                      captures: tuple[QueryCapture, ...]) -> DedupResult:
    """Fail-closed on false provenance and unsupported/unvisited query scopes."""
    if not isinstance(plan, ValidatedPlan) or type(captures) is not tuple:
        raise ValueError("INVALID_CAPTURE_PLAN")
    if len(captures) != len(plan.active) or not captures:
        raise ValueError("ALL_ACTIVE_QUERIES_REQUIRE_EXPLICIT_STATUS")
    expected = {x.query_id for x in plan.active}
    observed_query_ids = [x.query_id for x in captures]
    if set(observed_query_ids) != expected or len(set(observed_query_ids)) != len(captures):
        raise ValueError("UNAUTHORIZED_OR_DUPLICATE_QUERY_CAPTURE")
    run_ids = {x.run_id for x in captures}
    if len(run_ids) != 1 or not RUN.fullmatch(next(iter(run_ids))):
        raise ValueError("CROSS_RUN_HMAC_MERGE_FORBIDDEN")
    run_id = next(iter(run_ids))
    total_visits = 0
    all_rows: dict[str, list[tuple[str, Observation]]] = {}
    missing_identity = False
    stats = {q.query_id: {"observed": 0, "irrelevant": 0, "unknown": 0}
             for q in plan.active}
    for capture in captures:
        if (not isinstance(capture.status, str) or capture.status not in STATUSES
                or type(capture.visits_spent) is not int
                or not 0 <= capture.visits_spent <= 3
                or not isinstance(capture.rows, tuple) or len(capture.rows) > 50):
            raise ValueError("INVALID_QUERY_CAPTURE")
        if capture.status == "BLOCKED" and capture.rows:
            raise ValueError("BLOCKED_QUERY_HAS_RESULTS")
        if capture.status == "COMPLETE" and capture.visits_spent == 0:
            raise ValueError("COMPLETE_QUERY_WITHOUT_VISITS")
        if capture.visits_spent == 0 and capture.rows:
            raise ValueError("UNVISITED_QUERY_HAS_RESULTS")
        ranks = [row.rank for row in capture.rows]
        if len(ranks) != len(set(ranks)):
            raise ValueError("DUPLICATE_QUERY_RANK")
        total_visits += capture.visits_spent
        for row in capture.rows:
            if (not isinstance(row, Observation)
                    or type(row.price_krw) is not int
                    or not 0 <= row.price_krw <= plan.intent.max_price_krw
                    or type(row.rank) is not int or not 0 <= row.rank <= 650
                    or not isinstance(row.relevance, str) or row.relevance not in RELEVANCE
                    or row.source_verified is not True):
                raise ValueError("UNVERIFIED_OR_INVALID_LISTING_EVIDENCE")
            stats[capture.query_id]["observed"] += 1
            if row.relevance == "IRRELEVANT":
                stats[capture.query_id]["irrelevant"] += 1
            elif row.relevance == "UNKNOWN":
                stats[capture.query_id]["unknown"] += 1
            if not isinstance(row.listing_run_hmac, str) or not TOKEN.fullmatch(
                    row.listing_run_hmac):
                missing_identity = True
            else:
                all_rows.setdefault(row.listing_run_hmac, []).append(
                    (capture.query_id, row))
    if total_visits > MAX_SOURCE_VISITS or total_visits > plan.source_visit_budget:
        raise ValueError("GLOBAL_CAPTURE_VISIT_BUDGET_EXCEEDED")
    raw_count = sum(x["observed"] for x in stats.values())

    def result(status, unique=(), duplicate=0, groups=0, quarantined=0,
               exclusive=None, shared=None):
        exclusive = exclusive or {}
        shared = shared or {}
        yields = tuple(QueryYield(
            query_id=q.query_id, observed=stats[q.query_id]["observed"],
            relevant_exclusive=exclusive.get(q.query_id, 0),
            relevant_shared=shared.get(q.query_id, 0),
            irrelevant=stats[q.query_id]["irrelevant"],
            unknown=stats[q.query_id]["unknown"]
        ) for q in plan.active)
        return DedupResult(run_id, plan.plan_sha256, status, raw_count,
                           len(unique), duplicate, groups, quarantined,
                           total_visits, yields, tuple(sorted(unique)))

    if missing_identity:
        return result("INCONCLUSIVE_MISSING_RUN_SCOPED_IDENTITY")
    exclusive: dict[str, int] = {}
    shared: dict[str, int] = {}
    unique = []
    duplicates = groups = quarantined = 0
    for token, rows in all_rows.items():
        queries = {x[0] for x in rows}
        prices = {x[1].price_krw for x in rows}
        relevance = {x[1].relevance for x in rows}
        if len(prices) != 1 or relevance != {"RELEVANT"}:
            groups += 1
            quarantined += len(rows)
            continue
        unique.append(token)
        duplicates += len(rows) - 1
        if len(queries) == 1:
            query_id = next(iter(queries))
            exclusive[query_id] = exclusive.get(query_id, 0) + 1
        else:
            for query_id in queries:
                shared[query_id] = shared.get(query_id, 0) + 1
    status = ("COMPLETE_VERIFIED_QUERY_SET" if
              not plan.pending and all(x.status == "COMPLETE" for x in captures)
              else "PARTIAL_COVERAGE")
    return result(status, unique, duplicates, groups, quarantined, exclusive, shared)
