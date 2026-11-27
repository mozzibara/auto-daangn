"""Owner-local A/A/FAR diagnostic scheduling; never listing admission.

A NEW root-owned local approval is required; the expired GitHub lease is
not accepted. Existing robots checks and diagnostic execution are unchanged.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import tempfile
import time

from app_v5.temporal_slot_ledger import Lease, SlotLedger, expected_slots, WINDOW

HOME = Path('/var/lib/daangn-temporal-home')
CHECKOUT = HOME / 'code/auto-daangn-region-diagnostic'
STATE = Path('/var/lib/daangn-temporal-state')
CONFIG = Path('/etc/daangn-temporal')
PYTHON = '/opt/daangn-temporal-venv/bin/python'
SCHEMA = 'daangn_local_temporal_approval_v1'
PURPOSE = 'AA_FAR_DIAGNOSTIC_ONLY'
MAX_OUTPUT = 65536
MAX_SECONDS = 690
FLAGS = ('authorizes_listings', 'collection_started', 'database_written', 'telegram_used')
ARMS = ('a1', 'far', 'a2')
PAIRS = {'aa': ('a1', 'a2'), 'a1_far': ('a1', 'far'), 'a2_far': ('a2', 'far')}
COUNTS = ('rows', 'local_exact', 'same_city', 'outside_city', 'unverified',
          'region_object_rows', 'region_name_only_rows',
          'region_name_only_target_rows', 'region_name_only_other_rows',
          'region_id_rows', 'region_city_rows')


def utc_now():
    return datetime.now(timezone.utc)


def read_trusted(path):
    if os.name != 'posix':
        raise ValueError('LINUX_REQUIRED')
    p = Path(path)
    for ancestor in p.parents:
        info = ancestor.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('UNTRUSTED_CONFIG_DIRECTORY')
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0
                or before.st_nlink != 1 or before.st_mode & 0o022
                or before.st_size > 4096):
            raise ValueError('UNTRUSTED_CONFIG_FILE')
        data = stream.read(4097)
        after = os.fstat(stream.fileno())
        if len(data) > 4096 or (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
            raise ValueError('CONFIG_CHANGED')
        return data


def parse_approval(raw, source_sha):
    def unique(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise ValueError('DUPLICATE_APPROVAL_FIELD')
            out[k] = v
        return out
    doc = json.loads(raw, object_pairs_hook=unique)
    if (type(doc) is not dict or set(doc) != {'schema', 'purpose', 'approval_id', 'starts_at', 'source_sha'}
            or doc['schema'] != SCHEMA or doc['purpose'] != PURPOSE
            or doc['source_sha'] != source_sha or type(doc['starts_at']) is not str
            or len(doc['starts_at']) > 40):
        raise ValueError('INVALID_LOCAL_APPROVAL')
    return Lease(doc['approval_id'], datetime.fromisoformat(doc['starts_at'].replace('Z', '+00:00')), source_sha)


def read_approval():
    sha = read_trusted(CONFIG / 'source.sha').decode('ascii').strip()
    try:
        raw = read_trusted(CONFIG / 'approval.json')
    except FileNotFoundError:
        return None
    return parse_approval(raw, sha)


def due_slot(lease, now):
    if lease is None or not lease.starts_at <= now < lease.expires_at:
        return None
    if lease.stopped_at is not None and now >= lease.stopped_at:
        return None
    return next((s for s in expected_slots(lease) if s <= now < s + WINDOW), None)


def project_report(raw, returncode):
    """Reproject bounded aggregates; do not preserve arbitrary strings or IDs."""
    if type(raw) is not bytes or len(raw) > MAX_OUTPUT:
        raise ValueError('REPORT_BOUNDARY')
    report = json.loads(raw)
    if (type(report) is not dict or report.get('schema') != 'oci_region_aa_far_aggregate_v1'
            or any(report.get(k) is not False for k in FLAGS)):
        raise ValueError('REPORT_BOUNDARY')
    if returncode != 0 or report.get('status') != 'OBSERVED':
        return {'status': 'NOT_VERIFIED', **dict.fromkeys(FLAGS, False)}
    if report.get('execution_order') != 'BULDANG_SADANG_BULDANG':
        raise ValueError('REPORT_ORDER')
    arms, pairs = report.get('arms'), report.get('pairs')
    if type(arms) is not dict or set(arms) != set(ARMS) or type(pairs) is not dict or set(pairs) != set(PAIRS):
        raise ValueError('REPORT_SHAPE')
    projected = {}
    for arm in ARMS:
        a = arms[arm]
        if (type(a) is not dict or a.get('region_status') != 'TARGET_REGION_CONFIRMED_DIAGNOSTIC'
                or a.get('fresh_route') != 'ONE_FRESH'):
            raise ValueError('ARM_UNVERIFIED')
        s = a.get('item_sample')
        if (type(s) is not dict or s.get('status') != 'COMPLETE'
                or s.get('identity_coverage') != 'COMPLETE'
                or any(type(s.get(k)) is not int or not 0 <= s[k] <= 650 for k in COUNTS)):
            raise ValueError('ARM_SAMPLE_INVALID')
        n = s['rows']
        if (n == 0 or any(s[k] > n for k in COUNTS)
                or sum(s[k] for k in COUNTS[1:5]) != n
                or s['region_name_only_target_rows'] + s['region_name_only_other_rows'] != s['region_name_only_rows']
                or any(s[k] > s['region_object_rows'] for k in ('region_name_only_rows', 'region_id_rows', 'region_city_rows'))):
            raise ValueError('ARM_COUNT_CONFLICT')
        projected[arm] = {k: s[k] for k in COUNTS}
    comparison = {}
    for name, (left, right) in PAIRS.items():
        p = pairs[name]
        if type(p) is not dict or any(type(p.get(k)) is not int or not 0 <= p[k] <= 1300
                for k in ('overlap', 'left_only', 'right_only', 'union', 'symmetric_difference')):
            raise ValueError('PAIR_COUNT_INVALID')
        overlap, l, r = p['overlap'], p['left_only'], p['right_only']
        if (overlap+l != projected[left]['rows'] or overlap+r != projected[right]['rows']
                or p['union'] != overlap+l+r or p['symmetric_difference'] != l+r):
            raise ValueError('PAIR_COUNT_CONFLICT')
        comparison[name] = {'overlap': overlap, 'left_only': l, 'right_only': r,
                            'union': overlap+l+r, 'symmetric_difference': l+r,
                            'jaccard': round(overlap/(overlap+l+r), 6)}
    return {'status': 'OBSERVED', 'arms': projected, 'pairs': comparison,
            'backend_geographic_scope_proven': False, 'statistical_significance_proven': False,
            **dict.fromkeys(FLAGS, False)}


def execute(keep_running, seconds):
    """Linux-only fixed child, bounded output, no inherited credentials."""
    if seconds <= 0 or not keep_running():
        return {'status': 'INTERRUPTED'}
    with tempfile.TemporaryDirectory(prefix='daangn-temporal-') as temp:
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(HOME), 'LANG': 'C.UTF-8',
               'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1',
               'XDG_CACHE_HOME': temp+'/cache', 'XDG_CONFIG_HOME': temp+'/config',
               'XDG_DATA_HOME': temp+'/data', 'TMPDIR': temp}
        proc = subprocess.Popen(
            ['/usr/bin/xvfb-run', '-a', PYTHON, '-s', '-B', '-m',
             'ops.oci.region_aa_far', '--live', '--headed',
             '--owner-approval', 'I_APPROVE_OCI_REGION_AA_FAR_V1'],
            cwd=CHECKOUT, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            start_new_session=True)
        data = bytearray()
        deadline = time.monotonic() + min(seconds, MAX_SECONDS)
        try:
            with selectors.DefaultSelector() as sel:
                sel.register(proc.stdout, selectors.EVENT_READ)
                while True:
                    if time.monotonic() >= deadline or not keep_running():
                        return {'status': 'INTERRUPTED'}
                    for key, _ in sel.select(timeout=0.5):
                        part = os.read(key.fileobj.fileno(), 8192)
                        if not part:
                            sel.unregister(key.fileobj)
                            break
                        data.extend(part)
                        if len(data) > MAX_OUTPUT:
                            return {'status': 'NOT_VERIFIED'}
                    if not sel.get_map() and proc.poll() is not None:
                        if not keep_running() or time.monotonic() >= deadline:
                            return {'status': 'INTERRUPTED'}
                        return project_report(bytes(data), proc.returncode)
        finally:
            # systemd control-group cleanup also handles detached descendants.
            if proc.returncode is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            proc.stdout.close()
            proc.wait(timeout=5)


def write_once(path, doc):
    fd, name = tempfile.mkstemp(prefix='.record-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(doc, stream, sort_keys=True, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.link(name, path)
        dfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        os.unlink(name)


def tick(state, read, runner, clock=utc_now, persist=write_once):
    state = Path(state)
    hold = state / 'review-hold.json'
    if hold.exists() or hold.is_symlink():
        return 'REVIEW_REQUIRED'
    lease = read()
    slot = due_slot(lease, clock())
    if slot is None:
        return 'NO_APPROVED_SLOT'
    ledger = SlotLedger(state / 'slots.sqlite3')
    if read() != lease:
        return 'APPROVAL_CHANGED'
    now = clock()
    if due_slot(lease, now) != slot:
        return 'NO_APPROVED_SLOT'
    claim = ledger.claim(lease, slot, now)
    if claim != 'CLAIMED':
        return claim
    end = min(slot+WINDOW, lease.expires_at, lease.stopped_at or lease.expires_at)
    def keep_running():
        try:
            current = clock()
            return now <= current < end and read() == lease
        except Exception:
            return False
    outcome = 'INTERRUPTED'
    try:
        result = runner(keep_running, min(MAX_SECONDS, (end-clock()).total_seconds())) if keep_running() else {'status': 'INTERRUPTED'}
        if not keep_running():
            result = {'status': 'INTERRUPTED'}
        outcome = result.get('status')
        if outcome not in ('OBSERVED', 'NOT_VERIFIED', 'INTERRUPTED'):
            outcome, result = 'NOT_VERIFIED', {'status': 'NOT_VERIFIED'}
        persist(state/'results'/(slot.strftime('%Y%m%dT%H%M%SZ')+'.json'),
                {'slot_utc': slot.isoformat(), 'source_sha': lease.source_sha,
                 'result': result, **dict.fromkeys(FLAGS, False)})
    except Exception:
        outcome = 'INTERRUPTED'
    # If hold persistence fails, leave the attempt RUNNING, not replayable.
    if outcome != 'OBSERVED':
        persist(hold, {'status': outcome, 'slot_utc': slot.isoformat()})
    ledger.finish(lease, slot, clock(), outcome)
    return outcome


def check_runtime():
    if os.name != 'posix' or os.geteuid() == 0 or Path.cwd().resolve() != CHECKOUT:
        raise ValueError('ISOLATED_NON_ROOT_CHECKOUT_REQUIRED')
    import pwd
    if pwd.getpwuid(os.geteuid()).pw_name != 'daangn-temporal' or Path.home().resolve() != HOME:
        raise ValueError('DEDICATED_ACCOUNT_REQUIRED')
    for p in (CHECKOUT, CHECKOUT.parent, HOME):
        st = p.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
            raise ValueError('IMMUTABLE_CHECKOUT_REQUIRED')
    for p in (STATE, STATE/'results'):
        st = p.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid() or st.st_mode & 0o077:
            raise ValueError('PRIVATE_STATE_REQUIRED')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'status', 'tick'))
    args = parser.parse_args(argv)
    try:
        check_runtime()
        if args.command == 'init':
            SlotLedger.initialize(STATE/'slots.sqlite3')
            status = 'INITIALIZED_NO_APPROVAL'
        elif args.command == 'status':
            lease = read_approval()
            rows = SlotLedger(STATE/'slots.sqlite3').snapshot(lease, utc_now()) if lease else []
            print(json.dumps({'status': 'READ_ONLY', 'slots': rows,
                              'review_required': (STATE/'review-hold.json').exists(),
                              'authorizes_listings': False}, sort_keys=True))
            return 0
        else:
            status = tick(STATE, read_approval, execute)
        print(json.dumps({'status': status, 'authorizes_listings': False}, sort_keys=True))
        return 2 if status in ('INTERRUPTED', 'NOT_VERIFIED', 'REVIEW_REQUIRED', 'CLOCK_REGRESSION') else 0
    except Exception:
        print('{"status":"SCHEDULER_BLOCKED","authorizes_listings":false}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
