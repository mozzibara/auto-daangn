import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

from app_v5.temporal_slot_ledger import Lease, SlotLedger, expected_slots
from ops.oci import temporal_scheduler as s

START = datetime(2026, 1, 1, 8, tzinfo=timezone.utc)
SHA = 'a'*40
LEASE = Lease(1, START, SHA)
SLOT = expected_slots(LEASE)[0]


def fixture():
    sample = dict.fromkeys(s.COUNTS, 0)
    sample.update(rows=2, unverified=2, region_object_rows=2,
                  status='COMPLETE', identity_coverage='COMPLETE')
    arm = {'region_status': 'TARGET_REGION_CONFIRMED_DIAGNOSTIC',
           'fresh_route': 'ONE_FRESH', 'item_sample': sample}
    pair = {'overlap': 1, 'left_only': 1, 'right_only': 1,
            'union': 3, 'symmetric_difference': 2}
    return {'schema': 'oci_region_aa_far_aggregate_v1', 'status': 'OBSERVED',
            'execution_order': 'BULDANG_SADANG_BULDANG', 'arms': dict.fromkeys(s.ARMS, arm),
            'pairs': dict.fromkeys(s.PAIRS, pair), **dict.fromkeys(s.FLAGS, False)}


def encode(doc):
    return json.dumps(doc).encode()


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name)
        (self.state/'results').mkdir()
        self.ledger = SlotLedger.initialize(self.state/'slots.sqlite3')
        self.now = SLOT
        self.read = Mock(return_value=LEASE)
        self.runner = Mock(return_value=s.project_report(encode(fixture()), 0))

    def persist(self, path, doc):
        with path.open('x', encoding='utf-8') as stream:
            json.dump(doc, stream)

    def tick(self):
        return s.tick(self.state, self.read, self.runner,
                      lambda: self.now, self.persist)

    def test_parse_explicit_new_approval(self):
        doc = {'schema': s.SCHEMA, 'purpose': s.PURPOSE, 'approval_id': 1,
               'starts_at': START.isoformat(), 'source_sha': SHA}
        self.assertEqual(s.parse_approval(encode(doc), SHA), LEASE)
        for patch in ({'purpose': 'COLLECT'}, {'source_sha': 'b'*40},
                      {'starts_at': '2026-01-01'}, {'approval_id': True},
                      {'command': 'anything'}):
            with self.assertRaises(ValueError):
                s.parse_approval(encode({**doc, **patch}), SHA)
        with self.assertRaises(ValueError):
            s.parse_approval(encode(doc)[:-1]+b', "approval_id": 1}', SHA)

    def test_no_approval_no_runner(self):
        self.read.return_value = None
        self.assertEqual(self.tick(), 'NO_APPROVED_SLOT')
        self.runner.assert_not_called()

    def test_outside_window_no_catchup(self):
        for now in (SLOT-timedelta(seconds=1), SLOT+timedelta(minutes=75),
                    LEASE.expires_at):
            self.now = now
            self.assertEqual(self.tick(), 'NO_APPROVED_SLOT')
        self.runner.assert_not_called()

    def test_no_slot_before_lease(self):
        self.read.return_value = Lease(2, SLOT+timedelta(seconds=1), SHA)
        self.assertEqual(self.tick(), 'NO_APPROVED_SLOT')
        self.runner.assert_not_called()

    def test_revocation_before_claim(self):
        self.read.side_effect = [LEASE, None]
        self.assertEqual(self.tick(), 'APPROVAL_CHANGED')
        self.runner.assert_not_called()

    def test_success_single_attempt_and_result(self):
        self.assertEqual(self.tick(), 'OBSERVED')
        self.assertEqual(self.tick(), 'ALREADY_RECORDED')
        self.assertEqual(self.runner.call_count, 1)
        records = list((self.state/'results').glob('*.json'))
        self.assertEqual(len(records), 1)
        self.assertFalse(json.loads(records[0].read_text())['authorizes_listings'])
        self.assertEqual(self.ledger.snapshot(LEASE, self.now)[0]['status'], 'OBSERVED')

    def test_revocation_during_attempt_holds(self):
        def run(keep, seconds):
            self.assertTrue(keep())
            self.read.return_value = None
            self.assertFalse(keep())
            return {'status': 'INTERRUPTED'}
        self.runner.side_effect = run
        self.assertEqual(self.tick(), 'INTERRUPTED')
        self.read.return_value = LEASE
        self.now = expected_slots(LEASE)[1]
        self.assertEqual(self.tick(), 'REVIEW_REQUIRED')

    def test_failure_latches_hold(self):
        self.runner.return_value = {'status': 'NOT_VERIFIED'}
        self.assertEqual(self.tick(), 'NOT_VERIFIED')
        self.now = expected_slots(LEASE)[1]
        self.assertEqual(self.tick(), 'REVIEW_REQUIRED')
        self.assertEqual(self.runner.call_count, 1)

    def test_runner_exception_latches_hold(self):
        self.runner.side_effect = RuntimeError('secret text')
        self.assertEqual(self.tick(), 'INTERRUPTED')
        self.assertNotIn('secret', (self.state/'review-hold.json').read_text())

    def test_claimed_interruption_blocks_next_slot(self):
        self.ledger.claim(LEASE, SLOT, SLOT)
        self.now = expected_slots(LEASE)[1]
        self.assertEqual(self.tick(), 'REVIEW_REQUIRED')
        self.runner.assert_not_called()

    def test_result_write_failure_holds(self):
        real = self.persist
        def fail_result(path, doc):
            if path.parent.name == 'results':
                raise OSError('disk')
            real(path, doc)
        self.persist = fail_result
        self.assertEqual(self.tick(), 'INTERRUPTED')
        self.assertTrue((self.state/'review-hold.json').exists())

    def test_expiry_caps_execution(self):
        lease = Lease(3, SLOT-timedelta(days=7)+timedelta(seconds=30), SHA)
        self.read.return_value = lease
        self.assertEqual(self.tick(), 'OBSERVED')
        self.assertEqual(self.runner.call_args.args[1], 30)

    def test_projection_discards_extra_values(self):
        doc = fixture()
        doc['secret'] = 'https://private.invalid/listing'
        doc['arms']['a1']['item_sample']['url'] = 'private'
        out = s.project_report(encode(doc), 0)
        self.assertNotIn('private', json.dumps(out))
        self.assertEqual(out['pairs']['aa']['jaccard'], 0.333333)

    def test_projection_rejects_permission_or_count_conflicts(self):
        for doc in ({**fixture(), 'authorizes_listings': True},
                    {**fixture(), 'execution_order': 'OTHER'}):
            with self.assertRaises(ValueError):
                s.project_report(encode(doc), 0)
        doc = fixture()
        doc['pairs']['aa']['union'] = 4
        with self.assertRaises(ValueError):
            s.project_report(encode(doc), 0)
        doc = fixture()
        doc['arms']['a1']['item_sample']['unverified'] = 3
        with self.assertRaises(ValueError):
            s.project_report(encode(doc), 0)

    def test_incomplete_not_observed(self):
        self.assertEqual(s.project_report(encode(fixture()), 2)['status'], 'NOT_VERIFIED')
        with self.assertRaises(ValueError):
            s.project_report(b'x'*(s.MAX_OUTPUT+1), 0)

    def test_timer_and_service_contract(self):
        base = Path(__file__).resolve().parents[1]/'ops/oci/systemd'
        service = (base/'daangn-temporal.service').read_text()
        timer = (base/'daangn-temporal.timer').read_text()
        for line in ('User=daangn-temporal', 'NoNewPrivileges=yes', 'ProtectSystem=strict',
                     'KillMode=control-group', 'TimeoutStartSec=720', 'MemoryMax=650M'):
            self.assertIn(line, service)
        self.assertIn('OnCalendar=*-*-* 00,12:17:00 UTC', timer)
        self.assertIn('Persistent=false', timer)
        self.assertNotIn('ExecStart=/usr/local/libexec/oci-ci-alt', service)
        self.assertNotIn('--live', service)


if __name__ == '__main__':
    unittest.main()
