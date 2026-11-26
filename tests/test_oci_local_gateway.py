"""Offline finite command and metadata contract."""
import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ops.oci import local_gateway as g


class GatewayTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(g.os, 'geteuid', return_value=1000, create=True)
        p.start()
        self.addCleanup(p.stop)

    def test_denied_commands_do_not_execute(self):
        with patch.object(g.subprocess, 'run', side_effect=AssertionError):
            for value in ('restart', 'deploy', 'rollback', 'logs', 'health;sh', None, [], ''):
                self.assertEqual(g.execute(value)['status'], 'DENIED')
            self.assertEqual(g.main(['health', 'extra']), 2)

    def test_root_rejected_before_reads(self):
        with patch.object(g.os, 'geteuid', return_value=0), \
                patch.object(g, '_memory', side_effect=AssertionError):
            self.assertEqual(g.execute('health')['status'], 'UNPRIVILEGED_ACCOUNT_REQUIRED')

    def test_health_only_reports_finite_metadata(self):
        with patch.object(g, '_memory', return_value=600), patch.object(g, '_disk', return_value=30000):
            result = g.execute('health')
        self.assertEqual(result['status'], 'OK')
        self.assertEqual(result['mem_available_mib'], 600)
        self.assertEqual(result['disk_free_mib'], 30000)
        for flag in ('service_changed', 'database_accessed', 'collection_started', 'privileged_operation'):
            self.assertIs(result[flag], False)

    def test_unknown_and_malformed_output_not_exported(self):
        for data in (b'', b'LoadState=SECRET', b'LoadState=loaded\nLoadState=loaded',
                     b'\xff', b'X'*4097,
                     b'LoadState=loaded\nActiveState=active\nUnitFileState=enabled\nSecret=PRIVATE'):
            self.assertEqual(g._parse(data), g._unknown())
        with patch.object(g.subprocess, 'run', return_value=SimpleNamespace(
                returncode=1, stdout=b'SECRET')):
            self.assertNotIn('SECRET', json.dumps(g._unit('daangn-status.service')))
        with patch.object(g.subprocess, 'run', side_effect=subprocess.TimeoutExpired('fixed', 3)):
            self.assertEqual(g._unit('daangn-status.service'), g._unknown())

    def test_doctor_invokes_only_fixed_show_commands(self):
        reply = b'LoadState=loaded\nActiveState=active\nUnitFileState=enabled\n'
        with patch.object(g.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=reply)) as run, \
                patch.object(g.os.path, 'isfile', return_value=True), patch.object(g.os, 'access', return_value=True):
            result = g.execute('doctor')
        self.assertEqual(result['status'], 'OK')
        self.assertFalse(result['production_ready'])
        self.assertEqual(run.call_count, len(g.UNITS))
        for call, (_, unit) in zip(run.call_args_list, g.UNITS):
            self.assertEqual(call.args[0], ['/usr/bin/systemctl', '--no-pager', 'show',
                '--property=LoadState,ActiveState,UnitFileState', unit])
            self.assertEqual(call.kwargs['env'], g.ENV)
            self.assertNotIn('shell', call.kwargs)
        with patch.object(g.subprocess, 'run', side_effect=AssertionError):
            self.assertEqual(g._unit('arbitrary.service'), g._unknown())

    def test_partial_when_evidence_missing(self):
        with patch.object(g, '_unit', return_value=g._unknown()):
            self.assertEqual(g.execute('doctor')['status'], 'PARTIAL')
        with patch.object(g, '_memory', return_value=None):
            self.assertEqual(g.execute('health')['status'], 'PARTIAL')


if __name__ == '__main__':
    unittest.main()
