"""Daangn A/A/FAR diagnostic slot accounting; never a live approval or runner.

Caller must independently verify the existing owner approval/stop and report
provenance. This ledger cannot authorize a site visit or listing import.
Use a separate, owner-local diagnostic database, not the marketplace history DB.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
import sqlite3

UTC = timezone.utc
LEASE_LENGTH = timedelta(days=7)
WINDOW = timedelta(minutes=75)
OUTCOMES = frozenset(('OBSERVED', 'NOT_VERIFIED', 'FAILED', 'INTERRUPTED'))
APP_ID = 0x44415331


def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('UTC_AWARE_TIME_REQUIRED')
    return value.astimezone(UTC)


def _stamp(value):
    return _utc(value).isoformat(timespec='microseconds').replace('+00:00', 'Z')


@dataclass(frozen=True)
class Lease:
    """Representation of externally verified approval; not proof of approval."""
    approval_id: int
    starts_at: datetime
    source_sha: str
    stopped_at: datetime | None = None

    def __post_init__(self):
        if type(self.approval_id) is not int or not 0 < self.approval_id < 2**63:
            raise ValueError('INVALID_APPROVAL_ID')
        if type(self.source_sha) is not str or not re.fullmatch('[0-9a-f]{40}', self.source_sha):
            raise ValueError('EXACT_SOURCE_SHA_REQUIRED')
        object.__setattr__(self, 'starts_at', _utc(self.starts_at))
        if self.stopped_at is not None:
            object.__setattr__(self, 'stopped_at', _utc(self.stopped_at))
            if self.stopped_at < self.starts_at:
                raise ValueError('STOP_PRECEDES_APPROVAL')

    @property
    def expires_at(self):
        return self.starts_at + LEASE_LENGTH


def expected_slots(lease):
    """Exactly the historical 00:17/12:17 UTC cadence, no retroactive slots."""
    base = lease.starts_at.replace(hour=0, minute=17, second=0, microsecond=0)
    return tuple(s for i in range(16)
                 if lease.starts_at <= (s := base + timedelta(hours=12*i)) < lease.expires_at)


def audit_slots(lease, now, verified_reports):
    """Project missing slots without treating absent reports as failed visits.

    Reports must already be authenticated and bound to this exact lease/source.
    A successful Actions run without a valid report is not an observation.
    """
    now = _utc(now)
    slots = expected_slots(lease)
    if type(verified_reports) is not dict or any(
            s not in slots or s > now or outcome not in OUTCOMES
            or (lease.stopped_at is not None and s >= lease.stopped_at)
            for s, outcome in verified_reports.items()):
        raise ValueError('INVALID_SLOT_REPORT')
    rows = []
    for slot in slots:
        if slot in verified_reports:
            state = verified_reports[slot]
        elif lease.stopped_at is not None and slot >= lease.stopped_at:
            state = 'CANCELLED'
        elif now < slot:
            state = 'FUTURE'
        elif now >= min(slot+WINDOW, lease.expires_at, lease.stopped_at or lease.expires_at):
            state = 'MISSED_UNREPORTED'
        else:
            state = 'DUE_UNREPORTED'
        rows.append({'slot_utc': _stamp(slot), 'status': state, 'authorizes_listings': False})
    return rows


class SlotLedger:
    """Durable at-most-one attempt record, not an execution authorization.

    The operator supplies a trusted local directory. No automatic retry after
    interruption, no subprocess, network, collection, Telegram or history DB.
    """
    def __init__(self, path):
        self.path = Path(path).absolute()
        if not self.path.is_file() or self.path.is_symlink():
            raise ValueError('EXISTING_LEDGER_REQUIRED')
        with closing(self._connect(read_only=True)):
            pass

    @classmethod
    def initialize(cls, path):
        path = Path(path).absolute()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.execute(f'PRAGMA application_id={APP_ID}')
            conn.execute('PRAGMA user_version=1')
            conn.execute('''CREATE TABLE slot_attempts (
                slot TEXT PRIMARY KEY, approval_id INTEGER NOT NULL,
                lease_start TEXT NOT NULL, source_sha TEXT NOT NULL,
                started_at TEXT NOT NULL, finished_at TEXT,
                status TEXT NOT NULL CHECK(status IN
                    ('RUNNING','OBSERVED','NOT_VERIFIED','FAILED','INTERRUPTED'))
            )''')
        return cls(path)

    def _connect(self, read_only=False):
        if self.path.is_symlink():
            raise ValueError('LEDGER_SYMLINK')
        conn = sqlite3.connect(self.path.as_uri() + ('?mode=ro' if read_only else '?mode=rw'),
                               uri=True, timeout=3)
        try:
            if (conn.execute('PRAGMA application_id').fetchone()[0] != APP_ID
                    or conn.execute('PRAGMA user_version').fetchone()[0] != 1):
                raise ValueError('FOREIGN_LEDGER')
            return conn
        except BaseException:
            conn.close()
            raise

    def claim(self, lease, slot, now):
        slot, now = _utc(slot), _utc(now)
        if lease.stopped_at is not None and now >= lease.stopped_at:
            return 'STOPPED'
        if now >= lease.expires_at:
            return 'EXPIRED'
        if slot not in expected_slots(lease) or not slot <= now < slot+WINDOW:
            return 'NOT_DUE'
        with closing(self._connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute('SELECT 1 FROM slot_attempts WHERE slot=?', (_stamp(slot),)).fetchone():
                return 'ALREADY_RECORDED'
            if conn.execute("SELECT 1 FROM slot_attempts WHERE status='RUNNING' LIMIT 1").fetchone():
                return 'REVIEW_REQUIRED'
            last = conn.execute('SELECT MAX(COALESCE(finished_at,started_at)) FROM slot_attempts').fetchone()[0]
            if last is not None and last > _stamp(now):
                return 'CLOCK_REGRESSION'
            conn.execute('INSERT INTO slot_attempts VALUES (?,?,?,?,?,NULL,?)',
                         (_stamp(slot), lease.approval_id, _stamp(lease.starts_at), lease.source_sha,
                          _stamp(now), 'RUNNING'))
        return 'CLAIMED'

    def finish(self, lease, slot, now, outcome):
        if outcome not in OUTCOMES:
            raise ValueError('INVALID_OUTCOME')
        slot, now = _utc(slot), _utc(now)
        with closing(self._connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            result = conn.execute('''UPDATE slot_attempts SET status=?,finished_at=?
                WHERE slot=? AND approval_id=? AND lease_start=? AND source_sha=?
                AND status='RUNNING' AND started_at<=?''',
                (outcome, _stamp(now), _stamp(slot), lease.approval_id,
                 _stamp(lease.starts_at), lease.source_sha, _stamp(now)))
            if result.rowcount != 1:
                raise ValueError('ATTEMPT_BINDING_OR_STATE_MISMATCH')

    def has_unresolved(self):
        """Read-only, including after an approval has been removed."""
        with closing(self._connect(read_only=True)) as conn:
            return conn.execute("SELECT 1 FROM slot_attempts WHERE status='RUNNING' LIMIT 1").fetchone() is not None

    def snapshot(self, lease, now):
        now = _utc(now)
        rows = audit_slots(lease, now, {})
        with closing(self._connect(read_only=True)) as conn:
            conn.execute('BEGIN')
            for row in rows:
                rec = conn.execute('''SELECT approval_id,lease_start,source_sha,started_at,
                    finished_at,status FROM slot_attempts WHERE slot=?''', (row['slot_utc'],)).fetchone()
                if rec is None:
                    continue
                if rec[:3] != (lease.approval_id, _stamp(lease.starts_at), lease.source_sha):
                    row['status'] = 'OTHER_LEASE_RECORDED'
                elif rec[3] > _stamp(now) or (rec[4] is not None and rec[4] > _stamp(now)):
                    row['status'] = 'OUTCOME_UNKNOWN'
                elif rec[5] == 'RUNNING':
                    row['status'] = 'OUTCOME_UNKNOWN'
                else:
                    row['status'] = rec[5]
        return rows
