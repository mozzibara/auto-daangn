"""Local Linux test runner for an independently reviewed clean Git checkout.

No Actions dispatch, remote service access, token use or merge authorization.
The tests themselves are trusted code; this runner is not a network sandbox.
Use a fresh checkout and an external virtualenv, not a production directory.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r'[0-9a-f]{40}\Z')
CONTROL_TESTS = ('test_oci_release_control.py', 'test_oci_release_stage.py',
                 'test_oci_local_gateway.py')
MAX_OUTPUT = 4 * 1024 * 1024


def _git(root, env, *args):
    proc = subprocess.run(['/usr/bin/git', '-c', 'core.fsmonitor=false',
                           '-c', 'core.hooksPath=/dev/null', *args],
                          cwd=root, env=env, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          timeout=20, check=False)
    if proc.returncode or len(proc.stdout) > MAX_OUTPUT:
        raise ValueError('GIT_CHECK_FAILED')
    return proc.stdout


def _clean(root, env, expected):
    if _git(root, env, 'rev-parse', 'HEAD').decode('ascii').strip() != expected:
        raise ValueError('COMMIT_MISMATCH')
    if _git(root, env, 'status', '--porcelain=v1', '--untracked-files=all', '--ignored'):
        raise ValueError('CHECKOUT_NOT_CLEAN')


def _result(raw, returncode):
    if len(raw) > MAX_OUTPUT:
        return {'status': 'OUTPUT_LIMIT', 'tests': None}
    text = raw.decode('utf-8', errors='replace')
    runs = re.findall(r'(?m)^Ran (\d+) tests? in [\d.]+s\r?$', text)
    terminal = re.findall(r'(?m)^(OK|FAILED)(?: \(([^\r\n]*)\))?\r?$', text)
    if len(runs) != 1 or len(terminal) != 1 or int(runs[0]) < 1:
        return {'status': 'RESULT_UNVERIFIED', 'tests': None}
    counts = {name: 0 for name in ('failures', 'errors', 'skipped')}
    for name in counts:
        hit = re.search(r'\b' + name + r'=(\d+)\b', terminal[0][1])
        if hit:
            counts[name] = int(hit.group(1))
    if sum(counts.values()) > int(runs[0]):
        return {'status': 'RESULT_UNVERIFIED', 'tests': None}
    passed = (returncode == 0 and terminal[0][0] == 'OK' and
              counts['failures'] == counts['errors'] == 0 and
              counts['skipped'] < int(runs[0]))
    return {'status': 'PASS' if passed else 'FAIL', 'tests': int(runs[0]), **counts}


def run(root, expected, suite):
    if type(expected) is not str or not SHA.fullmatch(expected) or suite not in ('control', 'full'):
        raise ValueError('INVALID_TEST_REQUEST')
    with tempfile.TemporaryDirectory(prefix='daangn-offline-') as home:
        env = {'PATH': '/usr/bin:/bin', 'HOME': home, 'LC_ALL': 'C.UTF-8',
               'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1',
               'GIT_TERMINAL_PROMPT': '0', 'PYTHONUTF8': '1',
               'PYTHONDONTWRITEBYTECODE': '1', 'CI': 'true', 'GITHUB_ACTIONS': 'true'}
        _clean(root, env, expected)
        patterns = CONTROL_TESTS if suite == 'control' else ('test_*.py',)
        results = []
        for pattern in patterns:
            with tempfile.TemporaryFile() as log:
                try:
                    proc = subprocess.run([sys.executable, '-m', 'unittest', 'discover',
                                           '-s', 'tests', '-p', pattern, '-q'],
                                          cwd=root, env=env, stdin=subprocess.DEVNULL,
                                          stdout=log, stderr=subprocess.STDOUT,
                                          timeout=300, check=False)
                except subprocess.TimeoutExpired:
                    results.append({'status': 'TIMEOUT', 'tests': None})
                    continue
                log.seek(0)
                results.append(_result(log.read(MAX_OUTPUT + 1), proc.returncode))
        _clean(root, env, expected)
    return {'schema': 'oci_offline_regression_v1', 'commit': expected, 'suite': suite,
            'status': 'PASS' if all(x['status'] == 'PASS' for x in results) else 'FAIL',
            'results': results, 'github_ci_satisfied': False, 'merge_authorized': False,
            'network_sandboxed': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run reviewed local offline regression')
    parser.add_argument('--expected-commit', required=True)
    parser.add_argument('--suite', choices=('control', 'full'), default='control')
    args = parser.parse_args(argv)
    if not hasattr(os, 'geteuid') or os.geteuid() == 0:
        print('{"status":"UNPRIVILEGED_LINUX_REQUIRED"}')
        return 2
    try:
        result = run(ROOT, args.expected_commit, args.suite)
    except (ValueError, OSError, UnicodeError, subprocess.TimeoutExpired):
        result = {'status': 'BLOCKED', 'github_ci_satisfied': False, 'merge_authorized': False}
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
