"""Administrator-local release selection; no service execution or data mutation.

Only reviewed source trees belong here. The external expected manifest digest
must be authenticated by the operator, not obtained from the candidate itself.
The selection record is a prerequisite for a future trusted launcher, not a
claim that a release is installed or running.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from contextlib import contextmanager

ROOT = Path('/opt/auto-daangn-managed')
SHA = re.compile(r'[0-9a-f]{40}\Z')
DIGEST = re.compile(r'[0-9a-f]{64}\Z')
PART = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z')
MANIFEST = 'release-manifest.json'
MAX_FILES = 3000
MAX_BYTES = 32 * 1024 * 1024


def _valid(pattern, value):
    return type(value) is str and pattern.fullmatch(value) is not None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def _decode(raw):
    return json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object)


def _json(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _safe(path, uid, *, directory=False):
    info = path.lstat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if (not kind(info.st_mode) or info.st_uid != uid or
            info.st_mode & 0o7022 or (not directory and info.st_nlink != 1)):
        raise ValueError('UNTRUSTED_PATH_METADATA')
    return info


def _read(path, uid, limit):
    info = _safe(path, uid)
    if info.st_size > limit:
        raise ValueError('FILE_TOO_LARGE')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) != info.st_size or len(raw) > limit:
        raise ValueError('FILE_SIZE_CHANGED')
    return raw


def _entry(value):
    if (type(value) is not dict or set(value) != {'commit', 'manifest_sha256'} or
            not _valid(SHA, value['commit']) or not _valid(DIGEST, value['manifest_sha256'])):
        raise ValueError('INVALID_RELEASE_IDENTITY')
    return dict(value)


def _relative(value):
    if type(value) is not str or len(value) > 512:
        raise ValueError('INVALID_MANIFEST_PATH')
    parts = value.split('/')
    if not all(PART.fullmatch(p) and p not in ('__pycache__',) for p in parts):
        raise ValueError('INVALID_MANIFEST_PATH')
    if value == MANIFEST:
        raise ValueError('MANIFEST_SELF_REFERENCE')
    return value


class ReleaseStore:
    """Local trusted-owner library; CLI separately enforces root/ancestors."""
    def __init__(self, root, uid):
        self.root = Path(root)
        self.uid = uid
        self.releases = self.root / 'releases'
        self.selection = self.root / 'selection.json'
        _safe(self.root, uid, directory=True)
        _safe(self.releases, uid, directory=True)

    def verify(self, entry):
        entry = _entry(entry)
        release = self.releases / entry['commit']
        _safe(release, self.uid, directory=True)
        raw = _read(release / MANIFEST, self.uid, 1024 * 1024)
        if _sha(raw) != entry['manifest_sha256']:
            raise ValueError('MANIFEST_DIGEST_MISMATCH')
        manifest = _decode(raw)
        if (type(manifest) is not dict or set(manifest) != {'schema', 'commit', 'files'} or
                manifest['schema'] != 'oci_release_v1' or manifest['commit'] != entry['commit'] or
                type(manifest['files']) is not dict or not 1 <= len(manifest['files']) <= MAX_FILES):
            raise ValueError('INVALID_RELEASE_MANIFEST')
        expected = {}
        for name, digest in manifest['files'].items():
            name = _relative(name)
            if not _valid(DIGEST, digest):
                raise ValueError('INVALID_FILE_DIGEST')
            expected[name] = digest
        actual = set()
        total = 0
        for folder, dirs, files in os.walk(release, followlinks=False):
            for name in dirs:
                child = Path(folder) / name
                _safe(child, self.uid, directory=True)
                rel = _relative(child.relative_to(release).as_posix())
                if not any(p.startswith(rel + '/') for p in expected):
                    raise ValueError('UNMANIFESTED_DIRECTORY')
            for name in files:
                child = Path(folder) / name
                rel = child.relative_to(release).as_posix()
                if rel == MANIFEST:
                    continue
                if rel not in expected or len(actual) >= MAX_FILES:
                    raise ValueError('UNMANIFESTED_FILE')
                data = _read(child, self.uid, min(MAX_BYTES - total, MAX_BYTES))
                total += len(data)
                if _sha(data) != expected[rel]:
                    raise ValueError('RELEASE_FILE_DIGEST_MISMATCH')
                actual.add(rel)
        if actual != set(expected):
            raise ValueError('MISSING_RELEASE_FILE')
        return entry

    def state(self):
        try:
            raw = _read(self.selection, self.uid, 4096)
        except FileNotFoundError:
            return {'schema': 'oci_release_selection_v1', 'current': None, 'previous': None}
        doc = _decode(raw)
        if (type(doc) is not dict or set(doc) != {'schema', 'current', 'previous'} or
                doc['schema'] != 'oci_release_selection_v1' or doc['current'] is None):
            raise ValueError('INVALID_SELECTION_RECORD')
        current = _entry(doc['current'])
        previous = _entry(doc['previous']) if doc['previous'] is not None else None
        if previous is not None and previous['commit'] == current['commit']:
            raise ValueError('INVALID_SELECTION_RECORD')
        return {'schema': doc['schema'], 'current': current, 'previous': previous}

    @contextmanager
    def _lock(self):
        import fcntl
        path = self.root / '.selection.lock'
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            _safe(path, self.uid)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    def _write(self, doc):
        fd, name = tempfile.mkstemp(prefix='.selection-', dir=self.root)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(_json(doc))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.selection)
            dfd = os.open(self.root, os.O_DIRECTORY | os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def transition(self, *, expected_current, candidate=None, rollback=False):
        if expected_current is not None and not _valid(SHA, expected_current):
            raise ValueError('INVALID_EXPECTED_CURRENT')
        if type(rollback) is not bool or (rollback == (candidate is not None)):
            raise ValueError('EXACTLY_ONE_TRANSITION_REQUIRED')
        with self._lock():
            state = self.state()
            current = state['current']
            if (current['commit'] if current else None) != expected_current:
                raise ValueError('SELECTION_CHANGED')
            target = state['previous'] if rollback else _entry(candidate)
            if target is None:
                raise ValueError('NO_PREVIOUS_RELEASE')
            self.verify(target)
            if current is not None:
                self.verify(current)
                if target['commit'] == current['commit']:
                    if target != current:
                        raise ValueError('RELEASE_IDENTITY_CONFLICT')
                    return state
            state = {'schema': state['schema'], 'current': target, 'previous': current}
            self._write(state)
            return state


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local release selection only')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status')
    verify = sub.add_parser('verify')
    activate = sub.add_parser('select')
    rollback = sub.add_parser('rollback')
    for p in (verify, activate):
        p.add_argument('commit')
        p.add_argument('manifest_sha256')
    for p in (activate, rollback):
        p.add_argument('--expected-current', required=True, help='commit SHA or NONE')
    args = parser.parse_args(argv)
    if not hasattr(os, 'geteuid') or os.geteuid() != 0:
        print('{"status":"ADMIN_REQUIRED"}')
        return 2
    try:
        for path in ROOT.parents:
            _safe(path, 0, directory=True)
        store = ReleaseStore(ROOT, 0)
        if args.command == 'status':
            state = store.state()
        elif args.command == 'verify':
            state = store.verify({'commit': args.commit, 'manifest_sha256': args.manifest_sha256})
        else:
            state = store.transition(
                expected_current=None if args.expected_current == 'NONE' else args.expected_current,
                candidate={'commit': args.commit, 'manifest_sha256': args.manifest_sha256}
                if args.command == 'select' else None, rollback=args.command == 'rollback')
        print(json.dumps({'status': 'OK', 'selection': state,
                          'service_changed': False, 'database_written': False,
                          'collection_authorized': False}, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError):
        print('{"status":"RELEASE_CONTROL_REJECTED"}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
