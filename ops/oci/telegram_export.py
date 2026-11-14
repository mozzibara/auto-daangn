# -*- coding: utf-8 -*-
"""Offline producer: export only independently attested price-drop alerts.

This runs AS the daangn data owner, WITHOUT Telegram credentials or network.
It does not activate live collection, change transaction status, or write to
GitHub. The private OCI sender accepts these bounded local JSON messages.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import unicodedata
from urllib.parse import urlsplit

from app_v5.history import HistoryStore
from app_v5.telegram_outbox import signed_price_drops

KEY = re.compile(r"^[0-9a-f]{64}$")
NAME = re.compile(r"^drop-([1-9]\d{0,18})-([a-f0-9]{16})\.json$")
SLUG = re.compile(r"^/kr/buy-sell/[A-Za-z0-9-]{4,128}/?$")
MAX_FILE = 4096
MAX_EVENTS = 100
LOOKBACK = timedelta(hours=72)


def _utc(value):
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if date.tzinfo is None:
            return None
        return date.astimezone(timezone.utc)
    except (ValueError, AttributeError, TypeError):
        return None


def _safe_title(title):
    if not isinstance(title, str):
        raise ValueError("INVALID_TITLE")
    text = "".join(" " if unicodedata.category(ch)[0] == "C" else ch
                   for ch in unicodedata.normalize("NFC", title))
    text = " ".join(text.split())[:100]
    return text or "제목 미확인"


def _safe_url(url):
    if not isinstance(url, str) or len(url) > 250:
        raise ValueError("INVALID_URL")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "www.daangn.com"
            or parsed.username or parsed.password
            or parsed.query or parsed.fragment
            or not SLUG.fullmatch(parsed.path)):
        raise ValueError("INVALID_URL")
    return url


def build_envelope(event):
    when = _utc(event.observed_at_utc)
    if (type(event.event_id) is not int or not 1 <= event.event_id <= 10**19
            or not isinstance(event.listing_key, str)
            or not KEY.fullmatch(event.listing_key)
            or type(event.price_krw) is not int
            or type(event.previous_price_krw) is not int
            or not 0 < event.price_krw < event.previous_price_krw <= 1_000_000_000
            or when is None):
        raise ValueError("INVALID_SIGNED_PRICE_DROP")
    return {
        "schema": "daangn_verified_price_drop_v1",
        "source": "SIGNED_PRICE_DROP_REVIEWABLE",
        "event_id": event.event_id,
        "listing_key": event.listing_key,
        "title": _safe_title(event.title),
        "url": _safe_url(event.url),
        "previous_price_krw": event.previous_price_krw,
        "price_krw": event.price_krw,
        "observed_at_utc": when.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "seller_confirmed_available": False,
        "transaction_status_verified": False,
        "smart_verified": False,
    }


def _directory(folder):
    if folder.is_symlink():
        raise ValueError("EXPORT_DIRECTORY_SYMLINK")
    folder.mkdir(mode=0o700, parents=False, exist_ok=True)
    st = folder.stat()
    if (not stat.S_ISDIR(st.st_mode)
            or (os.name == "posix"
                and (st.st_uid != os.getuid() or st.st_mode & 0o022))):
        raise ValueError("EXPORT_DIRECTORY_UNSAFE")


def _grant_runner_read(path: Path):
    # The production data owner grants read access ONLY to this one export
    # file. No ACL for the SQLite database, secret keys or staging inbox.
    # Requires acl/setfacl installed. Never spawn a shell.
    try:
        completed = subprocess.run(
            ["setfacl", "-m", "u:oci-runner:r--", str(path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("EXPORT_ACL_SHARE_UNAVAILABLE") from None
    if completed.returncode:
        raise ValueError("EXPORT_ACL_SHARE_FAILED")


def _prune_expired(folder: Path, *, now: datetime) -> int:
    # Retention is independent of Telegram delivery: old events are not
    # eligible for new alerts after 72h and do not become backups.
    removed = 0
    cutoff = now.timestamp() - 96*3600
    for file in folder.iterdir():
        if not NAME.fullmatch(file.name) or file.is_symlink():
            continue
        info = file.stat(follow_symlinks=False)
        if (not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid() or info.st_mode & 0o022):
            raise ValueError("UNSAFE_EXPIRED_EXPORT")
        if info.st_mtime < cutoff:
            file.unlink()
            removed += 1
    return removed


def export_verified_drops(store: HistoryStore, destination: Path, *,
                          now: datetime, max_events: int = MAX_EVENTS,
                          share_with_runner: bool = False):
    if now.tzinfo is None or not 1 <= max_events <= 500:
        raise ValueError("INVALID_EXPORT_SETTINGS")
    now = now.astimezone(timezone.utc)
    destination = Path(destination)
    if not destination.is_absolute() or destination.is_symlink():
        raise ValueError("ABSOLUTE_EXPORT_DIRECTORY_REQUIRED")
    candidates = []
    for event in signed_price_drops(store):
        message = build_envelope(event)
        when = _utc(message["observed_at_utc"])
        if now-LOOKBACK <= when <= now+timedelta(minutes=2):
            candidates.append(message)
    if len(candidates) > max_events:
        raise ValueError("VERIFIED_ALERT_EXPORT_CAP_EXCEEDED")
    _directory(destination)
    pruned = _prune_expired(destination, now=now)
    created = existing = 0
    for message in candidates:
        name = (f"drop-{message['event_id']}-"
                f"{message['listing_key'][:16]}.json")
        if not NAME.fullmatch(name):
            raise ValueError("UNSAFE_EXPORT_FILENAME")
        content = (json.dumps(message, sort_keys=True, ensure_ascii=False,
                              separators=(",", ":")) + "\n").encode("utf-8")
        if len(content) > MAX_FILE:
            raise ValueError("EXPORT_CONTENT_TOO_LARGE")
        path = destination / name
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != content:
                raise ValueError("EXISTING_EXPORT_CONTENT_MISMATCH")
            if share_with_runner:
                _grant_runner_read(path)
            existing += 1
            continue
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        if share_with_runner:
            _grant_runner_read(path)
        created += 1
    return {
        "schema": "daangn_export_v1", "status": "OK",
        "verified_price_drops_in_window": len(candidates),
        "created": created, "unchanged": existing, "pruned_expired": pruned,
        "source_authenticated": True,
        "telegram_token_accessed": False, "network_accessed": False,
        "new_listing_alerts_active": False,
    }


def export_from_state(state_dir, *, now=None):
    # Imports are local; production DB and HMAC identity remain owned by daangn.
    from ops.oci import runtime
    root = runtime._root(state_dir, create=False)
    _, history_key, _ = runtime._keyring(root)
    store = HistoryStore(root / "db" / "history.sqlite3", history_key)
    return export_verified_drops(
        store, root / "telegram-export",
        now=now or datetime.now(timezone.utc), share_with_runner=True
    )


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        result = export_from_state(args.state_dir)
    except Exception:
        # Never print data, filesystem paths or private identifiers.
        print(json.dumps({"schema": "daangn_export_v1",
                          "status": "EXPORT_BLOCKED"}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
