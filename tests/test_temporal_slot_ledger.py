import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from app_v5.temporal_slot_ledger import Lease, SlotLedger, expected_slots, audit_slots

UTC = timezone.utc
START = datetime(2026, 1, 1, 8, tzinfo=UTC)
SHA = 'a' * 40
OTHER = 'b' * 40


class TemporalSlotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'slots.sqlite3'
        self.lease = Lease(1, START, SHA)
        self.slot = expected_slots(self.lease)[0]

    def ledger(self):
        return SlotLedger.initialize(self.path)

    def test_exact_fourteen_slots_and_no_backfill(self):
        slots = expected_slots(self.lease)
        self.assertEqual(len(slots), 14)
        self.assertEqual(slots[0], START.replace(hour=12, minute=17))
        self.assertEqual(slots[-1], START + timedelta(days=7, hours=-7, minutes=-43))
        self.assertTrue(all(START <= s < START + timedelta(days=7) for s in slots))

    def test_invalid_lease(self):
        for args in [(True, START, SHA), (0, START, SHA), (1, START.replace(tzinfo=None), SHA), (1, START, 'main'), (1, START, SHA, START-timedelta(seconds=1))]:
            with self.assertRaises(ValueError):
                Lease(*args)

    def test_missing_report_is_not_proven_failure_or_success(self):
        rows = audit_slots(self.lease, self.slot + timedelta(minutes=75), {})
        self.assertEqual(rows[0]['status'], 'MISSED_UNREPORTED')
        self.assertEqual(rows[1]['status'], 'FUTURE')
        self.assertFalse(rows[0]['authorizes_listings'])

    def test_report_requires_exact_slot_and_finite_outcome(self):
        for reports in [{self.slot: 'SUCCESS'}, {self.slot-timedelta(seconds=1): 'OBSERVED'}]:
            with self.assertRaises(ValueError):
                audit_slots(self.lease, self.slot, reports)
        self.assertEqual(audit_slots(self.lease, self.slot, {self.slot: 'OBSERVED'})[0]['status'], 'OBSERVED')

    def test_cancelled_and_expired(self):
        lease = Lease(1, START, SHA, self.slot)
        self.assertEqual(audit_slots(lease, self.slot, {})[0]['status'], 'CANCELLED')
        ledger = self.ledger()
        self.assertEqual(ledger.claim(lease, self.slot, self.slot), 'STOPPED')
        self.assertEqual(ledger.claim(self.lease, self.slot, START+timedelta(days=7)), 'EXPIRED')
        self.assertEqual(ledger.claim(self.lease, self.slot, self.slot+timedelta(minutes=75)), 'NOT_DUE')

    def test_no_overwrite_and_no_implicit_creation(self):
        with self.assertRaises((ValueError, sqlite3.Error, OSError)):
            SlotLedger(self.path)
        self.assertFalse(self.path.exists())
        self.ledger()
        with self.assertRaises(FileExistsError):
            SlotLedger.initialize(self.path)
        foreign = self.path.with_name('foreign.db')
        with closing(sqlite3.connect(foreign)) as conn, conn:
            conn.execute('CREATE TABLE keep_me (x INTEGER)')
        before = foreign.read_bytes()
        with self.assertRaises(ValueError):
            SlotLedger(foreign)
        self.assertEqual(before, foreign.read_bytes())

    def test_persistent_claim_and_cross_lease_replay(self):
        ledger = self.ledger()
        self.assertEqual(ledger.claim(self.lease, self.slot, self.slot), 'CLAIMED')
        self.assertEqual(SlotLedger(self.path).claim(self.lease, self.slot, self.slot), 'ALREADY_RECORDED')
        ledger.finish(self.lease, self.slot, self.slot+timedelta(seconds=1), 'OBSERVED')
        self.assertEqual(ledger.claim(Lease(2, START, OTHER), self.slot, self.slot), 'ALREADY_RECORDED')
        self.assertEqual(ledger.snapshot(self.lease, self.slot+timedelta(seconds=1))[0]['status'], 'OBSERVED')

    def test_crash_requires_explicit_outcome_and_no_retry(self):
        ledger = self.ledger()
        ledger.claim(self.lease, self.slot, self.slot)
        next_slot = expected_slots(self.lease)[1]
        self.assertEqual(SlotLedger(self.path).claim(self.lease, next_slot, next_slot), 'REVIEW_REQUIRED')
        self.assertEqual(ledger.snapshot(self.lease, next_slot)[0]['status'], 'OUTCOME_UNKNOWN')
        ledger.finish(self.lease, self.slot, next_slot, 'INTERRUPTED')
        self.assertEqual(ledger.claim(self.lease, self.slot, self.slot), 'ALREADY_RECORDED')
        self.assertEqual(ledger.claim(self.lease, next_slot, next_slot), 'CLAIMED')

    def test_finish_binding_and_single_transition(self):
        ledger = self.ledger()
        ledger.claim(self.lease, self.slot, self.slot)
        for lease, now, state in [(Lease(2, START, SHA), self.slot, 'OBSERVED'), (Lease(1, START, OTHER), self.slot, 'OBSERVED'), (self.lease, self.slot-timedelta(seconds=1), 'OBSERVED'), (self.lease, self.slot, 'PASS')]:
            with self.assertRaises(ValueError):
                ledger.finish(lease, self.slot, now, state)
        ledger.finish(self.lease, self.slot, self.slot, 'NOT_VERIFIED')
        with self.assertRaises(ValueError):
            ledger.finish(self.lease, self.slot, self.slot, 'OBSERVED')

    def test_snapshot_does_not_credit_other_lease(self):
        ledger = self.ledger()
        ledger.claim(self.lease, self.slot, self.slot)
        ledger.finish(self.lease, self.slot, self.slot, 'OBSERVED')
        self.assertEqual(ledger.snapshot(Lease(2, START, SHA), self.slot)[0]['status'], 'OTHER_LEASE_RECORDED')

    def test_concurrent_claims_only_one_wins(self):
        ledger = self.ledger()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: ledger.claim(self.lease, self.slot, self.slot), range(8)))
        self.assertEqual(results.count('CLAIMED'), 1)
        self.assertEqual(results.count('ALREADY_RECORDED'), 7)

    def test_clock_regression_after_later_completion(self):
        ledger = self.ledger()
        ledger.claim(self.lease, self.slot, self.slot)
        next_slot = expected_slots(self.lease)[1]
        ledger.finish(self.lease, self.slot, next_slot+timedelta(seconds=5), 'FAILED')
        self.assertEqual(ledger.claim(self.lease, next_slot, next_slot), 'CLOCK_REGRESSION')

    def test_future_reports_and_time_rollback_are_rejected(self):
        with self.assertRaises(ValueError):
            audit_slots(self.lease, self.slot-timedelta(seconds=1), {self.slot: 'OBSERVED'})
        ledger = self.ledger()
        self.assertEqual(ledger.claim(self.lease, self.slot, self.slot-timedelta(seconds=1)), 'NOT_DUE')


if __name__ == '__main__':
    unittest.main()
