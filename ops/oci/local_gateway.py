"""Actions-independent local diagnostics; no privileged or network commands.

This is the non-privileged gateway core, not a remote listener. Only bounded
metadata is returned. A future authenticated transport may call the exact
same finite operations without exposing a shell.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

COMMANDS = ('health', 'doctor')
UNITS = (
    ('status_service', 'daangn-status.service'),
    ('status_timer', 'daangn-status.timer'),
    ('intake_service', 'daangn-actions-intake.service'),
    ('intake_timer', 'daangn-actions-intake.timer'),
    ('backup_service', 'daangn-object-storage-backup.service'),
    ('backup_timer', 'daangn-object-storage-backup.timer'),
)
FIELDS = {
    'LoadState': ('loaded', 'not-found', 'masked', 'error', 'bad-setting'),
    'ActiveState': ('active', 'inactive', 'failed', 'activating', 'deactivating', 'reloading'),
    'UnitFileState': ('enabled', 'enabled-runtime', 'disabled', 'static', 'masked', 'masked-runtime', ''),
}
TOOLS = {
    'python': '/usr/bin/python3', 'git': '/usr/bin/git',
    'sqlite': '/usr/bin/sqlite3', 'flock': '/usr/bin/flock',
    'systemctl': '/usr/bin/systemctl',
}
ENV = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'SYSTEMD_COLORS': '0', 'SYSTEMD_PAGER': ''}


def _unknown():
    return {key: 'UNKNOWN' for key in FIELDS}


def _parse(raw):
    if type(raw) is not bytes or len(raw) > 4096:
        return _unknown()
    try:
        values = {}
        for line in raw.decode('ascii').splitlines():
            key, sep, value = line.partition('=')
            if not sep or key not in FIELDS or key in values or value not in FIELDS[key]:
                return _unknown()
            values[key] = value
        return values if set(values) == set(FIELDS) else _unknown()
    except UnicodeError:
        return _unknown()


def _unit(name):
    if name not in {unit for _, unit in UNITS}:
        return _unknown()
    try:
        proc = subprocess.run(
            ['/usr/bin/systemctl', '--no-pager', 'show',
             '--property=LoadState,ActiveState,UnitFileState', name],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=ENV, timeout=3, check=False,
        )
        return _parse(proc.stdout) if proc.returncode == 0 else _unknown()
    except (OSError, subprocess.TimeoutExpired):
        return _unknown()


def _memory():
    try:
        with Path('/proc/meminfo').open('r', encoding='ascii') as stream:
            raw = stream.read(16384)
        for line in raw.splitlines():
            key, sep, value = line.partition(':')
            parts = value.split()
            if key == 'MemAvailable' and sep and len(parts) == 2 and parts[1] == 'kB':
                if parts[0].isascii() and parts[0].isdecimal() and len(parts[0]) <= 16:
                    return int(parts[0]) // 1024
    except (OSError, UnicodeError):
        pass
    return None


def _disk():
    try:
        return shutil.disk_usage('/').free // (1024 * 1024)
    except OSError:
        return None


def execute(command):
    base = {'schema': 'oci_local_gateway_v1', 'service_changed': False,
            'database_accessed': False, 'collection_started': False,
            'privileged_operation': False}
    if type(command) is not str or command not in COMMANDS:
        return {**base, 'status': 'DENIED'}
    if not hasattr(os, 'geteuid') or os.geteuid() == 0:
        return {**base, 'status': 'UNPRIVILEGED_ACCOUNT_REQUIRED'}
    if command == 'health':
        mem, disk = _memory(), _disk()
        return {**base, 'operation': command,
                'status': 'OK' if mem is not None and disk is not None else 'PARTIAL',
                'mem_available_mib': mem, 'disk_free_mib': disk}
    units = {label: _unit(unit) for label, unit in UNITS}
    tools = {label: os.path.isfile(path) and os.access(path, os.X_OK)
             for label, path in TOOLS.items()}
    observed = all('UNKNOWN' not in state.values() for state in units.values())
    return {**base, 'operation': command,
            'status': 'OK' if observed and all(tools.values()) else 'PARTIAL',
            'units': units, 'tools': tools, 'production_ready': False}


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    result = execute(args[0] if len(args) == 1 else None)
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'OK' else 2


if __name__ == '__main__':
    raise SystemExit(main())
