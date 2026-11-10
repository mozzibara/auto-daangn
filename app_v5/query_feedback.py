# -*- coding: utf-8 -*-
"""Conservative multi-run query-performance feedback, offline and review-only.

No query self-modification, LLM calls, marketplace access, or hidden feedback
from seller text. AI may generate NEW untrusted candidate terms next iteration;
the existing owner approval and per-run visit budget apply again.
"""
from __future__ import annotations

from dataclasses import dataclass

from app_v5.query_expansion import ValidatedPlan, validate_ai_proposal
from app_v5.multi_query_dedup import DedupResult


@dataclass(frozen=True)
class FeedbackItem:
    query_id: str
    completed_runs: int
    observations: int
    exclusive_unique: int
    shared_unique: int
    irrelevant: int
    unknown: int
    action: str  # evidence-based human REVIEW, never automated removal


@dataclass(frozen=True)
class FeedbackReport:
    plan_sha256: str
    valid_completed_runs: int
    skipped_incomplete_runs: int
    items: tuple[FeedbackItem, ...]
    prompt_version: str = "v5.query-feedback.v1"


def evaluate_keyword_yield(plan: ValidatedPlan,
                           history: tuple[DedupResult, ...],
                           *, min_completed_runs: int = 3) -> FeedbackReport:
    if (not isinstance(plan, ValidatedPlan) or type(history) is not tuple
            or type(min_completed_runs) is not int
            or not 2 <= min_completed_runs <= 100):
        raise ValueError("INVALID_FEEDBACK_INPUT")
    if len(history) > 100 or any(not isinstance(x, DedupResult) for x in history):
        raise ValueError("INVALID_FEEDBACK_HISTORY")
    if len({x.run_id for x in history}) != len(history):
        raise ValueError("DUPLICATE_FEEDBACK_RUN")
    if any(x.plan_sha256 != plan.plan_sha256 for x in history):
        raise ValueError("FEEDBACK_PLAN_VERSION_CONFLICT")
    completed = [x for x in history if x.status == "COMPLETE_VERIFIED_QUERY_SET"]
    items = []
    for query in plan.active:
        observations = exclusive = shared = irrelevant = unknown = 0
        for run in completed:
            found = [x for x in run.per_query if x.query_id == query.query_id]
            if len(found) != 1:
                raise ValueError("INCONSISTENT_FEEDBACK_SOURCE")
            metric = found[0]
            observations += metric.observed
            exclusive += metric.relevant_exclusive
            shared += metric.relevant_shared
            irrelevant += metric.irrelevant
            unknown += metric.unknown
        if len(completed) < min_completed_runs:
            action = "INSUFFICIENT_COMPLETE_RUNS"
        elif observations and irrelevant * 2 >= observations:
            action = "REVIEW_SCOPE_MISMATCH"
        elif exclusive == 0:
            action = "REVIEW_LOW_INCREMENTAL_YIELD"
        else:
            action = "RETAIN"
        items.append(FeedbackItem(query.query_id, len(completed), observations,
                                  exclusive, shared, irrelevant, unknown, action))
    return FeedbackReport(plan.plan_sha256, len(completed),
                          len(history) - len(completed), tuple(items))


def next_candidate_proposal_from_ai(
    proposal: dict, *, plan: ValidatedPlan
) -> ValidatedPlan:
    """AI-proposed *review queue*, not a runnable expansion.
    
    No new term is auto-approved, even if an AI or feedback report requests it.
    """
    if not isinstance(plan, ValidatedPlan):
        raise ValueError("INVALID_EXISTING_PLAN")
    checked = validate_ai_proposal(
        proposal, intent=plan.intent, owner_approved_terms=()
    )
    return checked


def feedback_prompt_input(plan: ValidatedPlan,
                          report: FeedbackReport) -> dict:
    """Privacy-bounded, read-only context for an external future AI API."""
    if not isinstance(plan, ValidatedPlan) or report.plan_sha256 != plan.plan_sha256:
        raise ValueError("UNTRUSTED_FEEDBACK_REPORT")
    metrics = {r.query_id: r for r in report.items}
    if set(metrics) != {q.query_id for q in plan.active}:
        raise ValueError("FEEDBACK_QUERY_MISMATCH")
    return {
        "schema_version": report.prompt_version,
        "base_keyword": plan.intent.keyword,
        "approved_queries": [{
            "text": q.text,
            "relation": q.relation,
            "observations": metrics[q.query_id].observations,
            "exclusive_unique": metrics[q.query_id].exclusive_unique,
            "shared_unique": metrics[q.query_id].shared_unique,
            "irrelevant": metrics[q.query_id].irrelevant,
            "unknown": metrics[q.query_id].unknown,
            "review_action": metrics[q.query_id].action,
        } for q in plan.active],
        "completed_runs": report.valid_completed_runs,
        "skipped_incomplete_runs": report.skipped_incomplete_runs,
        "must_return": "v5.query-proposal.v1",
        "new_terms_require_owner_approval": True,
        "prohibited_fields": [
            "listing_url", "seller_data", "run_hmac", "secret", "raw_page_content"
        ],
    }
