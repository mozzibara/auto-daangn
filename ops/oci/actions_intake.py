# -*- coding: utf-8 -*-
"""OCI reads ONLY owner-approved, signed v4.34 Actions artifacts.

Uses GitHub Actions:read token from a private file (Deploy Key is for Git SSH).
No live marketplace visit, no webhook listener, no LLM, no Telegram sender.
Offline synthetic tests inject a fake GitHub client.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat
import sys
import tempfile
from typing import Protocol
from urllib import error, parse, request
from zipfile import ZipFile, BadZipFile

from app_v5.history import HistoryStore
from ops.oci import runtime
from ops.oci.backup import require_recent_offsite_backup

REPO = "mozzibara/auto-daangn"
OWNER = "mozzibara"
WORKFLOW = ".github/workflows/secure-links-v434.yml"
ARTIFACT_PREFIX = "daangn-v434-sealed-links-"
API = f"https://api.github.com/repos/{REPO}"
MAX_ARCHIVE = 5 * 1024 * 1024
MAX_SINGLE_FILE = 512 * 1024
MAX_TOTAL = 3 * 1024 * 1024
EXPECTED = frozenset(runtime.SIGNED_FILES.values())
ALLOWED_EVENTS = frozenset(("workflow_dispatch", "issue_comment"))
TOKEN_RELATIVE = "keys/github-actions-read-token"


class GitHubSource(Protocol):
    def list_runs(self) -> dict: ...
    def list_artifacts(self, run_id: int, name: str) -> dict: ...
    def download_zip(self, artifact_id: int) -> bytes: ...


class _StopRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHubREST:
    """HTTPS GitHub API requests. Never forward Authorization to ZIP redirect."""

    def __init__(self, token_file: Path, *, timeout_seconds: int = 18):
        file = Path(token_file)
        if (file.is_symlink() or not file.is_file() or
                (os.name == "posix" and stat.S_IMODE(file.stat().st_mode) & 0o077)):
            raise ValueError("GITHUB_READ_TOKEN_FILE_MUST_BE_0600")
        token = file.read_text(encoding="utf-8").strip()
        if (not 20 <= len(token) <= 500 or any(ch.isspace() for ch in token)):
            raise ValueError("INVALID_GITHUB_READ_TOKEN")
        self._token = token
        self.timeout = timeout_seconds

    def _get(self, suffix: str, *, redirect: bool = False,
             max_bytes: int = 512 * 1024) -> bytes | str:
        if not suffix.startswith("/") or "//" in suffix or ".." in suffix:
            raise ValueError("INVALID_API_PATH")
        path = API + suffix
        req = request.Request(path, headers={
            "Authorization": "Bearer " + self._token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "auto-daangn-oci-actions-intake/1",
        })
        try:
            with request.build_opener(_StopRedirect()).open(
                    req, timeout=self.timeout) as resp:
                raw = resp.read(max_bytes + 1)
                if len(raw) > max_bytes:
                    raise ValueError("GITHUB_RESPONSE_TOO_LARGE")
                return raw
        except error.HTTPError as exc:
            if not redirect or exc.code != 302:
                raise ValueError("GITHUB_API_REQUEST_FAILED") from None
            location = exc.headers.get("Location", "")
            parts = parse.urlsplit(location)
            # GitHub API supplies a short-lived HTTPS download link. It is
            # NEVER sent the Bearer token. HTTPS host is strictly checked.
            host = (parts.hostname or "").lower()
            if (parts.scheme != "https" or parts.username or parts.password
                    or parts.port not in (None, 443)
                    or not (host.endswith(".blob.core.windows.net")
                            or host.endswith(".actions.githubusercontent.com")
                            or host.endswith(".githubusercontent.com"))
                    or not parts.path):
                raise ValueError("UNTRUSTED_GITHUB_ARTIFACT_REDIRECT")
            try:
                with request.urlopen(request.Request(
                        location, headers={"User-Agent":
                        "auto-daangn-oci-actions-intake/1"}),
                        timeout=self.timeout) as stream:
                    data = stream.read(max_bytes + 1)
            except (error.HTTPError, error.URLError, TimeoutError):
                raise ValueError("GITHUB_ZIP_DOWNLOAD_FAILED") from None
            if len(data) > max_bytes:
                raise ValueError("GITHUB_ZIP_TOO_LARGE")
            return data
        except (error.URLError, TimeoutError, OSError):
            raise ValueError("GITHUB_API_UNREACHABLE") from None

    def _json(self, suffix: str) -> dict:
        try:
            data = json.loads(self._get(suffix))
        except (ValueError, UnicodeError, TypeError):
            raise ValueError("GITHUB_JSON_INVALID") from None
        if type(data) is not dict:
            raise ValueError("GITHUB_JSON_OBJECT_REQUIRED")
        return data

    def list_runs(self) -> dict:
        # GitHub retains success runs for far longer than the one-day capture
        # artifacts. Searching all history eventually exceeds per_page=100
        # and permanently blocks intake. Bound the query to recent UTC dates
        # (at least 48 hours, up to 72 hours due to date granularity).
        # Never silently truncate: poll_once rejects an incomplete result.
        from_utc_date = (datetime.now(timezone.utc) -
                         timedelta(hours=48)).date().isoformat()
        return self._json(
            "/actions/workflows/secure-links-v434.yml/runs"
            "?status=success&per_page=100&page=1&created=" +
            parse.quote(">=" + from_utc_date, safe="")
        )

    def list_artifacts(self, run_id: int, name: str) -> dict:
        return self._json(
            f"/actions/runs/{run_id}/artifacts"
            "?per_page=100&name=" + parse.quote(name)
        )

    def download_zip(self, artifact_id: int) -> bytes:
        return self._get(f"/actions/artifacts/{artifact_id}/zip",
                         redirect=True, max_bytes=MAX_ARCHIVE)


def _valid_run(run: dict) -> tuple[int, int, str] | None:
    if type(run) is not dict:
        return None
    run_id, attempt, sha = (run.get("id"), run.get("run_attempt"),
                            run.get("head_sha"))
    if (type(run_id) is not int or run_id < 1
            or type(attempt) is not int or attempt < 1
            or not isinstance(sha, str) or not runtime.COMMIT.fullmatch(sha)
            or run.get("status") != "completed"
            or run.get("conclusion") != "success"
            or run.get("event") not in ALLOWED_EVENTS
            or run.get("path", "").split("@")[0] != WORKFLOW
            or run.get("head_branch") != "main"
            or type(run.get("repository")) is not dict
            or run["repository"].get("full_name") != REPO
            or type(run.get("head_repository")) is not dict
            or run["head_repository"].get("full_name") != REPO
            or type(run.get("actor")) is not dict
            or run["actor"].get("login") != OWNER
            or type(run.get("triggering_actor")) is not dict
            or run["triggering_actor"].get("login") != OWNER):
        return None
    return run_id, attempt, sha


def _pick_artifact(doc: dict, *, run_id: int) -> int | None:
    if type(doc) is not dict or type(doc.get("artifacts")) is not list:
        raise ValueError("INVALID_GITHUB_ARTIFACT_CATALOG")
    matches = [x for x in doc["artifacts"] if type(x) is dict
               and x.get("name") == ARTIFACT_PREFIX + str(run_id)
               and x.get("expired") is False]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError("DUPLICATE_UNTRUSTED_ARTIFACTS")
    art = matches[0]
    if (type(art.get("id")) is not int or art["id"] < 1
            or type(art.get("size_in_bytes")) is not int
            or not 0 < art["size_in_bytes"] <= MAX_ARCHIVE
            or type(art.get("workflow_run")) is not dict
            or art["workflow_run"].get("id") != run_id):
        raise ValueError("UNTRUSTED_ARTIFACT_METADATA")
    return art["id"]


def _unpack_exact(zip_bytes: bytes, destination: Path) -> None:
    if type(zip_bytes) is not bytes or not 0 < len(zip_bytes) <= MAX_ARCHIVE:
        raise ValueError("INVALID_ARTIFACT_ZIP_SIZE")
    entries = set()
    total = 0
    try:
        with ZipFile(BytesIO(zip_bytes)) as archive:
            if len(archive.infolist()) != len(EXPECTED):
                raise ValueError("UNEXPECTED_ARTIFACT_MEMBER_COUNT")
            for member in archive.infolist():
                name = member.filename
                if (name not in EXPECTED
                        and name not in {
                            "v434_live_output/" + f for f in EXPECTED
                        }):
                    raise ValueError("UNEXPECTED_ZIP_MEMBER")
                pure = PurePosixPath(name)
                if (pure.is_absolute() or ".." in pure.parts
                        or name.endswith("/")
                        or member.is_dir()
                        or member.flag_bits & 0x1):
                    raise ValueError("UNSAFE_ZIP_MEMBER")
                # Unix Zip permission high bits; block symlink and devices.
                member_type = (member.external_attr >> 16) & 0o170000
                if member_type not in (0, 0o100000):
                    raise ValueError("UNSAFE_ZIP_MEMBER_TYPE")
                basename = pure.name
                if basename in entries:
                    raise ValueError("DUPLICATE_ZIP_MEMBER")
                entries.add(basename)
                if (not 0 < member.file_size <= MAX_SINGLE_FILE
                        or member.compress_size > MAX_ARCHIVE):
                    raise ValueError("ZIP_MEMBER_TOO_LARGE")
                total += member.file_size
                if total > MAX_TOTAL:
                    raise ValueError("ZIP_UNCOMPRESSED_TOTAL_EXCEEDED")
            if entries != EXPECTED:
                raise ValueError("MISSING_SIGNED_ARTIFACT_FILE")
            for member in archive.infolist():
                with archive.open(member) as src:
                    content = src.read(MAX_SINGLE_FILE + 1)
                if len(content) != member.file_size:
                    raise ValueError("ZIP_FILE_SIZE_MISMATCH")
                runtime._new_file(destination / PurePosixPath(member.filename).name,
                                  content)
    except (BadZipFile, OSError, EOFError):
        raise ValueError("INVALID_ARTIFACT_ZIP") from None


def _stage_bundle(state_dir: Path, *, run_id: int, attempt: int,
                  zip_bytes: bytes) -> Path:
    root = runtime._root(state_dir, create=False)
    inbox = runtime._dir(root, "inbox", create=False)
    final = inbox / f"github-{run_id}-a{attempt}"
    if final.exists() or final.is_symlink():
        raise ValueError("BUNDLE_ALREADY_STAGED_REQUIRE_MANUAL_REVIEW")
    with tempfile.TemporaryDirectory(prefix=".incoming-", dir=inbox) as td:
        stage = Path(td)
        if os.name == "posix":
            stage.chmod(0o700)
        _unpack_exact(zip_bytes, stage)
        # Direct child of private inbox; never traverse or overwrite.
        stage.rename(final)
    return final


def poll_once(state_dir: Path, client: GitHubSource,
              *, dry_run: bool = False,
              now: datetime | None = None) -> dict:
    """At most ONE previously unimported signed capture per timer invocation.

    Preflight backup gate runs before ANY API work or download. After an
    import, new signed DB contents block further imports until fresh backup.
    """
    gate = require_recent_offsite_backup(state_dir, now=now)
    root = runtime._root(state_dir, create=False)
    _, hmac_secret, _ = runtime._keyring(root)
    history = HistoryStore(root / "db" / "history.sqlite3", hmac_secret)
    document = client.list_runs()
    if (type(document) is not dict or type(document.get("workflow_runs")) is not list
            or type(document.get("total_count")) is not int
            or not 0 <= document["total_count"] <= 100
            or len(document["workflow_runs"]) != document["total_count"]):
        raise ValueError("INCOMPLETE_GITHUB_RUN_CATALOG")
    eligible = []
    for run in document["workflow_runs"]:
        valid = _valid_run(run)
        if valid:
            eligible.append(valid)
    eligible.sort()
    for run_id, attempt, source_sha in eligible:
        job_id = f"v434-gh-{run_id}-a{attempt}"
        job = history.get_job(job_id)
        if job is not None and job["status"] == "COMPLETED":
            continue
        artifact_id = _pick_artifact(client.list_artifacts(
            run_id, ARTIFACT_PREFIX + str(run_id)), run_id=run_id)
        if artifact_id is None:
            continue
        if dry_run:
            return {"state": "APPROVED_ARTIFACT_AVAILABLE",
                    "run_id": run_id, "run_attempt": attempt,
                    "database_written": False,
                    "backup_gate": gate["state"]}
        bundle = _stage_bundle(root, run_id=run_id, attempt=attempt,
                               zip_bytes=client.download_zip(artifact_id))
        try:
            validated = runtime.import_capture(
                root, bundle, expected_commit_sha=source_sha,
                run_id=run_id, run_attempt=attempt, dry_run=True)
            if validated["state"] != "SIGNED_DRY_RUN_PASS":
                raise ValueError("SIGNED_DRY_RUN_FAILED")
            # Backup might have expired during the download/verification.
            require_recent_offsite_backup(root, now=now)
            result = runtime.import_capture(
                root, bundle, expected_commit_sha=source_sha,
                run_id=run_id, run_attempt=attempt)
            return {"state": "SIGNED_ARTIFACT_IMPORTED",
                    "run_id": run_id, "run_attempt": attempt,
                    "imported": result["imported"],
                    "already_present": result["already_present"],
                    "events_generated": result["events_generated"],
                    "backup_gate": "PASS_BEFORE_IMPORT",
                    "transaction_state_verified": False}
        finally:
            # Delete private staging even on rejection. DB is idempotent.
            import shutil
            shutil.rmtree(bundle, ignore_errors=True)
    return {"state": "NO_ELIGIBLE_NEW_SIGNED_ARTIFACT",
            "backup_gate": gate["state"], "database_written": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backup-gated GitHub Actions pull importer")
    parser.add_argument("action", choices=("poll",))
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        root = runtime._root(args.state_dir, create=False)
        # Preflight *before* reading the token or touching GitHub.
        require_recent_offsite_backup(root)
        token_file = args.token_file or (root / TOKEN_RELATIVE)
        client = GitHubREST(token_file)
        result = poll_once(root, client, dry_run=args.dry_run)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, sqlite3.Error, TypeError):
        print("OCI_ACTIONS_INTAKE_REJECTED", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
