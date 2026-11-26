"""Offline tests of the owner-only Issue command protocol."""
from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ops.oci import issue_gateway as g

CFG = {'repository': 'example/private-control', 'issue': 1, 'owner_id': 123}
FLOOR = '2026-01-01T00:00:00Z'
NEW = '2026-01-01T00:00:01Z'


def comment(cid, body, *, uid=123, created=NEW, updated=None, association='OWNER'):
    return {'id': cid, 'body': body, 'user': {'id': uid}, 'author_association': association,
            'created_at': created, 'updated_at': updated or created}


class Memory:
    def __init__(self):
        self.value = g.initial(datetime(2026, 1, 1, tzinfo=timezone.utc), CFG)
    def load(self):
        return deepcopy(self.value)
    def save(self, value):
        self.value = deepcopy(value)


class Client:
    def __init__(self, rows):
        self.rows = rows
        self.private = True
        self.sent = []
        self.fail_after_post = False
    def private_repository(self):
        return self.private
    def comments(self, since):
        return self.rows
    def post(self, body):
        self.sent.append(body)
        if self.fail_after_post:
            self.rows.append(comment(99, body))
            self.fail_after_post = False
            raise OSError('ambiguous response')


def execute(op):
    return {'schema': 'oci_local_gateway_v1', 'operation': op, 'status': 'OK'}


class ProtocolTests(unittest.TestCase):
    def test_owner_exact_fresh_unedited_command_only(self):
        store = Memory()
        client = Client([comment(1, '/local health', created=FLOOR),
                         comment(2, '/local health', uid=456),
                         comment(3, '/local doctor;sh'),
                         comment(4, '/local health', updated='2026-01-01T00:00:02Z'),
                         comment(5, '/local health', association='COLLABORATOR'),
                         comment(6, '/local doctor')])
        with patch.object(g.local_gateway, 'execute', side_effect=AssertionError):
            result = g.tick(client, store, CFG, execute=execute)
        self.assertTrue(result['command_executed'])
        self.assertEqual(len(client.sent), 1)
        self.assertIn('"operation": "doctor"', client.sent[0])
        self.assertEqual(store.value['cursor_id'], 6)
        self.assertEqual(g.tick(client, store, CFG, execute=execute)['status'], 'NO_COMMAND')
        self.assertEqual(len(client.sent), 1)

    def test_ambiguous_post_reconciles_without_reexecution_or_duplicate(self):
        store = Memory()
        client = Client([comment(10, '/local health')])
        client.fail_after_post = True
        with self.assertRaises(OSError):
            g.tick(client, store, CFG, execute=execute)
        self.assertIsNotNone(store.value['pending'])
        result = g.tick(client, store, CFG, execute=lambda _: self.fail('must not execute'))
        self.assertFalse(result['command_executed'])
        self.assertEqual(len(client.sent), 1)
        self.assertEqual(store.value['cursor_id'], 10)
        self.assertIsNone(store.value['pending'])

    def test_private_repository_and_bounded_batches_required(self):
        store = Memory()
        client = Client([comment(1, '/local health')])
        client.private = False
        with self.assertRaises(ValueError):
            g.tick(client, store, CFG, execute=execute)
        client.private = True
        client.rows *= 101
        with self.assertRaises(ValueError):
            g.tick(client, store, CFG, execute=execute)
        self.assertEqual(client.sent, [])
        self.assertEqual(store.value['cursor_id'], 0)

    def test_changed_configuration_cannot_reuse_cursor(self):
        store = Memory()
        client = Client([comment(10, '/local health')])
        with self.assertRaisesRegex(ValueError, 'CONTROL_CONFIG_CHANGED'):
            g.tick(client, store, dict(CFG, issue=2), execute=execute)
        self.assertEqual(client.sent, [])

    def test_pending_retry_without_remote_reply(self):
        store = Memory()
        client = Client([comment(10, '/local health')])
        with patch.object(client, 'post', side_effect=OSError):
            with self.assertRaises(OSError):
                g.tick(client, store, CFG, execute=execute)
        g.tick(client, store, CFG, execute=lambda _: self.fail('must not execute'))
        self.assertEqual(len(client.sent), 1)
        self.assertIsNone(store.value['pending'])

    def test_bad_config_and_redirect_denied(self):
        for repo in ('https://evil.example/a', '../a', 'a/..', 'a/b/c'):
            with self.assertRaises(ValueError):
                g.config(dict(CFG, repository=repo))
        with self.assertRaises(ValueError):
            g.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.example/')

    @unittest.skipUnless(os.name == 'posix', 'POSIX private state')
    def test_state_init_no_overwrite_and_symlink_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = g.StateStore(root, os.geteuid())
            store.save(Memory().value, create=True)
            with self.assertRaises(FileExistsError):
                store.save(Memory().value, create=True)
            self.assertEqual(store.load()['floor'], FLOOR)
            store.path.unlink()
            store.path.symlink_to(root / 'missing')
            with self.assertRaises(ValueError):
                store.load()


if __name__ == '__main__':
    unittest.main()
