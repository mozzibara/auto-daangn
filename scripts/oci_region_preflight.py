# -*- coding: utf-8 -*-
"""Offline-only OCI Chrome baseline preflight. Never touches OCI keys or DB.

No marketplace request, outgoing IP lookup, login, network call, privileged
install, systemd unit, timers or profile state is performed by this script.

Run as a non-root user from the separate diagnostic checkout:
  python -m scripts.oci_region_preflight
  xvfb-run -a python -m scripts.oci_region_preflight --offline-browser --headed

A successful offline preflight is NOT evidence of region selection or
permission to collect public listings.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import platform
from pathlib import Path
import shutil
import sys

_SCHEMA = "oci_region_chrome_preflight_v1"
_ARCHITECTURES = ("x86_64", "aarch64")
_OS_ID = "ubuntu"
_OS_VERSION = "24.04"
_REQUIRED_LIBRARIES = ("playwright", "cryptography")


def _os_release(path=Path("/etc/os-release")):
    """Read only literal ID and VERSION_ID, never execute shell values."""
    try:
        content = path.read_text(encoding="utf-8")[:4000]
    except (OSError, UnicodeError):
        return {}
    data = {}
    for line in content.splitlines():
        key, _, raw = line.partition("=")
        if key not in ("ID", "VERSION_ID") or not _:
            continue
        data[key] = raw.strip().strip('"').strip("'")[:30]
    return data


def classify_environment(*, architecture, os_id, os_version,
                         python_version, chrome_available,
                         xvfb_available, xauth_available,
                         package_status, root, working_copy_isolated,
                         display_available=False):
    """Fixed schema only: no server hostname, paths, URLs or env values."""
    os_ok = (os_id == _OS_ID and os_version == _OS_VERSION)
    arch = (architecture if architecture in _ARCHITECTURES else "OTHER")
    python_ok = (type(python_version) is tuple and len(python_version) >= 2
                 and type(python_version[0]) is int
                 and type(python_version[1]) is int
                 and (python_version[0], python_version[1]) >= (3, 12))
    libraries_ok = (type(package_status) is dict and all(
        package_status.get(name) is True for name in _REQUIRED_LIBRARIES))
    browser_ok = chrome_available is True
    display_ok = (display_available is True or
                  (xvfb_available is True and xauth_available is True))
    safe_user = root is False
    ready = (os_ok and arch == "x86_64" and python_ok and libraries_ok
             and browser_ok and display_ok and safe_user
             and working_copy_isolated is True)
    return {
        "schema": _SCHEMA,
        "architecture": arch,
        "ubuntu_24_04": os_ok,
        "python_3_12_or_newer": python_ok,
        "google_chrome_stable_found": browser_ok,
        "xvfb_run_found": xvfb_available is True,
        "xauth_found": xauth_available is True,
        "display_present": display_available is True,
        "libraries_present": {
            name: libraries_ok if type(package_status) is not dict
            else package_status.get(name) is True
            for name in _REQUIRED_LIBRARIES
        },
        "non_root": safe_user,
        "separate_from_existing_oci_state": working_copy_isolated is True,
        "ready_for_offline_chrome_fixture": ready,
        "offline_fixture_passed": None,
        "public_site_visited": False,
        "region_selection_attempted": False,
        "third_party_ip_geolocation_attempted": False,
        "authorizes_listings": False,
    }


def inspect_environment(*, cwd=None):
    here = (Path(cwd) if cwd is not None else Path.cwd()).resolve()
    # Prevent accidental reuse of the owner's existing OCI operational stage,
    # state/keys or production service. A separate checkout is required.
    blocked = (
        Path("/opt/auto-daangn-public-stage"),
        Path("/opt/auto-daangn"),
        Path("/var/lib/auto-daangn"),
    )
    isolated = not any(here == base or base in here.parents for base in blocked)
    system = _os_release()
    library_status = {}
    for name in _REQUIRED_LIBRARIES:
        try:
            library_status[name] = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            library_status[name] = False
    chrome = (shutil.which("google-chrome") is not None or
              shutil.which("google-chrome-stable") is not None)
    return classify_environment(
        architecture=platform.machine(),
        os_id=system.get("ID"),
        os_version=system.get("VERSION_ID"),
        python_version=(sys.version_info.major, sys.version_info.minor),
        chrome_available=chrome,
        xvfb_available=shutil.which("xvfb-run") is not None,
        xauth_available=shutil.which("xauth") is not None,
        package_status=library_status,
        root=(hasattr(os, "geteuid") and os.geteuid() == 0),
        working_copy_isolated=isolated,
        display_available=bool(os.environ.get("DISPLAY")),
    )


async def _local_html_fixture(*, headed):
    """Delegates to existing one-page HTML fixture: no remote navigation."""
    from scripts.region_baseline_contrast import observe
    report = await observe(live=False, headed=headed, egress_context=False)
    return (report.get("status") == "OFFLINE_FIXTURE"
            and report.get("site_visit") == "NO_SITE_VISIT"
            and report.get("login_used") is False
            and report.get("authorizes_listings") is False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline-browser", action="store_true",
                        help="Start installed Chrome on local HTML only")
    parser.add_argument("--headed", action="store_true",
                        help="Requires DISPLAY or xvfb-run; no GUI login")
    parser.add_argument("--strict", action="store_true",
                        help="Fail when any offline preflight requirement is missing")
    args = parser.parse_args(argv)
    safe = inspect_environment()
    if args.offline_browser:
        if not safe["ready_for_offline_chrome_fixture"] or (
                args.headed and not safe["display_present"]):
            safe["offline_fixture_passed"] = False
        else:
            try:
                safe["offline_fixture_passed"] = asyncio.run(
                    _local_html_fixture(headed=args.headed))
            except Exception:
                # Never serialize exception text: it may contain a path,
                # downloaded executable details or local environment values.
                safe["offline_fixture_passed"] = False
    print(json.dumps(safe, ensure_ascii=False, sort_keys=True, indent=2))
    if args.offline_browser and safe["offline_fixture_passed"] is not True:
        return 2
    if args.strict and not safe["ready_for_offline_chrome_fixture"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
