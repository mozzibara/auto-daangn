"""Isolated installer tests; no actual account, service or system mutations."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ops.oci import install_issue_gateway as i
from ops.oci import release_control as r
from ops.oci import release_stage as s

CFG = {'repository': 'example/private-control', 'issue': 1, 'owner_id': 123}


@unittest.skipUnless(os.name == 'posix', 'POSIX installation metadata')
class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for name in ('usr', 'etc', 'var', 'units'):
            (root / name).mkdir()
        self.layout = i.Layout(root / 'usr' / 'libexec' / 'control', root / 'etc' / 'control',
                               root / 'var' / 'control', root / 'units')
        self.uid, self.gid = os.geteuid(), os.getegid()
        checkout = Path(__file__).resolve().parents[1]
        self.files = {name: (checkout / name).read_bytes() for name in i.PAYLOAD}

    def apply(self, files=None, cfg=None):
        return i.install_files(self.layout, self.files if files is None else files,
            CFG if cfg is None else cfg, admin_uid=self.uid, admin_gid=self.gid,
            service_uid=self.uid, service_gid=self.gid)

    def test_prepares_inactive_and_idempotent(self):
        result = self.apply()
        self.assertEqual(result['status'], 'PREPARED')
        self.assertFalse(result['service_enable_requested'])
        self.assertFalse(result['token_written'])
        self.assertFalse((self.layout.state / 'token').exists())
        self.assertFalse((self.layout.state / 'cursor.json').exists())
        self.assertEqual(self.layout.state.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.layout.config / 'config.json').stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.apply(), result)

    def test_reject_unpinned_payload_before_layout_creation(self):
        bad = dict(self.files)
        bad['ops/oci/issue_gateway.py'] += b'\n# changed'
        with self.assertRaises(ValueError):
            self.apply(bad)
        self.assertFalse(self.layout.lib.exists())
        self.assertFalse(self.layout.state.exists())

    def test_conflicts_do_not_overwrite(self):
        self.apply()
        unit = self.layout.units / 'daangn-local-control.service'
        unit.write_bytes(b'preserve')
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(unit.read_bytes(), b'preserve')

    def test_config_change_and_symlink_refused(self):
        self.apply()
        path = self.layout.config / 'config.json'
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            self.apply(cfg=dict(CFG, issue=2))
        self.assertEqual(path.read_bytes(), before)
        path.unlink()
        path.symlink_to(self.layout.units / 'daangn-local-control.service')
        with self.assertRaises(ValueError):
            self.apply()

    def test_existing_token_is_not_read_or_replaced(self):
        self.apply()
        token = self.layout.state / 'token'
        token.write_bytes(b'synthetic-secret')
        token.chmod(0o600)
        self.apply()
        self.assertEqual(token.read_bytes(), b'synthetic-secret')

    def test_release_verification_and_bootstrap_pins(self):
        root = Path(self.tmp.name) / 'managed'
        s.prepare_layout(root, self.uid)
        sha = 'a'*40
        tree = root / 'incoming' / 'releases' / sha
        tree.mkdir()
        for name, data in self.files.items():
            path = tree / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        result = s.build_manifest(tree, sha, self.uid)
        entry = {key: result[key] for key in ('commit', 'manifest_sha256')}
        s.stage(root, self.uid, entry)
        self.assertEqual(i.verified_payload(r.ReleaseStore(root, self.uid), entry), self.files)
        with self.assertRaises(ValueError):
            i.verified_payload(r.ReleaseStore(root, self.uid), dict(entry, manifest_sha256='0'*64))


if __name__ == '__main__':
    unittest.main()
