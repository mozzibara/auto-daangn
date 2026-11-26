"""Prepare a source manifest and stage an independently verified release.

No network, archive extraction, subprocess, service or database operations.
A reviewed source export is prepared outside production. Root must separately
review and place its files in the root-owned incoming tree before promotion.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat

from ops.oci import release_control as r


def build_manifest(tree, commit, uid):
    tree = Path(tree)
    if not r._valid(r.SHA, commit):
        raise ValueError('INVALID_COMMIT')
    r._safe(tree, uid, directory=True)
    files = {}
    total = 0

    def fail(exc):
        raise exc

    for folder, dirs, names in os.walk(tree, followlinks=False, onerror=fail):
        for name in dirs:
            path = Path(folder) / name
            r._safe(path, uid, directory=True)
            r._relative(path.relative_to(tree).as_posix())
        for name in names:
            path = Path(folder) / name
            rel = r._relative(path.relative_to(tree).as_posix())
            if len(files) >= r.MAX_FILES:
                raise ValueError('TOO_MANY_FILES')
            data = r._read(path, uid, r.MAX_BYTES - total)
            total += len(data)
            files[rel] = r._sha(data)
    if not files:
        raise ValueError('EMPTY_RELEASE')
    # Empty directories are not manifestable and must not be present.
    for folder, dirs, _ in os.walk(tree, followlinks=False, onerror=fail):
        for name in dirs:
            rel = (Path(folder) / name).relative_to(tree).as_posix()
            if not any(p.startswith(rel + '/') for p in files):
                raise ValueError('EMPTY_RELEASE_DIRECTORY')
    raw = r._json({'schema': 'oci_release_v1', 'commit': commit, 'files': files})
    if len(raw) > 1024 * 1024:
        raise ValueError('MANIFEST_TOO_LARGE')
    target = tree / r.MANIFEST
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {'commit': commit, 'manifest_sha256': r._sha(raw), 'files': len(files)}


def _mkdir(path, uid, mode):
    try:
        path.mkdir(mode=mode)
    except FileExistsError:
        pass
    info = r._safe(path, uid, directory=True)
    if mode == 0o700 and stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('INCOMING_DIRECTORY_NOT_PRIVATE')


def prepare_layout(root, uid):
    root = Path(root)
    _mkdir(root, uid, 0o755)
    _mkdir(root / 'releases', uid, 0o755)
    _mkdir(root / 'incoming', uid, 0o700)
    _mkdir(root / 'incoming' / 'releases', uid, 0o700)
    return {'status': 'LAYOUT_READY', 'selection_changed': False}


def stage(root, uid, entry):
    entry = r._entry(entry)
    root = Path(root)
    store = r.ReleaseStore(root, uid)
    incoming = r.ReleaseStore(root / 'incoming', uid)
    for directory in (incoming.root, incoming.releases):
        if stat.S_IMODE(r._safe(directory, uid, directory=True).st_mode) != 0o700:
            raise ValueError('INCOMING_DIRECTORY_NOT_PRIVATE')
    target = store.releases / entry['commit']
    source = incoming.releases / entry['commit']
    with store._lock():
        if target.exists() or target.is_symlink():
            store.verify(entry)
            return {'status': 'ALREADY_STAGED', 'selection_changed': False, **entry}
        incoming.verify(entry)
        if incoming.releases.stat().st_dev != store.releases.stat().st_dev:
            raise ValueError('CROSS_DEVICE_STAGING_DENIED')
        os.rename(source, target)
        # On post-rename failure, inspect the destination before retrying.
        for directory in (incoming.releases, store.releases):
            fd = os.open(directory, os.O_DIRECTORY | os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        store.verify(entry)
        return {'status': 'STAGED', 'selection_changed': False, **entry}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local source manifest and staging only')
    sub = parser.add_subparsers(dest='command', required=True)
    make = sub.add_parser('manifest')
    make.add_argument('tree', type=Path)
    make.add_argument('commit')
    sub.add_parser('layout')
    promote = sub.add_parser('stage')
    promote.add_argument('commit')
    promote.add_argument('manifest_sha256')
    args = parser.parse_args(argv)
    if not hasattr(os, 'geteuid'):
        return 2
    uid = os.geteuid()
    try:
        if args.command == 'manifest':
            if uid == 0:
                raise ValueError('UNPRIVILEGED_BUILD_REQUIRED')
            result = build_manifest(args.tree, args.commit, uid)
        else:
            if uid != 0:
                raise ValueError('ADMIN_REQUIRED')
            for path in r.ROOT.parents:
                r._safe(path, 0, directory=True)
            if args.command == 'layout':
                result = prepare_layout(r.ROOT, 0)
            else:
                result = stage(r.ROOT, 0, {'commit': args.commit,
                                          'manifest_sha256': args.manifest_sha256})
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, RuntimeError):
        print('{"status":"RELEASE_STAGE_REJECTED"}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
