# -*- coding: utf-8 -*-
"""Bounded AI-query *proposal* contract: human approval stays outside model JSON.

Offline only. A generated keyword is untrusted until an independent owner
allowlist approves it. Neither AI confidence nor AI rationale grants authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import unicodedata
from typing import Any, Sequence

SCHEMA = "v5.query-proposal.v1"
RELATIONS = frozenset({"synonym", "spelling", "model_family", "related"})
MAX_PROPOSALS = 12
MAX_SOURCE_VISITS = 9
VISITS_PER_QUERY = 3


def normalize_keyword(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 120:
        raise ValueError("INVALID_KEYWORD")
    value = unicodedata.normalize("NFKC", value)
    if (not 1 <= len(value.strip()) <= 60
            or any(unicodedata.category(c)[0] == "C" for c in value)
            or any(not (unicodedata.category(c)[0] in ("L", "N")
                        or c in " -+./()") for c in value)):
        raise ValueError("INVALID_KEYWORD_CHARACTERS")
    return " ".join(value.split()).casefold()


@dataclass(frozen=True)
class SearchIntent:
    profile_id: str
    keyword: str
    region: str
    category_id: int
    max_price_krw: int
    available_only: bool = True

    def __post_init__(self):
        if not isinstance(self.profile_id, str) or not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,60}", self.profile_id):
            raise ValueError("INVALID_PROFILE_ID")
        normalize_keyword(self.keyword)
        if (not isinstance(self.region, str)
                or not re.fullmatch(r"[a-z0-9_-]{2,50}", self.region)
                or type(self.category_id) is not int or self.category_id < 1
                or type(self.max_price_krw) is not int
                or not 1 <= self.max_price_krw <= 999999999
                or self.available_only is not True):
            raise ValueError("INVALID_TRUSTED_FILTERS")


@dataclass(frozen=True)
class Query:
    query_id: str
    text: str
    relation: str


@dataclass(frozen=True)
class ValidatedPlan:
    intent: SearchIntent
    active: tuple[Query, ...]
    pending: tuple[Query, ...]
    plan_sha256: str
    source_visit_budget: int

    @property
    def approved_search_complete(self) -> bool:
        return not self.pending


def _id(text: str) -> str:
    return hashlib.sha256(normalize_keyword(text).encode("utf-8")).hexdigest()[:16]


def validate_ai_proposal(
    proposal: dict[str, Any], *, intent: SearchIntent,
    owner_approved_terms: Sequence[str] = (),
    max_source_visits: int = MAX_SOURCE_VISITS,
) -> ValidatedPlan:
    """Compile a *single-run* plan; rejected overflow must not silently truncate."""
    if (type(max_source_visits) is not int or not 1 <= max_source_visits <=
            MAX_SOURCE_VISITS or not isinstance(intent, SearchIntent)):
        raise ValueError("INVALID_CAPTURE_BUDGET")
    if type(proposal) is not dict or set(proposal) != {
            "schema_version", "profile_id", "base_keyword", "candidates"}:
        raise ValueError("INVALID_AI_PROPOSAL_SCHEMA")
    if (proposal["schema_version"] != SCHEMA
            or proposal["profile_id"] != intent.profile_id
            or proposal["base_keyword"] != intent.keyword):
        raise ValueError("AI_CANNOT_OVERRIDE_SEARCH_INTENT")
    candidates = proposal["candidates"]
    if type(candidates) is not list or len(candidates) > MAX_PROPOSALS:
        raise ValueError("AI_PROPOSAL_COUNT_BOUNDED")
    if isinstance(owner_approved_terms, (str, bytes)) or not isinstance(
            owner_approved_terms, (list, tuple, set, frozenset)):
        raise ValueError("OWNER_ALLOWLIST_REQUIRED")
    base = normalize_keyword(intent.keyword)
    approvals = [normalize_keyword(q) for q in owner_approved_terms]
    if len(approvals) != len(set(approvals)):
        raise ValueError("DUPLICATE_OWNER_APPROVAL")
    seen = {base}
    validated = []
    for row in candidates:
        if type(row) is not dict or set(row) != {
                "text", "relation", "rationale", "confidence"}:
            raise ValueError("INVALID_AI_CANDIDATE_SCHEMA")
        raw = row["text"]
        norm = normalize_keyword(raw)
        if norm in seen:
            raise ValueError("DUPLICATE_OR_BASE_QUERY")
        seen.add(norm)
        confidence = row["confidence"]
        if (not isinstance(row["relation"], str)
                or row["relation"] not in RELATIONS
                or not isinstance(row["rationale"], str)
                or not 1 <= len(row["rationale"]) <= 160
                or type(confidence) not in (float, int)
                or not 0 <= confidence <= 1):
            raise ValueError("INVALID_AI_CANDIDATE_METADATA")
        validated.append(Query(_id(norm), raw.strip(), row["relation"]))
    if any(x not in seen for x in approvals):
        raise ValueError("UNRECOGNIZED_OWNER_APPROVAL")
    active = [Query(_id(base), intent.keyword, "original")]
    pending = []
    for row in validated:
        (active if normalize_keyword(row.text) in approvals else pending).append(row)
    budget = len(active) * VISITS_PER_QUERY
    if budget > max_source_visits:
        raise ValueError("SOURCE_VISIT_BUDGET_EXCEEDED_REQUIRES_NEW_APPROVAL")
    canonical = {
        "schema_version": SCHEMA,
        "intent": {
            "profile_id": intent.profile_id, "keyword": intent.keyword,
            "region": intent.region, "category_id": intent.category_id,
            "max_price_krw": intent.max_price_krw,
            "available_only": intent.available_only,
        },
        "active": [(q.query_id, q.text, q.relation) for q in active],
        "pending": [(q.query_id, q.text, q.relation) for q in pending],
        "source_visit_budget": budget,
    }
    digest = hashlib.sha256(json.dumps(canonical, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return ValidatedPlan(intent, tuple(active), tuple(pending), digest, budget)


def proposal_schema() -> dict:
    """JSON-schema-like contract for AI Structured Outputs (not semantic proof)."""
    row = {
        "type": "object", "additionalProperties": False,
        "required": ["text", "relation", "rationale", "confidence"],
        "properties": {
            "text": {"type": "string", "maxLength": 60},
            "relation": {"type": "string", "enum": sorted(RELATIONS)},
            "rationale": {"type": "string", "maxLength": 160},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
    }
    return {
        "type": "object", "additionalProperties": False,
        "required": ["schema_version", "profile_id", "base_keyword", "candidates"],
        "properties": {
            "schema_version": {"type": "string", "const": SCHEMA},
            "profile_id": {"type": "string"},
            "base_keyword": {"type": "string"},
            "candidates": {"type": "array", "maxItems": MAX_PROPOSALS, "items": row},
        },
    }
