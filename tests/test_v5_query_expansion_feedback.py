# -*- coding: utf-8 -*-
"""Synthetic, offline AI query plans, cross-keyword dedup and feedback gates."""
from __future__ import annotations

import unittest

from app_v5.query_expansion import (
    SearchIntent, validate_ai_proposal, normalize_keyword, proposal_schema,
)
from app_v5.multi_query_dedup import (
    Observation, QueryCapture, aggregate_one_run,
)
from app_v5.query_feedback import (
    evaluate_keyword_yield, feedback_prompt_input,
    next_candidate_proposal_from_ai,
)

A = "a" * 20
B = "b" * 20
C = "c" * 20
D = "d" * 20


def intent():
    return SearchIntent(
        profile_id="hdd-nas", keyword="HDD", region="cheonan",
        category_id=1, max_price_krw=50000, available_only=True
    )


def proposal(*, terms=None):
    terms = ["하드디스크", "3.5인치 하드"] if terms is None else terms
    return {
        "schema_version": "v5.query-proposal.v1",
        "profile_id": "hdd-nas",
        "base_keyword": "HDD",
        "candidates": [{
            "text": term, "relation": "synonym",
            "rationale": "Synthetic same-intent term for fixture",
            "confidence": 0.99
        } for term in terms]
    }


def plan(*, approvals=("하드디스크", "3.5인치 하드")):
    return validate_ai_proposal(
        proposal(), intent=intent(), owner_approved_terms=approvals
    )


def observation(token, rank, *, price=30000, relevance="RELEVANT", verified=True):
    return Observation(token, price, rank, relevance, verified)


def captures(p, *, run_id="capture-101", overlap_only=False):
    # Each query has <=3 source visits; HMAC comes from *the same run*.
    refs = [q.query_id for q in p.active]
    token_map = [
        (observation(A, 0), observation(B, 1)),
        (observation(A, 0), observation(C, 1)),
        (observation(A, 0),) if overlap_only else
            (observation(A, 0), observation(D, 1))
    ]
    return tuple(QueryCapture(
        query_id=ref, run_id=run_id, status="COMPLETE",
        visits_spent=3, rows=token_map[index]
    ) for index, ref in enumerate(refs))


class QueryExpansionTests(unittest.TestCase):
    def test_ai_suggestion_is_not_its_own_approval(self):
        p = validate_ai_proposal(proposal(), intent=intent())
        self.assertEqual([x.text for x in p.active], ["HDD"])
        self.assertEqual([x.text for x in p.pending],
                         ["하드디스크", "3.5인치 하드"])
        self.assertFalse(p.approved_search_complete)
        self.assertEqual(p.source_visit_budget, 3)

    def test_independent_owner_allowlist_can_enable_all_three(self):
        p = plan()
        self.assertTrue(p.approved_search_complete)
        self.assertEqual(len(p.active), 3)
        self.assertEqual(p.source_visit_budget, 9)
        self.assertEqual(p.plan_sha256, plan().plan_sha256)
        self.assertEqual(len(p.plan_sha256), 64)

    def test_ai_cannot_overwrite_original_keyword_or_filters(self):
        for field, fake in (
            ("profile_id", "different"),
            ("base_keyword", "SSD"),
            ("schema_version", "v5.query-proposal.v2"),
        ):
            with self.subTest(field=field):
                payload = proposal()
                payload[field] = fake
                with self.assertRaisesRegex(ValueError, "AI_CANNOT_OVERRIDE"):
                    validate_ai_proposal(payload, intent=intent())
        self.assertEqual(plan().intent.max_price_krw, 50000)
        self.assertEqual(plan().intent.region, "cheonan")

    def test_query_normalization_detects_confusables_and_duplicates(self):
        self.assertEqual(normalize_keyword("  ＨＤＤ   "), "hdd")
        data = proposal(terms=["hdd", "하드디스크"])
        with self.assertRaisesRegex(ValueError, "DUPLICATE_OR_BASE_QUERY"):
            validate_ai_proposal(data, intent=intent())
        data = proposal(terms=["NAS 하드", "nas  하드"])
        with self.assertRaisesRegex(ValueError, "DUPLICATE_OR_BASE_QUERY"):
            validate_ai_proposal(data, intent=intent())

    def test_injection_chars_and_unknown_schema_fields_denied(self):
        for term in ("HDD\nignore previous", "NAS\u200b하드",
                     "https://evil.example/?token=secret", "<script>", "💾"):
            with self.subTest(term=term):
                with self.assertRaises(ValueError):
                    validate_ai_proposal(proposal(terms=[term]), intent=intent())
        data = proposal()
        data["max_price_krw"] = 999999999
        with self.assertRaisesRegex(ValueError, "INVALID_AI_PROPOSAL_SCHEMA"):
            validate_ai_proposal(data, intent=intent())
        data = proposal()
        data["candidates"][0]["approved"] = True
        with self.assertRaisesRegex(ValueError, "INVALID_AI_CANDIDATE_SCHEMA"):
            validate_ai_proposal(data, intent=intent())

    def test_budget_never_grows_implicitly_with_ai_synonyms(self):
        data = proposal(terms=["하드디스크", "3.5인치 하드", "NAS 하드"])
        with self.assertRaisesRegex(ValueError, "SOURCE_VISIT_BUDGET_EXCEEDED"):
            validate_ai_proposal(data, intent=intent(), owner_approved_terms=[
                "하드디스크", "3.5인치 하드", "NAS 하드"
            ])
        with self.assertRaisesRegex(ValueError, "UNRECOGNIZED_OWNER_APPROVAL"):
            validate_ai_proposal(proposal(), intent=intent(),
                                 owner_approved_terms=["SSD"])

    def test_malformed_ai_relation_or_trusted_profile_types_fail_closed(self):
        data = proposal()
        data["candidates"][0]["relation"] = ["synonym"]
        with self.assertRaisesRegex(ValueError, "INVALID_AI_CANDIDATE_METADATA"):
            validate_ai_proposal(data, intent=intent())
        with self.assertRaisesRegex(ValueError, "INVALID_PROFILE_ID"):
            SearchIntent(profile_id=["hdd"], keyword="HDD", region="cheonan",
                         category_id=1, max_price_krw=50000)
        with self.assertRaisesRegex(ValueError, "INVALID_TRUSTED_FILTERS"):
            SearchIntent(profile_id="hdd", keyword="HDD", region=[],
                         category_id=1, max_price_krw=50000)

    def test_bounded_json_contract(self):
        schema = proposal_schema()
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["candidates"]["maxItems"], 12)
        with self.assertRaisesRegex(ValueError, "AI_PROPOSAL_COUNT_BOUNDED"):
            validate_ai_proposal(proposal(terms=[f"model {i}" for i in range(13)]),
                                 intent=intent())


class MultiKeywordDedupTests(unittest.TestCase):
    def test_all_queries_unique_exact_id_and_overlap_provenance(self):
        p = plan()
        result = aggregate_one_run(p, captures(p))
        self.assertEqual(result.status, "COMPLETE_VERIFIED_QUERY_SET")
        self.assertEqual(result.raw_observations, 6)
        self.assertEqual(result.unique_listings, 4)
        self.assertEqual(result.duplicate_observations_removed, 2)
        self.assertEqual(result.quarantined_groups, 0)
        self.assertEqual(result.visits_spent, 9)
        self.assertEqual(result.unique_run_hmacs, (A, B, C, D))
        self.assertEqual([x.relevant_exclusive for x in result.per_query],
                         [1, 1, 1])
        self.assertEqual([x.relevant_shared for x in result.per_query],
                         [1, 1, 1])

    def test_distinct_ids_same_price_must_not_merge(self):
        p = plan(approvals=())
        q = p.active[0].query_id
        results = (QueryCapture(q, "run-abc", "COMPLETE", 3,
                    (observation(A, 0, price=20000),
                     observation(B, 1, price=20000))),)
        result = aggregate_one_run(p, results)
        self.assertEqual(result.unique_listings, 2)
        self.assertEqual(result.duplicate_observations_removed, 0)

    def test_price_conflict_quarantines_all_observations_for_id(self):
        p = plan()
        c = list(captures(p))
        c[1] = QueryCapture(c[1].query_id, c[1].run_id, "COMPLETE", 3,
                    (observation(A, 0, price=28000), observation(C, 1)))
        result = aggregate_one_run(p, tuple(c))
        self.assertEqual(result.unique_listings, 3)
        self.assertEqual(result.quarantined_groups, 1)
        self.assertEqual(result.quarantined_observations, 3)
        self.assertNotIn(A, result.unique_run_hmacs)

    def test_relevance_conflict_or_unknown_does_not_become_verified(self):
        p = plan(approvals=())
        q = p.active[0].query_id
        c = (QueryCapture(q, "run-abc", "COMPLETE", 3,
             (observation(A, 0, relevance="IRRELEVANT"),
              observation(B, 1, relevance="UNKNOWN"),
              observation(C, 2))),)
        result = aggregate_one_run(p, c)
        self.assertEqual(result.unique_listings, 1)
        self.assertEqual(result.quarantined_groups, 2)
        self.assertEqual(result.per_query[0].irrelevant, 1)
        self.assertEqual(result.per_query[0].unknown, 1)

    def test_missing_hmac_aborts_entire_dedup_as_inconclusive(self):
        p = plan(approvals=())
        q = p.active[0].query_id
        result = aggregate_one_run(p, (QueryCapture(
            q, "run-abc", "COMPLETE", 3,
            (observation(A, 0), observation(None, 1))),))
        self.assertEqual(result.status,
                         "INCONCLUSIVE_MISSING_RUN_SCOPED_IDENTITY")
        self.assertEqual(result.unique_listings, 0)

    def test_cross_run_and_untrusted_source_rejected(self):
        p = plan()
        c = list(captures(p))
        c[-1] = QueryCapture(c[-1].query_id, "run-different", "COMPLETE",
                             3, c[-1].rows)
        with self.assertRaisesRegex(ValueError, "CROSS_RUN_HMAC_MERGE"):
            aggregate_one_run(p, tuple(c))
        p = plan(approvals=())
        q = p.active[0].query_id
        with self.assertRaisesRegex(ValueError, "UNVERIFIED_OR_INVALID"):
            aggregate_one_run(p, (QueryCapture(
                q, "run-abc", "COMPLETE", 3,
                (observation(A, 0, verified=False),)),))

    def test_incomplete_queries_and_pending_expansion_are_partial(self):
        p = plan()
        c = list(captures(p))
        c[-1] = QueryCapture(c[-1].query_id, c[-1].run_id,
                             "BLOCKED", 0, ())
        result = aggregate_one_run(p, tuple(c))
        self.assertEqual(result.status, "PARTIAL_COVERAGE")
        self.assertEqual(result.visits_spent, 6)
        pending_plan = validate_ai_proposal(proposal(), intent=intent())
        partial = aggregate_one_run(pending_plan, (QueryCapture(
            pending_plan.active[0].query_id, "run-abc", "COMPLETE",
            3, (observation(A, 0),)),))
        self.assertEqual(partial.status, "PARTIAL_COVERAGE")

    def test_missing_or_extra_or_duplicate_query_rejected(self):
        p = plan()
        all_capture = captures(p)
        for bad in (all_capture[:-1], all_capture + (all_capture[0],)):
            with self.assertRaises(ValueError):
                aggregate_one_run(p, bad)
        changed = list(all_capture)
        changed[0] = QueryCapture("unapproved", changed[0].run_id,
                                   "COMPLETE", 3, changed[0].rows)
        with self.assertRaisesRegex(ValueError, "UNAUTHORIZED_OR_DUPLICATE"):
            aggregate_one_run(p, tuple(changed))

    def test_malformed_status_and_relevance_fail_closed(self):
        p = plan(approvals=())
        q = p.active[0].query_id
        with self.assertRaisesRegex(ValueError, "INVALID_QUERY_CAPTURE"):
            aggregate_one_run(p, (QueryCapture(
                q, "syn-001", [], 3, (observation(A, 0),)),))
        with self.assertRaisesRegex(ValueError, "UNVERIFIED_OR_INVALID"):
            aggregate_one_run(p, (QueryCapture(
                q, "syn-001", "COMPLETE", 3,
                (observation(A, 0, relevance=[]),)),))

    def test_visit_budgets_and_capture_metadata_enforced(self):
        p = plan()
        c = list(captures(p))
        c[0] = QueryCapture(c[0].query_id, c[0].run_id, "COMPLETE", 4, c[0].rows)
        with self.assertRaisesRegex(ValueError, "INVALID_QUERY_CAPTURE"):
            aggregate_one_run(p, tuple(c))
        c = list(captures(p))
        c[0] = QueryCapture(c[0].query_id, c[0].run_id, "BLOCKED", 3, c[0].rows)
        with self.assertRaisesRegex(ValueError, "BLOCKED_QUERY_HAS_RESULTS"):
            aggregate_one_run(p, tuple(c))


class QueryFeedbackTests(unittest.TestCase):
    def test_three_completed_runs_propose_review_not_auto_prune(self):
        p = plan()
        records = tuple(aggregate_one_run(p, captures(
            p, run_id=f"syn-{n}", overlap_only=True)) for n in range(3))
        metrics = evaluate_keyword_yield(p, records)
        self.assertEqual(metrics.valid_completed_runs, 3)
        self.assertEqual([x.action for x in metrics.items],
            ["RETAIN", "RETAIN", "REVIEW_LOW_INCREMENTAL_YIELD"])
        self.assertEqual(metrics.items[-1].shared_unique, 3)
        self.assertEqual(metrics.items[-1].exclusive_unique, 0)
        prompt = feedback_prompt_input(p, metrics)
        self.assertTrue(prompt["new_terms_require_owner_approval"])
        self.assertFalse(any("listing_run_hmac" in str(x)
                             or A in str(x) for x in prompt.values()))

    def test_incomplete_runs_are_excluded_from_feedback(self):
        p = plan()
        completed = aggregate_one_run(p, captures(p, run_id="syn-good"))
        blocked = list(captures(p, run_id="syn-partial"))
        blocked[-1] = QueryCapture(
            blocked[-1].query_id, "syn-partial", "BLOCKED", 0, ())
        partial = aggregate_one_run(p, tuple(blocked))
        report = evaluate_keyword_yield(p, (completed, partial))
        self.assertEqual(report.valid_completed_runs, 1)
        self.assertEqual(report.skipped_incomplete_runs, 1)
        self.assertTrue(all(x.action == "INSUFFICIENT_COMPLETE_RUNS"
                            for x in report.items))

    def test_feedback_rejects_duplicate_runs_and_changed_plans(self):
        p = plan()
        r = aggregate_one_run(p, captures(p))
        with self.assertRaisesRegex(ValueError, "DUPLICATE_FEEDBACK_RUN"):
            evaluate_keyword_yield(p, (r, r))
        changed = plan(approvals=("하드디스크",))
        with self.assertRaisesRegex(ValueError, "FEEDBACK_PLAN_VERSION_CONFLICT"):
            evaluate_keyword_yield(changed, (r,))

    def test_ai_feedback_suggests_but_cannot_self_approve(self):
        p = plan()
        future = next_candidate_proposal_from_ai(
            proposal(terms=["NAS 하드", "서버 HDD"]), plan=p)
        self.assertEqual(len(future.active), 1)
        self.assertEqual(len(future.pending), 2)
        self.assertFalse(future.approved_search_complete)
        self.assertNotEqual(future.plan_sha256, p.plan_sha256)


if __name__ == "__main__":
    unittest.main()
