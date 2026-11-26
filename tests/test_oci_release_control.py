"""Synthetic source selection tests; no production paths or commands."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ops.oci import release_control as r


@unittest.skipUnless(os.name == 'posix', 'POSIX metadata and lock contract')
class ReleaseControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'releases').mkdir()
        self.store = r.ReleaseStore(self.root, os.geteuid())

    def make(self, sha, text=b'hello'):
        path = self.root / 'releases' / sha
        path.mkdir()
        (path / 'module.py').write_bytes(text)
        raw = json.dumps({'schema': 'oci_release_v1', 'commit': sha,
                          'files': {'module.py': hashlib.sha256(text).hexdigest()}}).encode()
        (path / r.MANIFEST).write_bytes(raw)
        return path, {'commit': sha, 'manifest_sha256': hashlib.sha256(raw).hexdigest()}

    def test_verified_selection_idempotent_and_rollback(self):
        _, a = self.make('a'*40)
        _, b = self.make('b'*40)
        self.assertIsNone(self.store.state()['current'])
        self.assertEqual(self.store.verify(a), a)
        self.store.transition(expected_current=None, candidate=a)
        self.assertEqual(self.store.transition(expected_current=a['commit'], candidate=a)['current'], a)
        self.store.transition(expected_current=a['commit'], candidate=b)
        self.assertEqual(self.store.state()['previous'], a)
        self.store.transition(expected_current=b['commit'], rollback=True)
        self.assertEqual(self.store.state()['current'], a)
        self.assertEqual(self.store.state()['previous'], b)

    def test_bad_digest_and_unlisted_file_leave_selection_unchanged(self):
        _, a = self.make('a'*40)
        path, b = self.make('b'*40)
        self.store.transition(expected_current=None, candidate=a)
        before = self.store.selection.read_bytes()
        for bad in (dict(b, manifest_sha256='0'*64), dict(b, commit='../escape')):
            with self.assertRaises(ValueError):
                self.store.transition(expected_current=a['commit'], candidate=bad)
        (path / 'extra.py').write_text('extra')
        with self.assertRaises(ValueError):
            self.store.transition(expected_current=a['commit'], candidate=b)
        self.assertEqual(self.store.selection.read_bytes(), before)

    def test_tampering_previous_blocks_rollback(self):
        path, a = self.make('a'*40)
        _, b = self.make('b'*40)
        self.store.transition(expected_current=None, candidate=a)
        self.store.transition(expected_current=a['commit'], candidate=b)
        (path / 'module.py').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'RELEASE_FILE_DIGEST_MISMATCH'):
            self.store.transition(expected_current=b['commit'], rollback=True)
        self.assertEqual(self.store.state()['current'], b)

    def test_reject_symlink_hardlink_and_writable_source(self):
        path, a = self.make('a'*40)
        file = path / 'module.py'
        file.chmod(0o666)
        with self.assertRaises(ValueError):
            self.store.verify(a)
        file.chmod(0o644)
        other = self.root / 'other'
        os.link(file, other)
        with self.assertRaises(ValueError):
            self.store.verify(a)
        file.unlink()
        file.symlink_to(other)
        with self.assertRaises(ValueError):
            self.store.verify(a)

    def test_stale_compare_and_swap_and_no_previous(self):
        _, a = self.make('a'*40)
        with self.assertRaisesRegex(ValueError, 'NO_PREVIOUS_RELEASE'):
            self.store.transition(expected_current=None, rollback=True)
        self.store.transition(expected_current=None, candidate=a)
        with self.assertRaisesRegex(ValueError, 'SELECTION_CHANGED'):
            self.store.transition(expected_current=None, candidate=a)

    def test_atomic_replace_failure_preserves_selection(self):
        _, a = self.make('a'*40)
        _, b = self.make('b'*40)
        self.store.transition(expected_current=None, candidate=a)
        with patch.object(r.os, 'replace', side_effect=OSError('synthetic')):
            with self.assertRaises(OSError):
                self.store.transition(expected_current=a['commit'], candidate=b)
        self.assertEqual(self.store.state()['current'], a)
        self.assertEqual(list(self.root.glob('.selection-*')), [])

    def test_lock_contention_and_selection_symlink_fail_closed(self):
        _, a = self.make('a'*40)
        with self.store._lock():
            with self.assertRaises(BlockingIOError):
                self.store.transition(expected_current=None, candidate=a)
        self.store.selection.symlink_to(self.root / 'missing')
        with self.assertRaises(ValueError):
            self.store.state()


class CliTests(unittest.TestCase):
    def test_non_admin_denied_before_store(self):
        with patch.object(r.os, 'geteuid', return_value=123, create=True), \
                patch.object(r, 'ReleaseStore', side_effect=AssertionError):
            self.assertEqual(r.main(['status']), 2)


if __name__ == '__main__':
    unittest.main()
