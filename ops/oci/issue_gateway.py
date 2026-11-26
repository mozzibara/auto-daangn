"""Owner-only read-only diagnostics over a private GitHub Issue, without Actions.

The dedicated local service account and token must be provisioned separately.
No listener, sudo, production DB access, live collection or arbitrary commands.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import urllib.parse
import urllib.request

from ops.oci import local_gateway

CONFIG = Path('/etc/auto-daangn-control/config.json')
STATE = Path('/var/lib/auto-daangn-control')
ACCOUNT = 'daangn-control'
COMMANDS = {'/local health': 'health', '/local doctor': 'doctor'}
REPO = re.compile(r'[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}\Z')
LIMIT = 1024 * 1024


def _utc(value):
    if type(value) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', value):
        raise ValueError('INVALID_TIMESTAMP')
    return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)


def _stamp(value):
    return value.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _positive(value):
    return type(value) is int and 0 < value < 10**20


def config(value):
    if (type(value) is not dict or set(value) != {'repository', 'issue', 'owner_id'} or
            type(value['repository']) is not str or not REPO.fullmatch(value['repository']) or
            any(p in ('.', '..') for p in value['repository'].split('/')) or
            not _positive(value['issue']) or not _positive(value['owner_id'])):
        raise ValueError('INVALID_CONTROL_CONFIG')
    return dict(value)


def initial(now):
    floor = _stamp(now)
    return {'schema': 'oci_issue_gateway_v1', 'floor': floor,
            'cursor_id': 0, 'cursor_time': floor, 'pending': None}


def validate_state(value):
    if (type(value) is not dict or set(value) != {'schema', 'floor', 'cursor_id', 'cursor_time', 'pending'} or
            value['schema'] != 'oci_issue_gateway_v1' or type(value['cursor_id']) is not int or
            not 0 <= value['cursor_id'] < 10**20 or _utc(value['cursor_time']) < _utc(value['floor'])):
        raise ValueError('INVALID_CONTROL_STATE')
    p = value['pending']
    if p is not None:
        if (type(p) is not dict or set(p) != {'id', 'created', 'body'} or
                not _positive(p['id']) or p['id'] <= value['cursor_id'] or
                _utc(p['created']) <= _utc(value['floor']) or type(p['body']) is not str or
                len(p['body'].encode('utf-8')) > 8192 or not p['body'].startswith(_marker(p['id']))):
            raise ValueError('INVALID_PENDING_RESPONSE')
    return value


def _marker(comment_id):
    return f'[auto-daangn-local-response:{comment_id}]\n'


def _owner(comment, owner_id):
    user = comment.get('user')
    return (type(user) is dict and type(user.get('id')) is int and user['id'] == owner_id
            and comment.get('author_association') == 'OWNER')


def _advance(state, comment_id, created):
    return {**state, 'cursor_id': comment_id,
            'cursor_time': max(state['cursor_time'], created), 'pending': None}


def tick(client, store, cfg, execute=local_gateway.execute):
    cfg = config(cfg)
    state = validate_state(store.load())
    if not client.private_repository():
        raise ValueError('PRIVATE_REPOSITORY_REQUIRED')
    since = _stamp(_utc(state['cursor_time']) - timedelta(seconds=1))
    comments = client.comments(since)
    if type(comments) is not list or len(comments) > 100:
        raise ValueError('COMMENT_BATCH_LIMIT')
    rows = []
    seen = set()
    for row in comments:
        if type(row) is not dict or not _positive(row.get('id')) or row['id'] in seen:
            raise ValueError('INVALID_COMMENT_BATCH')
        _utc(row.get('created_at'))
        seen.add(row['id'])
        rows.append(row)
    rows.sort(key=lambda row: row['id'])
    pending = state['pending']
    if pending is not None:
        # Retry an ambiguous POST only if no exact owner-authored reply exists.
        exists = any(_owner(row, cfg['owner_id']) and row.get('body') == pending['body'] for row in rows)
        if not exists:
            client.post(pending['body'])
        store.save(_advance(state, pending['id'], pending['created']))
        return {'status': 'RESPONSE_DELIVERED', 'command_executed': False}
    for row in rows:
        cid, created = row['id'], row['created_at']
        if cid <= state['cursor_id'] or created <= state['floor']:
            continue
        body = row.get('body')
        if not _owner(row, cfg['owner_id']) or type(body) is not str or body not in COMMANDS:
            state = _advance(state, cid, created)
            continue
        if row.get('updated_at') != created:
            state = _advance(state, cid, created)
            continue
        result = execute(COMMANDS[body])
        if type(result) is not dict or result.get('schema') != 'oci_local_gateway_v1':
            raise ValueError('INVALID_LOCAL_RESULT')
        reply = _marker(cid) + '```json\n' + json.dumps(result, sort_keys=True) + '\n```'
        if len(reply.encode('utf-8')) > 8192:
            raise ValueError('RESULT_TOO_LARGE')
        # Persist the response before attempting delivery. No re-execution on retry.
        pending = {'id': cid, 'created': created, 'body': reply}
        state = {**state, 'pending': pending}
        store.save(state)
        client.post(reply)
        store.save(_advance(state, cid, created))
        return {'status': 'RESPONSE_DELIVERED', 'command_executed': True}
    store.save(state)
    return {'status': 'NO_COMMAND', 'command_executed': False}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('REDIRECT_DENIED')


class GitHubIssueClient:
    def __init__(self, cfg, token):
        cfg = config(cfg)
        if type(token) is not str or not 20 <= len(token) <= 500 or not token.isascii() or any(c.isspace() for c in token):
            raise ValueError('INVALID_TOKEN')
        self.repo = 'https://api.github.com/repos/' + cfg['repository']
        self.name = cfg['repository']
        self.endpoint = self.repo + '/issues/' + str(cfg['issue']) + '/comments'
        self.token = token
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def _request(self, url, body=None):
        payload = None if body is None else json.dumps({'body': body}).encode('utf-8')
        req = urllib.request.Request(url, data=payload, method='GET' if body is None else 'POST',
            headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json',
                     'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'auto-daangn-local-control',
                     'Content-Type': 'application/json'})
        with self.opener.open(req, timeout=12) as response:
            if response.status != (200 if body is None else 201):
                raise ValueError('HTTP_STATUS_REJECTED')
            if body is not None:
                return None
            if 'rel="next"' in response.headers.get('Link', ''):
                raise ValueError('PAGINATED_BACKLOG')
            raw = response.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise ValueError('HTTP_BODY_LIMIT')
            return json.loads(raw.decode('utf-8'))

    def private_repository(self):
        data = self._request(self.repo)
        return type(data) is dict and data.get('private') is True and data.get('full_name') == self.name

    def comments(self, since):
        _utc(since)
        return self._request(self.endpoint + '?' + urllib.parse.urlencode({'per_page': 100, 'since': since}))

    def post(self, body):
        if type(body) is not str or len(body.encode('utf-8')) > 8192:
            raise ValueError('INVALID_RESPONSE')
        self._request(self.endpoint, body)


def _private_file(path, uid, limit, *, exact_mode=True):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_nlink != 1 or
            (stat.S_IMODE(info.st_mode) != 0o600 if exact_mode else info.st_mode & 0o022) or
            info.st_size > limit):
        raise ValueError('UNTRUSTED_CONTROL_FILE')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) != info.st_size or len(raw) > limit:
        raise ValueError('CONTROL_FILE_CHANGED')
    return raw


class StateStore:
    def __init__(self, root, uid):
        self.root, self.uid = Path(root), uid
        info = self.root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError('PRIVATE_CONTROL_DIRECTORY_REQUIRED')
        self.path = self.root / 'cursor.json'

    def load(self):
        return validate_state(json.loads(_private_file(self.path, self.uid, 16384).decode('utf-8')))

    def save(self, value, *, create=False):
        validate_state(value)
        raw = (json.dumps(value, sort_keys=True) + '\n').encode('utf-8')
        if len(raw) > 16384:
            raise ValueError('STATE_LIMIT')
        if create:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            name = None
        else:
            _private_file(self.path, self.uid, 16384)
            fd, name = tempfile.mkstemp(prefix='.cursor-', dir=self.root)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            if name is not None:
                os.replace(name, self.path)
            dfd = os.open(self.root, os.O_DIRECTORY | os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        finally:
            if name is not None and os.path.exists(name):
                os.unlink(name)


def main(argv=None):
    import fcntl
    import pwd
    parser = argparse.ArgumentParser(description='Local private Issue diagnostics')
    parser.add_argument('operation', choices=('init', 'tick'))
    args = parser.parse_args(argv)
    fd = None
    try:
        uid = os.geteuid()
        if uid == 0 or uid != pwd.getpwnam(ACCOUNT).pw_uid:
            raise ValueError('DEDICATED_ACCOUNT_REQUIRED')
        for directory in (*CONFIG.parents, *STATE.parents):
            info = directory.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise ValueError('UNTRUSTED_CONTROL_ANCESTOR')
        store = StateStore(STATE, uid)
        fd = os.open(STATE / '.poll.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError('UNTRUSTED_LOCK')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.operation == 'init':
            store.save(initial(datetime.now(timezone.utc)), create=True)
            result = {'status': 'INITIALIZED', 'command_executed': False}
        else:
            cfg = config(json.loads(_private_file(CONFIG, 0, 4096, exact_mode=False).decode('utf-8')))
            token = _private_file(STATE / 'token', uid, 512).decode('ascii').strip()
            result = tick(GitHubIssueClient(cfg, token), store, cfg)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, UnicodeError):
        print('{"status":"CONTROL_TICK_REJECTED"}')
        return 2
    finally:
        if fd is not None:
            os.close(fd)


if __name__ == '__main__':
    raise SystemExit(main())
