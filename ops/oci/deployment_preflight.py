# -*- coding: utf-8 -*-
"""Fixed-path, administrator-local preflight. No service or database mutation.

Do not install this as a sudo command or execute it from a mutable Runner
checkout. Run only as part of an independently reviewed, pinned release.
The report is advisory, never a grant of deploy or collection authority.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess

STATE = Path("/var/lib/auto-daangn")
SPOOL = Path("/var/spool/auto-daangn-telegram")
KEYS = (
    "recipient-x25519-private.bin", "recipient-x25519-public.b64",
    "history-hmac-private.bin", "github-actions-read-token",
)
DB = STATE / "db" / "history.sqlite3"
RUNNER = "oci-runner"
UNITS = (
    "daangn-status.service", "daangn-status.timer",
    "daangn-actions-intake.service", "daangn-actions-intake.timer",
    "daangn-object-storage-backup.service", "daangn-object-storage-backup.timer",
)
TOOLS = (
    "/usr/bin/git", "/usr/bin/python3", "/usr/bin/sqlite3",
    "/usr/bin/getfacl", "/usr/bin/setfacl", "/usr/bin/google-chrome",
    "/usr/bin/xvfb-run", "/usr/bin/flock", "/usr/bin/systemctl",
    "/usr/sbin/runuser",
)
REQUIRED_CHECKS = (
    "accounts_present", "runner_identity_probe", "trusted_ancestors", "private_state_metadata",
    "runner_state_denied", "runner_database_denied", "runner_keys_denied",
    "telegram_spool_metadata", "telegram_spool_read_only",
    "status_service_expected", "status_timer_enabled",
    "backup_inactive", "required_tools_present",
)
_ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C", "HOME": "/root"}


def evaluate(evidence, *, intake="UNKNOWN") -> dict:
    evidence = evidence if type(evidence) is dict else {}
    checks = {key: evidence.get(key) is True for key in REQUIRED_CHECKS}
    intake = intake if type(intake) is str and intake in (
        "NOT_INSTALLED", "DISABLED", "ACTIVE", "UNKNOWN") else "UNKNOWN"
    blockers = [key for key, ok in checks.items() if not ok]
    if intake not in ("NOT_INSTALLED", "DISABLED"):
        blockers.append("intake_inactive")
    return {
        "schema": "oci_deployment_preflight_v1",
        "status": "BLOCKED" if blockers else "READY_FOR_REVIEW",
        "checks": checks, "blockers": blockers, "intake": intake,
        "installation_authorized": False, "collection_authorized": False,
        "database_written": False, "service_configuration_changed": False,
        "key_material_read": False, "privileged_delegation_verified": False,
    }


def _meta(path, uid, gid, mode, *, directory=False):
    try:
        info = path.lstat()
        kind = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
        return (kind and info.st_uid == uid and info.st_gid == gid
                and stat.S_IMODE(info.st_mode) == mode
                and (directory or info.st_nlink == 1))
    except OSError:
        return False


def _trusted_ancestors(path):
    try:
        for ancestor in path.parents:
            info = ancestor.lstat()
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                    or stat.S_IMODE(info.st_mode) & 0o022):
                return False
        return True
    except OSError:
        return False


def _runner_access(path, flag):
    # Call only a fixed binary with a fixed identity and finite test flags.
    if flag not in ("-r", "-w", "-x"):
        return None
    try:
        p = subprocess.run(
            ["/usr/sbin/runuser", "-u", RUNNER, "--", "/usr/bin/test",
             flag, str(path)], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=_ENV, timeout=8, check=False,
        )
        return True if p.returncode == 0 else False if p.returncode == 1 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _unit(unit):
    if unit not in UNITS:
        return {}
    try:
        p = subprocess.run(
            ["/usr/bin/systemctl", "show", "--no-pager",
             "--property=LoadState,ActiveState,UnitFileState,User,WorkingDirectory",
             unit], stdin=subprocess.DEVNULL, capture_output=True, text=True,
            env=_ENV, timeout=8, check=False,
        )
        if p.returncode or len(p.stdout) > 4096:
            return {}
        allowed = {"LoadState", "ActiveState", "UnitFileState", "User", "WorkingDirectory"}
        result = {}
        for line in p.stdout.splitlines():
            key, sep, value = line.partition("=")
            if sep and key in allowed:
                if key in result:
                    return {}
                result[key] = value
        return result
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        return {}


def _absent(unit):
    return (unit.get("LoadState") == "not-found"
            and unit.get("ActiveState") == "inactive"
            and unit.get("UnitFileState", "") == "")


def _disabled(unit):
    return (unit.get("LoadState") in ("loaded", "masked")
            and unit.get("ActiveState") == "inactive"
            and unit.get("UnitFileState") in ("disabled", "static", "masked"))


def _intake_state(service, timer):
    if _absent(service) and _absent(timer):
        return "NOT_INSTALLED"
    if _disabled(service) and _disabled(timer):
        return "DISABLED"
    if any(u.get("ActiveState") in ("active", "activating", "reloading")
           or u.get("UnitFileState") in ("enabled", "enabled-runtime")
           for u in (service, timer)):
        return "ACTIVE"
    return "UNKNOWN"


def collect() -> dict:
    # Import locally so synthetic contract tests run on Windows too.
    import pwd

    try:
        owner = pwd.getpwnam("daangn")
        runner = pwd.getpwnam(RUNNER)
        accounts = owner.pw_uid != 0 and runner.pw_uid not in (0, owner.pw_uid)
    except KeyError:
        return evaluate({})
    uid, gid = owner.pw_uid, owner.pw_gid
    paths = [STATE / "keys" / name for name in KEYS]
    evidence = {
        "accounts_present": accounts,
        # Positive control: failure to become the runner must never be
        # mistaken for successful denial of every private path.
        "runner_identity_probe": _runner_access(Path("/"), "-x") is True,
        "trusted_ancestors": _trusted_ancestors(STATE) and _trusted_ancestors(SPOOL),
        "private_state_metadata": all(
            _meta(p, uid, gid, 0o700, directory=True)
            for p in (STATE, STATE / "db", STATE / "keys")
        ) and all(_meta(p, uid, gid, 0o600) for p in [DB, *paths]),
        "runner_state_denied": _runner_access(STATE, "-x") is False,
        "runner_database_denied": all(_runner_access(DB, f) is False for f in ("-r", "-w")),
        "runner_keys_denied": all(_runner_access(p, f) is False
                                   for p in paths for f in ("-r", "-w")),
        "telegram_spool_metadata": _meta(SPOOL, uid, gid, 0o750, directory=True),
        "telegram_spool_read_only": (_runner_access(SPOOL, "-r") is True
                                      and _runner_access(SPOOL, "-x") is True
                                      and _runner_access(SPOOL, "-w") is False),
        "required_tools_present": all(os.path.isfile(p) and os.access(p, os.X_OK) for p in TOOLS),
    }
    service, timer, intake, intake_timer, backup, backup_timer = map(_unit, UNITS)
    evidence["status_service_expected"] = (
        service.get("LoadState") == "loaded" and service.get("User") == "daangn"
        and service.get("WorkingDirectory") == "/opt/auto-daangn"
    )
    evidence["status_timer_enabled"] = (
        timer.get("LoadState") == "loaded" and timer.get("ActiveState") == "active"
        and timer.get("UnitFileState") == "enabled"
    )
    evidence["backup_inactive"] = all(_absent(u) or _disabled(u) for u in (backup, backup_timer))
    return evaluate(evidence, intake=_intake_state(intake, intake_timer))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fixed OCI metadata-only deployment preflight")
    parser.parse_args(argv)
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        print(json.dumps({"schema": "oci_deployment_preflight_v1", "status": "ADMIN_REQUIRED"}))
        return 2
    try:
        result = collect()
    except (OSError, ImportError, RuntimeError, ValueError):
        result = evaluate({})
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "READY_FOR_REVIEW" else 2


if __name__ == "__main__":
    raise SystemExit(main())
