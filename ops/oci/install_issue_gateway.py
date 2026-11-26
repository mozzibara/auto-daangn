"""Prepare the read-only Issue gateway from an independently verified release.

Run only from an independently reviewed trusted bootstrap, never a mutable
Runner checkout. This installs no token, grants no sudo, and starts no unit.
Existing files are never replaced; mismatches require operator review.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile

from ops.oci import issue_gateway as g
from ops.oci import release_control as r

PAYLOAD = {
    'ops/oci/issue_gateway.py': '2d50f23525181e4ab5db19cb0cffa1a20a620a8d47703e451132e037d34df57c',
    'ops/oci/local_gateway.py': '165eca58db9c35291289c91dd7c6aa855c66ac21b4bd97e48976bde832aa2622',
    'ops/oci/systemd/daangn-local-control.service': '5056c2474f6f490f57e71860f570743cfdf53d9dd3dd1eb97b571d84eb149520',
    'ops/oci/systemd/daangn-local-control.timer': 'a441a3c4bd273a9d93d04e3c0904b235f020700bb419a4236f554ed74630526e',
}


@dataclass(frozen=True)
class Layout:
    lib: Path
    config: Path
    state: Path
    units: Path


LAYOUT = Layout(Path('/usr/local/libexec/auto-daangn-control'), g.CONFIG.parent,
                g.STATE, Path('/etc/systemd/system'))


def verified_payload(store, entry):
    entry = store.verify(entry)
    source = store.releases / entry['commit']
    files = {}
    for name, digest in PAYLOAD.items():
        data = r._read(source / name, store.uid, 65536)
        if r._sha(data) != digest:
            raise ValueError('BOOTSTRAP_PAYLOAD_PIN_MISMATCH')
        files[name] = data
    return files


def _directory(path, uid, gid, mode):
    # Parent must be administrator-controlled; caller verifies each ancestor.
    created = False
    try:
        path.mkdir(mode=mode)
        created = True
    except FileExistsError:
        pass
    if created:
        os.chown(path, uid, gid, follow_symlinks=False)
        os.chmod(path, mode, follow_symlinks=False)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_gid != gid or
            stat.S_IMODE(info.st_mode) != mode):
        raise ValueError('INSTALL_DIRECTORY_CONFLICT')


def _once(path, data, uid, gid, mode):
    if path.exists() or path.is_symlink():
        info = r._safe(path, uid)
        if (info.st_gid != gid or stat.S_IMODE(info.st_mode) != mode or
                r._read(path, uid, 65536) != data):
            raise ValueError('INSTALL_FILE_CONFLICT')
        return
    fd, name = tempfile.mkstemp(prefix='.install-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fchown(stream.fileno(), uid, gid)
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        # Atomic no-replace publication; never overwrite a pre-existing file.
        os.link(name, path, follow_symlinks=False)
    finally:
        os.unlink(name)
    dfd = os.open(path.parent, os.O_DIRECTORY | os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def install_files(layout, files, cfg, *, admin_uid, admin_gid, service_uid, service_gid):
    cfg = g.config(cfg)
    if set(files) != set(PAYLOAD) or any(r._sha(files[p]) != digest for p, digest in PAYLOAD.items()):
        raise ValueError('UNVERIFIED_INSTALL_PAYLOAD')
    # The layout is fixed in the CLI. This function is also used with isolated test roots.
    for parent in (layout.lib.parent.parent, layout.config.parent, layout.state.parent, layout.units):
        r._safe(parent, admin_uid, directory=True)
    _directory(layout.lib.parent, admin_uid, admin_gid, 0o755)
    for folder in (layout.lib, layout.lib / 'ops', layout.lib / 'ops' / 'oci', layout.config):
        _directory(folder, admin_uid, admin_gid, 0o755)
    _directory(layout.state, service_uid, service_gid, 0o700)
    for path, data in files.items():
        target = (layout.units / Path(path).name if '/systemd/' in path else
                  layout.lib / path)
        _once(target, data, admin_uid, admin_gid, 0o644)
    raw = (json.dumps(cfg, sort_keys=True) + '\n').encode('utf-8')
    _once(layout.config / 'config.json', raw, admin_uid, service_gid, 0o640)
    return {'status': 'PREPARED', 'service_enable_requested': False,
            'service_start_requested': False,
            'token_written': False, 'production_state_modified': False}


def _account():
    import grp
    import pwd
    try:
        user = pwd.getpwnam(g.ACCOUNT)
    except KeyError:
        proc = subprocess.run(['/usr/sbin/useradd', '--system', '--user-group',
            '--home-dir', str(g.STATE), '--shell', '/usr/sbin/nologin', '--no-create-home', g.ACCOUNT],
            env={'PATH': '/usr/sbin:/usr/bin:/bin', 'LC_ALL': 'C'}, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20, check=False)
        if proc.returncode:
            raise ValueError('CONTROL_ACCOUNT_CREATE_FAILED')
        user = pwd.getpwnam(g.ACCOUNT)
    group = grp.getgrnam(g.ACCOUNT)
    if (user.pw_uid == 0 or user.pw_gid == 0 or user.pw_gid != group.gr_gid or
            user.pw_dir != str(g.STATE) or user.pw_shell != '/usr/sbin/nologin' or
            set(os.getgrouplist(g.ACCOUNT, user.pw_gid)) != {user.pw_gid}):
        raise ValueError('CONTROL_ACCOUNT_CONFLICT')
    for name in ('daangn', 'oci-runner'):
        try:
            other = pwd.getpwnam(name)
        except KeyError:
            continue
        if other.pw_uid == user.pw_uid or other.pw_gid == user.pw_gid:
            raise ValueError('CONTROL_ACCOUNT_NOT_SEPARATE')
    return user.pw_uid, user.pw_gid


def main(argv=None):
    parser = argparse.ArgumentParser(description='Prepare inactive read-only OCI control')
    parser.add_argument('--commit', required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--issue', required=True, type=int)
    parser.add_argument('--owner-id', required=True, type=int)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    if not hasattr(os, 'geteuid') or os.geteuid() != 0:
        print('{"status":"ADMIN_REQUIRED"}')
        return 2
    try:
        for directory in (r.ROOT, *r.ROOT.parents, LAYOUT.lib.parent.parent,
                          *LAYOUT.lib.parent.parent.parents, LAYOUT.config.parent,
                          *LAYOUT.config.parent.parents, LAYOUT.state.parent,
                          *LAYOUT.state.parent.parents, LAYOUT.units, *LAYOUT.units.parents):
            r._safe(directory, 0, directory=True)
        cfg = g.config({'repository': args.repository, 'issue': args.issue, 'owner_id': args.owner_id})
        files = verified_payload(r.ReleaseStore(r.ROOT, 0),
            {'commit': args.commit, 'manifest_sha256': args.manifest_sha256})
        if not args.apply:
            result = {'status': 'PAYLOAD_VERIFIED_FOR_REVIEW', 'installation_authorized': False}
        else:
            uid, gid = _account()
            result = install_files(LAYOUT, files, cfg, admin_uid=0, admin_gid=0,
                                   service_uid=uid, service_gid=gid)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, RuntimeError, KeyError, subprocess.TimeoutExpired):
        print('{"status":"INSTALL_PREPARATION_REJECTED"}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
