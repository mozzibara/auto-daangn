"""Synthetic manifest and source promotion tests."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ops.oci import release_control as r
from ops.oci import release_stage as s


@unittest.skipUnless(os.name == 'posix', 'POSIX staging contract')
class StageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'managed'
        self.uid = os.geteuid()
        s.prepare_layout(self.root, self.uid)
        self.store = r.ReleaseStore(self.root, self.uid)

    def build(self, commit='a'*40):
        tree = self.root / 'incoming' / 'releases' / commit
        tree.mkdir()
        (tree / 'ops').mkdir()
        (tree / 'ops' / 'runtime.py').write_text('synthetic code')
        result = s.build_manifest(tree, commit, self.uid)
        self.assertEqual(result['files'], 1)
        return tree, {k: result[k] for k in ('commit', 'manifest_sha256')}

    def test_layout_idempotent_without_selection_or_state(self):
        self.assertEqual(s.prepare_layout(self.root, self.uid)['status'], 'LAYOUT_READY')
        self.assertIsNone(self.store.state()['current'])
        self.assertEqual(set(p.name for p in self.root.iterdir()), {'incoming', 'releases'})

    def test_verified_stage_then_explicit_selection(self):
        tree, entry = self.build()
        result = s.stage(self.root, self.uid, entry)
        self.assertEqual(result['status'], 'STAGED')
        self.assertFalse(tree.exists())
        self.assertIsNone(self.store.state()['current'])
        self.assertEqual(s.stage(self.root, self.uid, entry)['status'], 'ALREADY_STAGED')
        self.store.transition(expected_current=None, candidate=entry)
        self.assertEqual(self.store.state()['current'], entry)

    def test_bad_digest_or_changed_source_never_promoted(self):
        tree, entry = self.build()
        with self.assertRaises(ValueError):
            s.stage(self.root, self.uid, dict(entry, manifest_sha256='0'*64))
        (tree / 'ops' / 'runtime.py').write_text('changed')
        with self.assertRaises(ValueError):
            s.stage(self.root, self.uid, entry)
        self.assertTrue(tree.exists())
        self.assertFalse((self.root / 'releases' / entry['commit']).exists())

    def test_manifest_never_overwritten_and_private_inputs_not_followed(self):
        tree, entry = self.build()
        previous = (tree / r.MANIFEST).read_bytes()
        with self.assertRaises(ValueError):
            s.build_manifest(tree, entry['commit'], self.uid)
        self.assertEqual((tree / r.MANIFEST).read_bytes(), previous)
        other = self.root / 'incoming' / 'releases' / ('b'*40)
        other.mkdir()
        (other / 'link.py').symlink_to(tree / 'ops' / 'runtime.py')
        with self.assertRaises(ValueError):
            s.build_manifest(other, 'b'*40, self.uid)
        self.assertFalse((other / r.MANIFEST).exists())

    def test_hidden_files_and_empty_dirs_fail_closed(self):
        tree = self.root / 'incoming' / 'releases' / ('c'*40)
        tree.mkdir()
        (tree / '.env').write_text('synthetic')
        with self.assertRaises(ValueError):
            s.build_manifest(tree, 'c'*40, self.uid)
        (tree / '.env').unlink()
        (tree / 'source.py').write_text('synthetic')
        (tree / 'empty').mkdir()
        with self.assertRaises(ValueError):
            s.build_manifest(tree, 'c'*40, self.uid)

    def test_existing_target_and_rename_failure_do_not_overwrite(self):
        tree, entry = self.build()
        with patch.object(s.os, 'rename', side_effect=OSError('synthetic')):
            with self.assertRaises(OSError):
                s.stage(self.root, self.uid, entry)
        self.assertTrue(tree.exists())
        target = self.root / 'releases' / entry['commit']
        target.mkdir()
        (target / 'existing').write_text('preserve')
        with self.assertRaises(OSError):
            s.stage(self.root, self.uid, entry)
        self.assertEqual((target / 'existing').read_text(), 'preserve')

    def test_nonprivate_incoming_rejected_without_chmod(self):
        _, entry = self.build()
        folder = self.root / 'incoming'
        folder.chmod(0o755)
        with self.assertRaises(ValueError):
            s.stage(self.root, self.uid, entry)
        self.assertEqual(folder.stat().st_mode & 0o777, 0o755)


if __name__ == '__main__':
    unittest.main()
