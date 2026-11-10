# -*- coding: utf-8 -*-
"""v5 SQLite history: exact-ID continuity, evidence-aware changes, no network.

This module consumes *already validated, owner-local* v4 evidence. It does not
approve marketplace listings, infer sale state from schema.org stock, perform
site requests, or write raw listing data to GitHub artifacts.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
import sqlite3
from typing import Iterator

from daangn_listing_state_v4_24 import AVAILABILITY_KINDS, TRANSACTION_STATES
from daangn_v4_1_core import normalized_listing
from daangn_v4_4_gate import stable_article_id

_SCHEMA_VERSION = 3
_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_REGION = re.compile(r"^[0-9]{1,12}$")
_SENTINELS = frozenset({"NOT_OBSERVABLE", "AMBIGUOUS", "NOT_VERIFIED"})


def _utc(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("UTC_TIMESTAMP_REQUIRED")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("INVALID_TIMESTAMP") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _identifier(value: str, kind: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("INVALID_" + kind)
    return value


def _title(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not (1 <= len(value) <= 140):
        raise ValueError("INVALID_TITLE")
    if any(ord(ch) < 32 for ch in value):
        raise ValueError("INVALID_TITLE_CONTROL")
    return value


@dataclass(frozen=True)
class Observation:
    """Exact-item observation; all bools denote verified provenance, not guesses."""

    canonical_url: str
    observed_at_utc: str
    identity_verified: bool = False
    title: str | None = None
    price_krw: int | None = None
    price_verified: bool = False
    transaction_status: str = "NOT_VERIFIED"
    primary_status_verified: bool = False
    stock_availability: str = "NOT_OBSERVABLE"
    stock_verified: bool = False
    description: str | None = None
    description_verified: bool = False
    evidence_level: str = "ADVISORY"
    sale_filter_eligible: bool = False
    sale_state_inferred: bool = False


@dataclass(frozen=True)
class SourceEvidence:
    """Private display provenance from a v4.34 sealed shortlist, never UI truth."""

    source_version: str
    capture_created_utc: str
    category_display: str
    sale_display: str
    source_observation_count: int
    primary_h1_captured: bool
    full_recommendation_approved: bool


def _prepare_source(item: SourceEvidence) -> tuple:
    if not isinstance(item, SourceEvidence) or item.source_version != "4.34":
        raise ValueError("INVALID_SOURCE_VERSION")
    if item.category_display != "디지털기기":
        raise ValueError("INVALID_SOURCE_CATEGORY")
    if item.sale_display not in ("판매 가능 추정", "판매중 직접 확인"):
        raise ValueError("INVALID_SOURCE_SALE_LABEL")
    if (type(item.source_observation_count) is not int or
            not 1 <= item.source_observation_count <= 9):
        raise ValueError("INVALID_SOURCE_OBSERVATION_COUNT")
    if (item.primary_h1_captured is not True or
            item.full_recommendation_approved is not False):
        raise ValueError("INVALID_SOURCE_APPROVAL_FLAGS")
    return (item.source_version, _utc(item.capture_created_utc),
            item.category_display, item.sale_display,
            item.source_observation_count, 1, 0)


def _prepare(item: Observation) -> tuple[str, str, dict]:
    if not isinstance(item, Observation):
        raise TypeError("OBSERVATION_REQUIRED")
    canonical = normalized_listing(item.canonical_url)
    if canonical is None or canonical != item.canonical_url:
        raise ValueError("EXACT_CANONICAL_URL_REQUIRED")
    article_id = stable_article_id(canonical)
    if article_id is None or item.identity_verified is not True:
        raise ValueError("EXACT_LISTING_IDENTITY_UNVERIFIED")
    for flag in ("price_verified", "primary_status_verified", "stock_verified",
                 "description_verified", "sale_filter_eligible", "sale_state_inferred"):
        if type(getattr(item, flag)) is not bool:
            raise ValueError("INVALID_FLAG_" + flag)
    if item.price_verified:
        if type(item.price_krw) is not int or item.price_krw < 0:
            raise ValueError("INVALID_VERIFIED_PRICE")
    elif item.price_krw is not None:
        raise ValueError("UNVERIFIED_PRICE_MUST_BE_NULL")
    if item.transaction_status not in TRANSACTION_STATES:
        raise ValueError("INVALID_TRANSACTION_STATE")
    if item.primary_status_verified:
        if item.transaction_status in _SENTINELS:
            raise ValueError("NO_DIRECT_PRIMARY_STATUS")
    elif item.transaction_status not in _SENTINELS:
        raise ValueError("UI_TRANSACTION_NOT_DIRECTLY_VERIFIED")
    if item.stock_availability not in AVAILABILITY_KINDS:
        raise ValueError("INVALID_STOCK_AVAILABILITY")
    if item.stock_verified:
        if item.stock_availability in ("NOT_OBSERVABLE", "AMBIGUOUS"):
            raise ValueError("UNVERIFIED_STOCK_KIND")
    elif item.stock_availability != "NOT_OBSERVABLE":
        raise ValueError("STOCK_WITHOUT_EXACT_PRODUCT_PROOF")
    if item.description_verified:
        if not isinstance(item.description, str) or len(item.description) > 50000:
            raise ValueError("INVALID_DESCRIPTION")
    elif item.description is not None:
        raise ValueError("UNVERIFIED_DESCRIPTION_MUST_BE_NULL")
    if item.evidence_level not in ("REVIEWABLE", "ADVISORY"):
        raise ValueError("INVALID_EVIDENCE_LEVEL")
    if item.sale_state_inferred and not item.sale_filter_eligible:
        raise ValueError("INFERRED_SALE_NOT_ELIGIBLE")
    # Contradictions cannot become trusted changes.
    if (item.primary_status_verified and item.stock_verified and
        ((item.transaction_status in ("SOLD", "RESERVED") and
          item.stock_availability == "IN_STOCK") or
         (item.transaction_status == "FOR_SALE" and
          item.stock_availability in ("OUT_OF_STOCK", "SOLD_OUT")))):
        raise ValueError("PRIMARY_STOCK_EVIDENCE_CONFLICT")
    seen = _utc(item.observed_at_utc)
    data = asdict(item)
    data.pop("description")
    data.pop("identity_verified")
    data["observed_at_utc"] = seen
    data["title"] = _title(item.title)
    data["description_sha256"] = (
        hashlib.sha256(item.description.encode("utf-8")).hexdigest()
        if item.description_verified else None
    )
    data["canonical_url"] = canonical
    return article_id, seen, data


class HistoryStore:
    """Single-writer transactional store, suitable for a small OCI instance."""

    def __init__(self, db_path: str | Path, hmac_key: bytes):
        if not isinstance(hmac_key, bytes) or len(hmac_key) < 32:
            raise ValueError("PRIVATE_HMAC_KEY_MIN_32_BYTES")
        self._key = hmac_key
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, _SCHEMA_VERSION):
                raise RuntimeError("UNSUPPORTED_SCHEMA_VERSION")
            if version < _SCHEMA_VERSION:
                conn.executescript(
                    Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
                )
                conn.execute("PRAGMA user_version = 3")
            expected_key_check = hmac.new(
                self._key, b"auto-daangn:v5:database-key-check",
                hashlib.sha256
            ).hexdigest()
            saved = conn.execute(
                "SELECT value FROM history_store_meta WHERE name='hmac_check'"
            ).fetchone()
            if saved is not None:
                if not hmac.compare_digest(saved["value"], expected_key_check):
                    raise ValueError("HISTORY_DATABASE_HMAC_KEY_MISMATCH")
            else:
                # v1 upgrade: prove the supplied key matches existing article IDs
                # rather than accepting an arbitrary new key.
                for row in conn.execute(
                    "SELECT listing_key,canonical_url FROM listings"
                ):
                    article_id = stable_article_id(row["canonical_url"])
                    if not article_id:
                        raise ValueError("CORRUPT_LEGACY_LISTING_ID")
                    actual_key = hmac.new(
                        self._key, ("daangn:v5:" + article_id).encode("ascii"),
                        hashlib.sha256
                    ).hexdigest()
                    if not hmac.compare_digest(actual_key, row["listing_key"]):
                        raise ValueError("HISTORY_DATABASE_HMAC_KEY_MISMATCH")
                conn.execute(
                    "INSERT INTO history_store_meta(name,value) VALUES ('hmac_check',?)",
                    (expected_key_check,)
                )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path), timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA journal_mode=WAL")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def stable_key(self, canonical_url: str) -> str:
        canonical = normalized_listing(canonical_url)
        article_id = stable_article_id(canonical) if canonical == canonical_url else None
        if not article_id:
            raise ValueError("EXACT_CANONICAL_URL_REQUIRED")
        return hmac.new(self._key, ("daangn:v5:" + article_id).encode("ascii"),
                        hashlib.sha256).hexdigest()

    def create_profile(self, profile_id: str, *, name: str, keyword: str,
                       region_id: str, max_price_krw: int | None = None) -> None:
        _identifier(profile_id, "PROFILE_ID")
        if not all(isinstance(x, str) and 1 <= len(x.strip()) <= 120
                   for x in (name, keyword)):
            raise ValueError("INVALID_PROFILE")
        if not isinstance(region_id, str) or not _REGION.fullmatch(region_id):
            raise ValueError("INVALID_REGION")
        if max_price_krw is not None and (
            type(max_price_krw) is not int or max_price_krw < 0
        ):
            raise ValueError("INVALID_MAX_PRICE")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT OR IGNORE INTO search_profiles
                (profile_id,name,keyword,region_id,max_price_krw,created_at_utc)
                VALUES (?,?,?,?,?,?)""",
                (profile_id, name, keyword, region_id, max_price_krw,
                 _utc(datetime.now(timezone.utc).isoformat()))
            )
            row = conn.execute(
                "SELECT name,keyword,region_id,max_price_krw FROM search_profiles WHERE profile_id=?",
                (profile_id,)
            ).fetchone()
            if tuple(row) != (name, keyword, region_id, max_price_krw):
                raise ValueError("PROFILE_ID_CONFLICT")

    def create_job(self, job_id: str, profile_id: str) -> None:
        _identifier(job_id, "JOB_ID")
        _identifier(profile_id, "PROFILE_ID")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT OR IGNORE INTO collection_jobs
                (job_id,profile_id,status,created_at_utc) VALUES (?,?,?,?)""",
                (job_id, profile_id, "PENDING",
                 _utc(datetime.now(timezone.utc).isoformat()))
            )
            row = conn.execute("SELECT profile_id,status FROM collection_jobs WHERE job_id=?",
                               (job_id,)).fetchone()
            if row is None or row["profile_id"] != profile_id:
                raise ValueError("JOB_ID_CONFLICT")

    def finish_job(self, job_id: str, *, succeeded: bool) -> None:
        _identifier(job_id, "JOB_ID")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                """UPDATE collection_jobs SET status=?,finished_at_utc=?
                WHERE job_id=? AND status IN ('PENDING','RUNNING')""",
                ("COMPLETED" if succeeded else "FAILED",
                 _utc(datetime.now(timezone.utc).isoformat()), job_id)
            )
            if cur.rowcount != 1:
                raise ValueError("JOB_MISSING_OR_FINALIZED")

    def ingest(self, job_id: str, item: Observation) -> dict:
        """Store one observation; delegates to the atomic batch API."""
        return self.ingest_many(job_id, [item])[0]

    def ingest_many(self, job_id: str, items: list[Observation], *,
                    source_evidence: list[SourceEvidence] | None = None,
                    signed_capture: dict | None = None) -> list[dict]:
        """Store one capture and optional verified producer metadata atomically.

        signed_capture is an *internal* trust-boundary argument. External callers
        must first verify the Ed25519 signature, pinned key, all file hashes,
        source commit, and run evidence with verify_attestation().
        """
        _identifier(job_id, "JOB_ID")
        if type(items) is not list or len(items) > 650:
            raise ValueError("INVALID_BATCH")
        if source_evidence is not None and (
                type(source_evidence) is not list or
                len(source_evidence) != len(items)):
            raise ValueError("SOURCE_EVIDENCE_COUNT_MISMATCH")
        prepared = [_prepare(item) for item in items]
        sources = ([_prepare_source(x) for x in source_evidence]
                   if source_evidence is not None else [None] * len(items))
        attested = None
        if signed_capture is not None:
            from app_v5.attestation import job_id_for_attestation
            claim = signed_capture
            if (type(claim) is not dict
                    or job_id_for_attestation(claim) != job_id):
                raise ValueError("ATTESTED_JOB_ID_MISMATCH")
            attested = (
                job_id, claim["repository"], claim["workflow"],
                claim["commit_sha"], claim["run_id"], claim["run_attempt"],
                claim["signer_key_id"], claim["attestation_sha256"],
                claim["encrypted_sha256"], claim["capture_ended_utc"]
            )
            if any(item.evidence_level != "REVIEWABLE" for item in items):
                raise ValueError("ATTESTED_CAPTURE_REQUIRES_REVIEWABLE")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if attested is not None:
                existing = conn.execute(
                    """SELECT repository,workflow,source_commit_sha,run_id,
                              run_attempt,signer_key_id,attestation_sha256,
                              encrypted_sha256,capture_ended_utc
                       FROM capture_attestations WHERE job_id=?""", (job_id,)
                ).fetchone()
                if existing is not None and tuple(existing) != attested[1:]:
                    raise ValueError("ATTESTED_JOB_REPLAY_CONFLICT")
                if existing is None:
                    try:
                        conn.execute(
                            """INSERT INTO capture_attestations
                               (job_id,repository,workflow,source_commit_sha,
                                run_id,run_attempt,signer_key_id,attestation_sha256,
                                encrypted_sha256,capture_ended_utc)
                               VALUES (?,?,?,?,?,?,?,?,?,?)""", attested
                        )
                    except sqlite3.IntegrityError as exc:
                        raise ValueError("ATTESTED_RUN_REPLAY_CONFLICT") from exc
            return [
                self._ingest_prepared(conn, job_id, article_id, seen, data, meta)
                for (article_id, seen, data), meta in zip(prepared, sources)
            ]

    def _ingest_prepared(self, conn: sqlite3.Connection, job_id: str,
                         article_id: str, seen: str, data: dict,
                         source_meta: tuple | None) -> dict:
        listing_key = hmac.new(
            self._key, ("daangn:v5:" + article_id).encode("ascii"),
            hashlib.sha256
        ).hexdigest()
        digest = hashlib.sha256(json.dumps(
            data, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")).hexdigest()

        def store_source(observation_id: int, *, repeated: bool):
            if source_meta is None:
                return
            current = conn.execute(
                """SELECT source_version,capture_created_utc,category_display,
                          sale_display,source_observation_count,primary_h1_captured,
                          full_recommendation_approved
                   FROM listing_source_evidence WHERE observation_id=?""",
                (observation_id,)
            ).fetchone()
            if current is not None:
                if tuple(current) != source_meta:
                    raise ValueError("CONFLICTING_SOURCE_EVIDENCE")
                return
            if repeated:
                raise ValueError("SOURCE_EVIDENCE_MISSING_ON_REPEAT")
            conn.execute(
                """INSERT INTO listing_source_evidence
                   (observation_id,source_version,capture_created_utc,
                    category_display,sale_display,source_observation_count,
                    primary_h1_captured,full_recommendation_approved)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (observation_id, *source_meta)
            )

        job = conn.execute(
            "SELECT profile_id,status FROM collection_jobs WHERE job_id=?", (job_id,)
        ).fetchone()
        if job is None or job["status"] not in ("PENDING", "RUNNING", "COMPLETED"):
            raise ValueError("JOB_NOT_ACCEPTING_OBSERVATIONS")
        old = conn.execute(
            """SELECT observation_id,payload_sha256 FROM listing_observations
            WHERE job_id=? AND listing_key=?""", (job_id, listing_key)
        ).fetchone()
        if old is not None:
            if old["payload_sha256"] != digest:
                raise ValueError("CONFLICTING_SAME_JOB_OBSERVATION")
            store_source(old["observation_id"], repeated=True)
            return {"listing_key": listing_key, "observation_id": old["observation_id"],
                    "events": [], "idempotent": True, "historical": False}
        if job["status"] == "COMPLETED":
            raise ValueError("COMPLETED_JOB_CANNOT_ACCEPT_NEW_OBSERVATIONS")
        latest = conn.execute(
            """SELECT * FROM listing_observations
            WHERE listing_key=? AND evidence_level='REVIEWABLE'
            ORDER BY observed_at_utc DESC, observation_id DESC LIMIT 1""",
            (listing_key,)
        ).fetchone()
        historical = latest is not None and seen < latest["observed_at_utc"]
        if latest is not None and seen == latest["observed_at_utc"]:
            if latest["payload_sha256"] != digest:
                raise ValueError("CONFLICTING_SAME_TIMESTAMP")
            historical = True
        conn.execute(
            """INSERT OR IGNORE INTO listings
            (listing_key,canonical_url,first_seen_utc,last_seen_utc)
            VALUES (?,?,?,?)""",
            (listing_key, data["canonical_url"], seen, seen)
        )
        fields = (
            "listing_key", "job_id", "profile_id", "observed_at_utc", "title",
            "price_krw", "price_verified", "transaction_status",
            "primary_status_verified", "stock_availability", "stock_verified",
            "description_sha256", "description_verified", "evidence_level",
            "sale_filter_eligible", "sale_state_inferred", "payload_sha256"
        )
        values = (
            listing_key, job_id, job["profile_id"], seen, data["title"],
            data["price_krw"], int(data["price_verified"]),
            data["transaction_status"], int(data["primary_status_verified"]),
            data["stock_availability"], int(data["stock_verified"]),
            data["description_sha256"], int(data["description_verified"]),
            data["evidence_level"], int(data["sale_filter_eligible"]),
            int(data["sale_state_inferred"]), digest
        )
        conn.execute(
            "INSERT INTO listing_observations (" + ",".join(fields) + ") VALUES (" +
            ",".join("?" for _ in fields) + ")", values
        )
        observation_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        store_source(observation_id, repeated=False)
        conn.execute(
            """UPDATE listings SET
                first_seen_utc=MIN(first_seen_utc, ?),
                last_seen_utc=MAX(last_seen_utc, ?)
            WHERE listing_key=?""", (seen, seen, listing_key)
        )
        events = []
        if data["evidence_level"] == "REVIEWABLE" and not historical:
            prior = conn.execute(
                """SELECT * FROM listing_observations
                WHERE listing_key=? AND evidence_level='REVIEWABLE'
                  AND observation_id<>? AND observed_at_utc<?
                ORDER BY observed_at_utc DESC, observation_id DESC LIMIT 1""",
                (listing_key, observation_id, seen)
            ).fetchone()
            # Missing/unverified values never erase a previous verified witness.
            def last_verified(column: str, flag: str):
                if not data[flag]:
                    return None
                return conn.execute(
                    f"""SELECT {column} AS value FROM listing_observations
                    WHERE listing_key=? AND evidence_level='REVIEWABLE'
                      AND {flag}=1 AND observed_at_utc<?
                    ORDER BY observed_at_utc DESC, observation_id DESC LIMIT 1""",
                    (listing_key, seen)
                ).fetchone()

            def emit(kind: str, before, after):
                if before is not None and str(before) != str(after):
                    conn.execute(
                        """INSERT INTO listing_events
                        (listing_key,observation_id,event_type,previous_value,current_value,created_at_utc)
                        VALUES (?,?,?,?,?,?)""",
                        (listing_key, observation_id, kind, str(before), str(after), seen)
                    )
                    events.append(kind)

            if prior is not None:
                previous_price = last_verified("price_krw", "price_verified")
                if previous_price is not None:
                    p, n = previous_price["value"], data["price_krw"]
                    if p is not None and n is not None:
                        emit("PRICE_DROPPED" if n < p else "PRICE_INCREASED", p, n)
                previous_status = last_verified("transaction_status",
                                                "primary_status_verified")
                if previous_status is not None:
                    emit("TRANSACTION_STATUS_CHANGED", previous_status["value"],
                         data["transaction_status"])
                previous_stock = last_verified("stock_availability", "stock_verified")
                if previous_stock is not None:
                    emit("STOCK_AVAILABILITY_CHANGED", previous_stock["value"],
                         data["stock_availability"])
                previous_description = last_verified("description_sha256",
                                                      "description_verified")
                if previous_description is not None:
                    emit("DESCRIPTION_CHANGED", previous_description["value"],
                         data["description_sha256"])
            conn.execute(
                """UPDATE listings SET latest_observation_id=?, canonical_url=?
                WHERE listing_key=?""",
                (observation_id, data["canonical_url"], listing_key)
            )
        return {"listing_key": listing_key, "observation_id": observation_id,
                "events": events, "idempotent": False, "historical": historical}


    def get_attestation(self, job_id: str) -> dict | None:
        """Return the pinned provenance digest for an already imported job."""
        _identifier(job_id, "JOB_ID")
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM capture_attestations WHERE job_id=?", (job_id,)
            ).fetchone()
            return dict(row) if row is not None else None

    def get_job(self, job_id: str) -> dict | None:
        """Inspect durable job state for safe idempotent import recovery."""
        _identifier(job_id, "JOB_ID")
        with self._connection() as conn:
            row = conn.execute(
                "SELECT job_id,profile_id,status,created_at_utc,finished_at_utc "
                "FROM collection_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            return dict(row) if row is not None else None

    def get_source_evidence(self, listing_key: str) -> list[dict]:
        """Read private v4.34 display metadata; never interpret it as sale proof."""
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT s.* FROM listing_source_evidence AS s
                   JOIN listing_observations AS o
                     ON o.observation_id = s.observation_id
                   WHERE o.listing_key=? ORDER BY o.observed_at_utc, o.observation_id""",
                (listing_key,)
            ).fetchall()
            return [dict(row) for row in rows]

    def get_events(self, listing_key: str | None = None) -> list[dict]:
        with self._connection() as conn:
            if listing_key is None:
                rows = conn.execute(
                    "SELECT * FROM listing_events ORDER BY event_id"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM listing_events WHERE listing_key=? ORDER BY event_id",
                    (listing_key,)
                ).fetchall()
            return [dict(row) for row in rows]

    def get_listing(self, listing_key: str) -> dict | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM listings WHERE listing_key=?", (listing_key,)
            ).fetchone()
            return dict(row) if row else None

    def get_observations(self, listing_key: str) -> list[dict]:
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT * FROM listing_observations
                WHERE listing_key=? ORDER BY observed_at_utc, observation_id""",
                (listing_key,)
            ).fetchall()
            return [dict(row) for row in rows]
