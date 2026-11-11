# -*- coding: utf-8 -*-
"""Constrained live-run entrypoint for explicitly approved GitHub Actions only.

The runner never performs a login, access-limit bypass or mutation.
It writes a robots decision and exit status even when the site rejects access.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import urllib.robotparser
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import daangn_v4_1_core as core  # noqa: E402

REGIONS = ('cheonan', 'asan', 'sadang')
AGENT = 'DaangnRegionDiagnostic/4.1'


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def config_from_env(env: dict) -> dict:
    """Strictly validate environment; nothing is interpolated into a shell script."""
    region = env.get('TARGET_REGION', 'cheonan')
    control = env.get('CONTROL_REGION', 'asan')
    if region not in REGIONS or control not in REGIONS or region == control:
        raise ValueError('target and control must be different known region presets')
    keyword = env.get('SEARCH_KEYWORD', 'HDD').strip()
    if not 1 <= len(keyword) <= 60 or any(ord(c) < 32 for c in keyword):
        raise ValueError('keyword must be 1..60 characters without controls')
    if not re.fullmatch(r'[0-9]{1,9}', env.get('CATEGORY_ID', '1')):
        raise ValueError('category ID must be a positive integer')
    if not re.fullmatch(r'[0-9]{1,9}', env.get('PRICE_MAX', '50000')):
        raise ValueError('price maximum must be an integer')
    if not re.fullmatch(r'[0-9]{1,9}', env.get('PRICE_MIN', '0')):
        raise ValueError('price minimum must be an integer')
    category = int(env.get('CATEGORY_ID', '1'))
    maximum = int(env.get('PRICE_MAX', '50000'))
    minimum = int(env.get('PRICE_MIN', '0'))
    observed = json.loads((ROOT / 'category_catalog_observed.json').read_text(encoding='utf-8'))
    if category not in {int(x['id']) for x in observed['items']}:
        raise ValueError('category ID not in observed public UI catalog')
    if not (0 <= minimum <= maximum <= 999_999_999 and maximum > 0):
        raise ValueError('invalid price range')
    av = str(env.get('AVAILABLE_ONLY', 'true')).lower()
    if av not in ('true', 'false'):
        raise ValueError('available only must be true/false')
    return dict(region=region, control_region=control, keyword=keyword,
                category_id=category, max_price=maximum, min_price=minimum,
                available_only=av == 'true')


def check_robots(config, *, getter=None):
    """Fail closed on robots failure; verify EXACT target and control paths."""
    getter = getter or urllib.request.urlopen
    urls = [core.search_url(config['keyword'], core.BY_KEY[r])
            for r in (config['region'], config['control_region'])]
    result = {'time_utc': now(), 'http_status': None, 'allowed': False,
              'checked_paths': [urlsplit(u).path for u in urls], 'reason': 'NOT_CHECKED'}
    try:
        request = urllib.request.Request('https://www.daangn.com/robots.txt',
                                         headers={'User-Agent': AGENT})
        with getter(request, timeout=20) as response:
            result['http_status'] = response.status
            if response.status != 200:
                result['reason'] = 'ROBOTS_NON_200'
                return result
            body = response.read(400_001)
        if len(body) > 400_000:
            result['reason'] = 'ROBOTS_TOO_LARGE'
            return result
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(body.decode('utf-8', 'replace').splitlines())
        result['allowed'] = all(rp.can_fetch('DaangnRegionDiagnostic', url) for url in urls)
        result['reason'] = 'ALLOWED' if result['allowed'] else 'DISALLOWED'
    except Exception as exc:
        result['reason'] = 'ROBOTS_UNAVAILABLE_' + type(exc).__name__
    return result


def check_region_picker_robots(region_term: str, *, getter=None) -> dict:
    """Read robots first for the known public region-picker suggestion endpoint.

    Region selection is permitted only for the fixed observed presets, never
    arbitrary terms or a different user-controlled endpoint.
    """
    from urllib.parse import quote
    known = {core.BY_KEY[k]["term"] for k in ("cheonan", "asan")}
    if region_term not in known:
        return {"allowed": False, "reason": "INVALID_REGION"}
    getter = getter or urllib.request.urlopen
    target = (core.BASE + core.REGION_API + "?keyword=" +
              quote(region_term, safe=""))
    try:
        req = urllib.request.Request(
            core.BASE + "/robots.txt", headers={"User-Agent": AGENT})
        with getter(req, timeout=20) as response:
            if response.status != 200:
                return {"allowed": False, "reason": "ROBOTS_NON_200"}
            body = response.read(400_001)
        if len(body) > 400_000:
            return {"allowed": False, "reason": "ROBOTS_TOO_LARGE"}
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(body.decode("utf-8", "replace").splitlines())
        allowed = bool(rp.can_fetch("DaangnRegionDiagnostic", target))
        return {"allowed": allowed, "reason": "ALLOWED" if allowed else "DISALLOWED"}
    except Exception:
        return {"allowed": False, "reason": "ROBOTS_UNAVAILABLE"}


def save_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def run_live(config, output_dir, *, robot_checker=check_robots, runner=None):
    output_dir.mkdir(parents=True, exist_ok=True)
    status = {'version': '4.6', 'started_utc': now(), 'attempted_live': False,
              'run_level_blocked': True, 'exit_code': 2, 'status': 'STOP_PREFLIGHT'}
    try:
        robots = robot_checker(config)
        save_json(output_dir / 'robots_decision.json', robots)
        if not robots.get('allowed'):
            status['status'] = 'STOP_ROBOTS_' + str(robots.get('reason', 'UNKNOWN'))
            return 2
        cmd = [sys.executable, str(ROOT / 'daangn_browser_v4_6.py'),
               '--region', config['region'], '--control-region', config['control_region'],
               '--keyword', config['keyword'], '--category-id', str(config['category_id']),
               '--max-price', str(config['max_price']), '--min-price', str(config['min_price']),
               '--output-dir', str(output_dir), '--timeout', '25', '--pause-ms', '2000',
               '--settle-ms', '1600']
        cmd.append('--available-only' if config['available_only'] else '--include-sold')
        status['attempted_live'] = True
        status['status'] = 'LIVE_COMMAND_EXECUTED'
        runner = runner or subprocess.run
        proc = runner(cmd, cwd=str(ROOT), check=False, timeout=660)
        code = getattr(proc, 'returncode', 1)
        status['exit_code'] = int(code) if isinstance(code, int) else 1
        resultfile = output_dir / 'daangn_browser_v4_6_results.json'
        if resultfile.exists():
            try:
                data = json.loads(resultfile.read_text(encoding='utf-8'))
                status['status'] = data.get('run_level', {}).get('status', 'LIVE_RESULT_UNKNOWN')
                status['run_level_blocked'] = data.get('run_level', {}).get('blocked', True)
            except Exception:
                status['status'] = 'UNREADABLE_RESULT'
        else:
            status['status'] = 'NO_RESULT_FILE'
        return status['exit_code']
    except subprocess.TimeoutExpired:
        status['status'] = 'STOP_TIME_LIMIT'
        status['exit_code'] = 2
        return 2
    except Exception as exc:
        status['status'] = 'STOP_' + type(exc).__name__
        status['exit_code'] = 2
        return 2
    finally:
        status['completed_utc'] = now()
        save_json(output_dir / 'run_status.json', status)


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--output-dir', default='live_output')
    args = p.parse_args()
    output = Path(args.output_dir).resolve()
    try:
        cfg = config_from_env(os.environ)
    except Exception as exc:
        output.mkdir(parents=True, exist_ok=True)
        save_json(output / 'run_status.json', {'status': 'STOP_INVALID_INPUT',
                  'error_type': type(exc).__name__, 'run_level_blocked': True,
                  'attempted_live': False, 'exit_code': 2})
        return 2
    output.mkdir(parents=True, exist_ok=True)
    save_json(output / 'requested_config.json', cfg)
    return run_live(cfg, output)

if __name__ == '__main__':
    raise SystemExit(main())
