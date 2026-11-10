# -*- coding: utf-8 -*-
"""Safe Telegram preview + SQLite outbox, WITHOUT any real Telegram adapter.

Real sendMessage has no client idempotency guarantee. Outbox prevents repeated
local enqueue/send-after-ack; a crash after remote accept but before ack can
still yield a duplicate on retry. This limitation must stay explicit.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from pathlib import Path
import sqlite3
import unicodedata
from uuid import uuid4
from typing import Protocol

from app_v5.analysis_profiles import (
    AnalysisResult, ProductFacts, SearchProfile, analyze_for_profile
)
from app_v5.history import HistoryStore


@dataclass(frozen=True)
class SignedPriceDrop:
    event_id: int
    listing_key: str
    title: str
    url: str
    previous_price_krw: int
    price_krw: int
    observed_at_utc: str


def signed_price_drops(store: HistoryStore) -> list[SignedPriceDrop]:
    """Read price drops with independently attested CURRENT and BASELINE rows.

    Does not treat caller-injected REVIEWABLE rows or unsigned advisory source
    as authenticated. SQLite event classification remains the source of truth.
    """
    sql = """
      SELECT e.event_id,e.listing_key,e.previous_value,e.current_value,
             e.created_at_utc,cur.title,cur.price_krw,l.canonical_url,
             prev.price_krw AS baseline_price, baseauth.job_id AS baseline_attested
        FROM listing_events e
        JOIN listing_observations cur ON cur.observation_id=e.observation_id
        JOIN capture_attestations auth ON auth.job_id=cur.job_id
        JOIN listings l ON l.listing_key=e.listing_key
        LEFT JOIN listing_observations prev ON prev.observation_id=(
            SELECT prior.observation_id FROM listing_observations prior
             WHERE prior.listing_key=cur.listing_key
               AND prior.evidence_level='REVIEWABLE'
               AND prior.price_verified=1
               AND prior.observed_at_utc<cur.observed_at_utc
             ORDER BY prior.observed_at_utc DESC, prior.observation_id DESC
             LIMIT 1)
        LEFT JOIN capture_attestations baseauth ON baseauth.job_id=prev.job_id
       WHERE e.event_type='PRICE_DROPPED'
         AND cur.evidence_level='REVIEWABLE' AND cur.price_verified=1
         AND cur.listing_key=e.listing_key
       ORDER BY e.event_id
    """
    with closing(sqlite3.connect(str(store.path))) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql).fetchall()
    result = []
    for row in rows:
        before, after = row["previous_value"], row["current_value"]
        if (not isinstance(before, str) or not before.isascii() or not before.isdecimal()
                or not isinstance(after, str) or not after.isascii()
                or not after.isdecimal() or not row["baseline_attested"]):
            continue
        previous, current = int(before), int(after)
        if (not 0 < current < previous
                or type(row["price_krw"]) is not int
                or row["price_krw"] != current
                or row["baseline_price"] != previous):
            continue
        result.append(SignedPriceDrop(
            event_id=row["event_id"], listing_key=row["listing_key"],
            title=row["title"] or "제목 확인 필요", url=row["canonical_url"],
            previous_price_krw=previous, price_krw=current,
            observed_at_utc=row["created_at_utc"]
        ))
    return result


def _clean(text: str, limit: int) -> str:
    if not isinstance(text, str):
        raise ValueError("UNSAFE_MESSAGE_TEXT")
    # Plain text, no HTML/Markdown parse_mode. No control characters.
    line = "".join(ch if unicodedata.category(ch)[0] != "C" else " "
                   for ch in text).strip()
    return " ".join(line.split())[:limit]


def render_telegram_preview(event: SignedPriceDrop,
                            analysis: AnalysisResult) -> str:
    """Render a local preview only; caller must NOT log the result in CI."""
    if not (event.event_id > 0 and len(event.listing_key) == 64
            and event.url.startswith("https://www.daangn.com/kr/buy-sell/")
            and event.previous_price_krw > event.price_krw > 0):
        raise ValueError("INVALID_SIGNED_PRICE_DROP")
    if analysis.price_drop_pct <= 0:
        raise ValueError("INVALID_PRICE_ANALYSIS")
    lines = [
        "[인증된 가격 하락 · 구매 적합성 미확정]",
        _clean(event.title, 100),
        f"{event.previous_price_krw:,}원 → {event.price_krw:,}원 "
        f"(−{analysis.price_drop_pct}%)",
        f"분석: {analysis.profile} | 우선순위 {analysis.priority} "
        f"| 점수 {analysis.score}/100 (휴리스틱)",
    ]
    if analysis.price_per_tb_krw is not None:
        lines.append(f"용량당 가격: {analysis.price_per_tb_krw:,}원/TB")
    if analysis.warnings:
        lines.append("확인 필요: " + ", ".join(analysis.warnings[:7]))
    lines.extend([
        "주의: 판매 상태·재고·SMART 원본은 별도 확인 필요",
        event.url
    ])
    rendered = "\n".join(lines)
    if len(rendered) > 3500:
        raise ValueError("MESSAGE_TOO_LONG")
    return rendered


@dataclass(frozen=True)
class ClaimedDelivery:
    delivery_id: str
    lease_token: str
    attempt: int
    text: str


class TransientSendError(Exception):
    def __init__(self, *, retry_after_seconds: int | None = None):
        super().__init__("TRANSIENT_SEND_FAILURE")
        self.retry_after_seconds = retry_after_seconds


class PermanentSendError(Exception):
    pass


class TextTransport(Protocol):
    def send_text(self, text: str) -> str: ...


def _iso(moment: datetime) -> str:
    if not isinstance(moment, datetime) or moment.utcoffset() is None:
        raise ValueError("UTC_CLOCK_REQUIRED")
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


class NotificationOutbox:
    """Temporary SQLite queue: dedup, lease/recovery, retry classification.

    The database is explicitly *not* a durable service in pre-OCI testing.
    On future OCI migration, retain this DB and use a serialized worker.
    """
    def __init__(self, path: str | Path, *, max_attempts: int = 4):
        if type(max_attempts) is not int or not 1 <= max_attempts <= 20:
            raise ValueError("INVALID_MAX_ATTEMPTS")
        self.path = Path(path)
        self.max_attempts = max_attempts
        with closing(sqlite3.connect(str(self.path))) as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS notification_outbox (
              delivery_id TEXT PRIMARY KEY,
              payload_sha256 TEXT NOT NULL,
              text_payload TEXT NOT NULL,
              state TEXT NOT NULL CHECK(state IN
                ('PENDING','INFLIGHT','SENT','DEAD')),
              attempts INTEGER NOT NULL DEFAULT 0,
              next_attempt_utc TEXT NOT NULL,
              lease_until_utc TEXT,
              lease_token TEXT,
              telegram_receipt TEXT
            );
            """)
            conn.commit()

    def _conn(self):
        conn = sqlite3.connect(str(self.path), timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def enqueue(self, event: SignedPriceDrop, recipient_ref: str,
                text: str, *, now: datetime) -> tuple[str, bool]:
        if (not isinstance(recipient_ref, str) or not 1 <= len(recipient_ref) <= 100
                or not isinstance(text, str) or not 1 <= len(text) <= 3500):
            raise ValueError("INVALID_DELIVERY_INPUT")
        if event.event_id < 1 or len(event.listing_key) != 64:
            raise ValueError("INVALID_EVENT_IDENTITY")
        delivery_id = hashlib.sha256(
            f"telegram\x00{recipient_ref}\x00{event.event_id}\x00{event.listing_key}"
            .encode("utf-8")
        ).hexdigest()
        payload_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        with closing(self._conn()) as conn:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    "SELECT payload_sha256 FROM notification_outbox WHERE delivery_id=?",
                    (delivery_id,)
                ).fetchone()
                if existing:
                    if not hmac.compare_digest(existing["payload_sha256"], payload_digest):
                        raise ValueError("CONFLICTING_ALERT_PAYLOAD")
                    return delivery_id, False
                conn.execute("""
                    INSERT INTO notification_outbox
                     (delivery_id,payload_sha256,text_payload,state,next_attempt_utc)
                     VALUES (?,?,?,'PENDING',?)
                """, (delivery_id, payload_digest, text, _iso(now)))
                return delivery_id, True

    def claim(self, *, now: datetime, lease_seconds: int = 60) -> ClaimedDelivery | None:
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise ValueError("INVALID_LEASE_SECONDS")
        clock = _iso(now)
        with closing(self._conn()) as conn:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("""
                    UPDATE notification_outbox SET
                     state=CASE WHEN attempts>=? THEN 'DEAD' ELSE 'PENDING' END,
                     lease_until_utc=NULL,lease_token=NULL,
                     next_attempt_utc=?
                    WHERE state='INFLIGHT' AND lease_until_utc<=?
                """, (self.max_attempts, clock, clock))
                row = conn.execute("""
                    SELECT * FROM notification_outbox
                    WHERE state='PENDING' AND next_attempt_utc<=?
                    ORDER BY next_attempt_utc,delivery_id LIMIT 1
                """, (clock,)).fetchone()
                if row is None:
                    return None
                token = uuid4().hex
                conn.execute("""
                    UPDATE notification_outbox SET
                      state='INFLIGHT',attempts=attempts+1,lease_token=?,
                      lease_until_utc=?
                    WHERE delivery_id=?
                """, (token, _iso(now + timedelta(seconds=lease_seconds)),
                      row["delivery_id"]))
                return ClaimedDelivery(row["delivery_id"], token,
                                       row["attempts"] + 1, row["text_payload"])

    def _resolve(self, claimed: ClaimedDelivery, *,
                 success: bool, permanent: bool, now: datetime,
                 telegram_receipt: str | None = None,
                 retry_after_seconds: int | None = None) -> str:
        clock = _iso(now)
        with closing(self._conn()) as conn:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("""
                    SELECT state,attempts,lease_token,lease_until_utc
                    FROM notification_outbox WHERE delivery_id=?
                """, (claimed.delivery_id,)).fetchone()
                if (row is None or row["state"] != "INFLIGHT"
                        or row["lease_token"] != claimed.lease_token
                        or row["lease_until_utc"] <= clock):
                    raise ValueError("STALE_DELIVERY_LEASE")
                if success:
                    if not isinstance(telegram_receipt, str) or not telegram_receipt:
                        raise ValueError("MISSING_SEND_RECEIPT")
                    state, next_run = "SENT", clock
                else:
                    state = ("DEAD" if permanent or row["attempts"] >= self.max_attempts
                             else "PENDING")
                    backoff = min(3600, 10 * (2 ** (row["attempts"] - 1)))
                    if retry_after_seconds is not None:
                        if type(retry_after_seconds) is not int or retry_after_seconds < 0:
                            raise ValueError("INVALID_RETRY_AFTER")
                        backoff = min(86400, max(backoff, retry_after_seconds))
                    next_run = _iso(now + timedelta(seconds=backoff))
                conn.execute("""
                    UPDATE notification_outbox
                    SET state=?,next_attempt_utc=?,lease_token=NULL,
                        lease_until_utc=NULL,telegram_receipt=?
                    WHERE delivery_id=?
                """, (state, next_run, telegram_receipt if success else None,
                      claimed.delivery_id))
                return state

    def ack(self, claimed: ClaimedDelivery, receipt: str, *, now: datetime) -> str:
        return self._resolve(claimed, success=True, permanent=False, now=now,
                             telegram_receipt=receipt)

    def fail(self, claimed: ClaimedDelivery, *, now: datetime,
             permanent: bool = False, retry_after_seconds: int | None = None) -> str:
        return self._resolve(claimed, success=False, permanent=permanent, now=now,
                             retry_after_seconds=retry_after_seconds)

    def status(self, delivery_id: str) -> dict | None:
        with closing(self._conn()) as conn:
            row = conn.execute("""
                SELECT delivery_id,state,attempts,next_attempt_utc,telegram_receipt
                FROM notification_outbox WHERE delivery_id=?
            """, (delivery_id,)).fetchone()
            return dict(row) if row is not None else None


def dispatch_mocked_once(outbox: NotificationOutbox, transport: TextTransport,
                         *, now: datetime) -> str:
    """Inject a fake transport in tests. Never calls Telegram itself."""
    item = outbox.claim(now=now)
    if item is None:
        return "IDLE"
    try:
        receipt = transport.send_text(item.text)
    except TransientSendError as exc:
        return outbox.fail(item, now=now,
                           retry_after_seconds=exc.retry_after_seconds)
    except PermanentSendError:
        return outbox.fail(item, now=now, permanent=True)
    return outbox.ack(item, receipt, now=now)


def enqueue_verified_drop(outbox: NotificationOutbox, store: HistoryStore,
                          event_id: int, recipient_ref: str,
                          profile: SearchProfile, facts: ProductFacts, *,
                          now: datetime) -> tuple[str, bool]:
    """Trust-boundary entry point: only a signed DB event becomes a queued alert.

    Caller-supplied SMART/capacity remain explicitly provenance-tagged,
    independently of the producer-authenticated PRICE event.
    """
    if type(event_id) is not int or event_id < 1:
        raise ValueError("INVALID_EVENT_ID")
    candidate = next((event for event in signed_price_drops(store)
                      if event.event_id == event_id), None)
    if candidate is None:
        raise ValueError("UNAUTHENTICATED_PRICE_DROP_EVENT")
    if (facts.previous_price_krw != candidate.previous_price_krw
            or facts.price_krw != candidate.price_krw):
        raise ValueError("PRICE_FACTS_MISMATCH_SIGNED_EVENT")
    analysis = analyze_for_profile(profile, facts)
    message = render_telegram_preview(candidate, analysis)
    return outbox.enqueue(candidate, recipient_ref, message, now=now)
