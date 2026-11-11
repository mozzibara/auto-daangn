#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Start ordinary Google Chrome with an isolated disposable local-debug profile.

All region selection is performed by the HUMAN in Chrome. Playwright attaches
over loopback CDP solely to observe existing events and safe first-party
responses. Does not launch Playwright Chromium, navigate, type or click.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

from daangn_v4_1_core import BY_KEY
from app_v5.manual_chrome_region import (
    SEARCH_URL, observe_manual_page, sanitize_manual_report,
)

_CHROME_NAMES = ("google-chrome", "google-chrome-stable")


def find_chrome(override: str | None = None) -> Path | None:
    if override:
        target = Path(override).expanduser()
        return target.resolve() if target.is_file() else None
    names = [shutil.which(name) for name in _CHROME_NAMES]
    candidates = [Path(name) for name in names if name]
    if sys.platform == "win32":
        for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            value = os.environ.get(var)
            if value:
                candidates.append(Path(value) / "Google" / "Chrome" /
                                  "Application" / "chrome.exe")
    elif sys.platform == "darwin":
        candidates.extend((
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def chrome_args(binary: Path, profile: Path) -> list[str]:
    if profile.exists() and any(profile.iterdir()):
        raise ValueError("Refusing to reuse a populated Chrome profile")
    return [
        str(binary), "--remote-debugging-address=127.0.0.1",
        "--remote-debugging-port=0",
        f"--user-data-dir={profile}",
        "--no-first-run", "--no-default-browser-check",
        "--disable-sync", "--new-window", SEARCH_URL,
    ]


def read_debug_port(profile: Path) -> int | None:
    marker = profile / "DevToolsActivePort"
    try:
        lines = marker.read_text(encoding="ascii").splitlines()
        value = int(lines[0])
        return value if 1 <= value <= 65535 else None
    except (OSError, UnicodeError, ValueError, IndexError):
        return None


async def await_debug_port(profile: Path, proc, *, deadline=12.0) -> int:
    started = asyncio.get_running_loop().time()
    while asyncio.get_running_loop().time() - started < deadline:
        port = read_debug_port(profile)
        if port is not None:
            return port
        if proc.poll() is not None:
            break
        await asyncio.sleep(.12)
    raise RuntimeError("CHROME_LAUNCH_FAILED")


async def find_search_tab(browser, *, deadline=15):
    until = asyncio.get_running_loop().time() + deadline
    while asyncio.get_running_loop().time() < until:
        for context in browser.contexts:
            for page in context.pages:
                try:
                    # Same exact public site/path/keyword, never another tab.
                    from app_v5.manual_chrome_region import is_public_search
                    if is_public_search(page.url):
                        return page
                except Exception:
                    continue
        await asyncio.sleep(.2)
    raise RuntimeError("PUBLIC_SEARCH_TAB_MISSING")


def save_report(path: Path, report: dict):
    """Atomic no-overwrite, local owner-only report; no HAR or raw headers."""
    safe = sanitize_manual_report(report)
    # O_EXCL avoids overwriting/symlink destinations with private data.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(safe, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


async def run(chrome: Path, *, timeout_sec: int,
              output: Path | None = None) -> dict:
    # No default profile, extensions, user sign-in, saved cookies or history.
    with TemporaryDirectory(prefix="daangn-manual-chrome-") as directory:
        profile = Path(directory) / "isolated"
        profile.mkdir()
        args = chrome_args(chrome, profile)
        proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, close_fds=True,
        )
        try:
            port = await await_debug_port(profile, proc)
            from playwright.async_api import async_playwright
            async with async_playwright() as pw:
                browser = await pw.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{port}", timeout=12000)
                try:
                    page = await find_search_tab(browser)
                    print("관찰 준비 완료: Chrome에서 지역 선택을 수동으로 실행하세요.")
                    print("1. 지역 선택을 열고 목표 지역을 검색하세요.")
                    print("2. 검색된 목표 지역을 마우스로 한 번 선택하세요.")
                    print("3. 이후 별도 조작 없이 화면의 결과를 관찰합니다.")
                    print("로그인하거나 다른 개인 정보를 입력하지 마세요.")
                    result = await observe_manual_page(
                        page, BY_KEY["cheonan"], timeout_sec=timeout_sec)
                finally:
                    try:
                        await browser.close()
                    except Exception:
                        pass
        finally:
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        safe = sanitize_manual_report(result)
        if output is not None:
            save_report(output, safe)
        return safe


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Manual Chrome locality comparison; no site automation or raw data")
    parser.add_argument("--chrome-path", default=None,
                        help="Google Chrome executable if auto-detection fails")
    parser.add_argument("--timeout-sec", type=int, default=120,
                        help="Time allowed for manual click (30..300 seconds)")
    parser.add_argument("--output", type=Path, default=None,
                        help="Optional new local JSON path (never overwritten)")
    args = parser.parse_args(argv)
    if not 30 <= args.timeout_sec <= 300:
        parser.error("--timeout-sec must be 30..300")
    chrome = find_chrome(args.chrome_path)
    if chrome is None:
        print("CHROME_NOT_FOUND: Chrome 경로를 --chrome-path로 지정하세요.")
        return 2
    try:
        report = asyncio.run(run(
            chrome, timeout_sec=args.timeout_sec, output=args.output))
    except KeyboardInterrupt:
        print("USER_CANCELLED")
        return 130
    except FileExistsError:
        print("OUTPUT_ALREADY_EXISTS: 기존 결과 파일을 덮어쓰지 않았습니다.")
        return 2
    except Exception as ex:
        safe_kind = ("CHROME_LAUNCH_FAILED" if
                     isinstance(ex, RuntimeError) and
                     str(ex) == "CHROME_LAUNCH_FAILED" else
                     "PUBLIC_SEARCH_TAB_MISSING" if
                     isinstance(ex, RuntimeError) and
                     str(ex) == "PUBLIC_SEARCH_TAB_MISSING" else
                     "OBSERVATION_FAILED")
        print(safe_kind)
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if report["status"] != "MANUAL_CLICK_OBSERVED":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
