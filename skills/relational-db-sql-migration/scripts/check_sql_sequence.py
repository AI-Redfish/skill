#!/usr/bin/env python3
"""Read-only SQL sequence inventory: local files + GitLab target + all opened MRs.

Python 3.9+, standard library; uv run or python. Configuration: process environment
then --workdir/.agents/.env (UTF-8 key=value, never sourced as shell code).
Usage: python check_sql_sequence.py --repo PATH --workdir PATH
       --target-branch origin/dev/v6.0.9.2 --database basic_platform_ops
Exit: 0 complete snapshot, 1 sequence collisions, 2 incomplete/invalid check.
No credential, repository, branch or MR writes. This is NOT an atomic reservation.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, quote
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class CheckError(Exception):
    pass


def config(workdir):
    values = {}
    path = Path(workdir) / '.agents' / '.env'
    if path.exists():
        for number, raw in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('export '):
                line = line[7:]
            key, sep, value = line.partition('=')
            if not sep or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key.strip()):
                raise CheckError(f'Invalid .env line {number}; use KEY=value')
            value = value.strip()
            if value.startswith(('"', "'")):
                if len(value) < 2 or value[-1] != value[0]:
                    raise CheckError(f'Unclosed .env quote at line {number}')
                value = value[1:-1]
            values[key.strip()] = value
    values.update(os.environ)
    return values


def git(repo, *args):
    try:
        r = subprocess.run(['git', '-C', str(repo), *args], capture_output=True,
                           encoding='utf-8', errors='replace', timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        raise CheckError('Git unavailable or timed out; verify --repo and Git installation') from None
    if r.returncode:
        raise CheckError('Git read failed; verify repository and origin configuration')
    return r.stdout.strip()


def remote_info(url):
    if '://' in url:
        parsed = urlsplit(url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise CheckError('Origin must not contain credentials, query or fragment')
        host = ('https' if parsed.scheme == 'ssh' else parsed.scheme) + '://' + parsed.netloc
        project = parsed.path.strip('/')
    else:
        match = re.fullmatch(r'(?:[^@]+@)?([^:]+):(.+)', url)
        if not match:
            raise CheckError('Cannot derive GitLab host/project from origin; configure explicitly')
        host, project = 'https://' + match[1], match[2]
    return host, project.removesuffix('.git')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Do not forward PRIVATE-TOKEN to another URL.


class API:
    def __init__(self, host, token, allow_http=False, timeout=30):
        parsed = urlsplit(host)
        if (parsed.scheme not in ('https', 'http') or not parsed.netloc or
                parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise CheckError('Invalid GITLAB_HOST; use a credential-free HTTP(S) base URL')
        if parsed.scheme == 'http' and not allow_http:
            raise CheckError('Plain HTTP exposes Token in transit; use HTTPS or explicitly configure GITLAB_ALLOW_HTTP=true')
        if not token or any(c in token for c in '\r\n'):
            raise CheckError('Missing/invalid GITLAB_TOKEN; configure read_api access in ignored .agents/.env')
        self.base = host.rstrip('/') + '/api/v4'
        self.token, self.timeout = token, timeout
        # No proxy by default: internal credentials only go to the configured origin.
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def get(self, path, params=None):
        url = self.base + path + ('?' + urlencode(params) if params else '')
        req = Request(url, headers={'PRIVATE-TOKEN': self.token, 'Accept': 'application/json'})
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                return json.load(response), response.headers
        except HTTPError as exc:
            raise CheckError(f'GitLab HTTP {exc.code}; check access, endpoint and limits; no sequence allocated') from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise CheckError('GitLab network/JSON failure; retry after verifying connection; no sequence allocated') from None

    def pages(self, path, params=None):
        page, seen = 1, set()
        while page <= 10000:
            if page in seen:
                raise CheckError('Repeated API page; incomplete inventory')
            seen.add(page)
            items, headers = self.get(path, dict(params or {}, page=page, per_page=100))
            if not isinstance(items, list):
                raise CheckError('Expected GitLab list response; incomplete inventory')
            yield from items
            nxt = headers.get('X-Next-Page')
            if nxt:
                if not nxt.isdigit():
                    raise CheckError('Invalid pagination header')
                page = int(nxt)
            elif not items or len(items) < 100 or nxt == '':
                return
            else:
                page += 1  # Some proxies omit pagination headers.
        raise CheckError('API pagination limit exceeded; incomplete inventory')


def parse_file(path, iteration, database):
    parts = PurePosixPath(path).parts
    if len(parts) != 3 or parts[1] != database:
        return None
    pattern = (r'V(?P<timestamp>\d{4}(?:\.\d{2}){5})_' + re.escape(iteration) +
               r'\.(?P<sequence>\d+)__' + re.escape(database) + r'_(?P<op>[^/]+)\.sql')
    match = re.fullmatch(pattern, parts[2])
    if not match:
        if parts[2].startswith('V') and ('_' + iteration + '.') in parts[2] and parts[2].endswith('.sql'):
            raise CheckError('Malformed iteration SQL filename; correct naming before allocation')
        return None
    datetime.strptime(match['timestamp'], '%Y.%m.%d.%H.%M.%S')
    return dict(engine=parts[0], database=database, path=str(path),
                filename=parts[2], sequence=int(match['sequence']), timestamp=match['timestamp'])


def summarize(inventories, iteration, database):
    entries, by_seq, maxima = {}, defaultdict(set), {}
    mr_claims = defaultdict(set)  # (engine, sequence, filename) -> {mr!iid}
    for source, paths in inventories.items():
        maximum = 0
        for path in paths:
            item = parse_file(path, iteration, database)
            if not item:
                continue
            maximum = max(maximum, item['sequence'])
            key = item['path']
            if key not in entries:
                entries[key] = dict(item, sources=[])
            if source not in entries[key]['sources']:
                entries[key]['sources'].append(source)
            by_seq[(item['engine'], item['sequence'])].add(item['filename'])
            if source.startswith('mr!'):
                mr_claims[(item['engine'], item['sequence'], item['filename'])].add(source)
        maxima[source] = maximum
    conflicts = [dict(engine=k[0], sequence=k[1], filenames=sorted(v))
                 for k, v in sorted(by_seq.items()) if len(v) > 1]
    # Same filename claimed by 2+ open MRs: duplicate Flyway version once both merge.
    # Advisory only: stacked MRs may legitimately share a diff path; human decides.
    conflicts += [dict(engine=k[0], sequence=k[1], filenames=[k[2]], sources=sorted(v))
                  for k, v in sorted(mr_claims.items()) if len(v) > 1]
    return dict(iteration=iteration, database=database, maxima=maxima,
                next_sequence=max(maxima.values(), default=0) + 1,
                conflicts=conflicts, files=sorted(entries.values(), key=lambda x: x['path']),
                atomic_reservation=False)


def collect(api, project, branch, repo, database, iteration):
    root = '/projects/' + quote(project, safe='')
    project_data, _ = api.get(root)
    if 'id' not in project_data:
        raise CheckError('GitLab project response missing id')
    root = '/projects/' + str(project_data['id'])
    initial, _ = api.get(root + '/repository/branches/' + quote(branch, safe=''))
    sha = initial['commit']['id']
    target = [i['path'] for i in api.pages(root + '/repository/tree',
              {'ref': sha, 'recursive': 'true'}) if i['type'] == 'blob']
    local = []
    for engine in Path(repo).iterdir():
        folder = engine / database
        if engine.is_dir() and not engine.is_symlink() and folder.is_dir() and not folder.is_symlink():
            local.extend(f'{engine.name}/{database}/{p.name}' for p in folder.glob('*.sql')
                         if p.is_file() and not p.is_symlink())
    inventories = {'local': local, 'target': target}
    mrs = list(api.pages(root + '/merge_requests', {'state': 'opened', 'target_branch': branch}))
    snapshots = {}
    for mr in mrs:
        iid = mr['iid']
        detail, _ = api.get(root + f'/merge_requests/{iid}')
        if detail.get('state') != 'opened' or detail.get('target_branch') != branch:
            raise CheckError('MR state changed during check; rerun')
        if detail.get('changes_count') is None or str(detail['changes_count']).endswith('+'):
            raise CheckError('MR diff preparing or capped; cannot certify complete file inventory')
        diffs = list(api.pages(root + f'/merge_requests/{iid}/diffs'))
        if len(diffs) != int(detail['changes_count']):
            raise CheckError('MR diff count mismatch/truncated; retry or use complete source commit tree')
        snapshots[iid] = detail['sha']
        inventories[f'mr!{iid}'] = [d['new_path'] for d in diffs if not d.get('deleted_file')]
    # Detect changes during the read; does not claim to lock subsequent writers.
    latest, _ = api.get(root + '/repository/branches/' + quote(branch, safe=''))
    current = list(api.pages(root + '/merge_requests', {'state': 'opened', 'target_branch': branch}))
    if latest['commit']['id'] != sha or {m['iid'] for m in current} != set(snapshots):
        raise CheckError('Target/MR set changed during check; rerun')
    for iid, commit in snapshots.items():
        detail, _ = api.get(root + f'/merge_requests/{iid}')
        if detail['sha'] != commit or detail['state'] != 'opened' or detail['target_branch'] != branch:
            raise CheckError('MR changed during check; rerun')
    result = summarize(inventories, iteration, database)
    result.update(target_branch=branch, target_sha=sha, project_id=project_data['id'],
                  opened_mrs=sorted(snapshots), checked_at=datetime.now(timezone.utc).isoformat())
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', required=True, type=Path)
    p.add_argument('--workdir', required=True, type=Path, help='Agent workspace containing .agents/.env')
    p.add_argument('--target-branch', required=True)
    p.add_argument('--database', required=True, help='Sequence scope is one database across engines')
    args = p.parse_args(argv)
    try:
        branch = args.target_branch.removeprefix('origin/')
        match = re.search(r'(?:^|/)v(\d+(?:\.\d+){3})(?:$|/)', branch)
        if not match or not re.fullmatch(r'[A-Za-z0-9_]+', args.database):
            raise CheckError('Require versioned target branch and simple database name')
        git(args.repo, 'rev-parse', '--show-toplevel')
        values = config(args.workdir)
        host, project = remote_info(git(args.repo, 'remote', 'get-url', 'origin'))
        configured_host = values.get('GITLAB_HOST', host).rstrip('/')
        configured_project = values.get('GITLAB_PROJECT', project)
        if (configured_host != host.rstrip('/') or configured_project != project):
            raise CheckError('GITLAB_HOST/PROJECT differ from origin; verify repository/config before sending Token')
        api = API(configured_host, values.get('GITLAB_TOKEN'),
                  values.get('GITLAB_ALLOW_HTTP', '').lower() == 'true')
        data = collect(api, configured_project, branch, args.repo, args.database, match[1])
        print(json.dumps({'status': 'conflict' if data['conflicts'] else 'ok', 'data': data}, ensure_ascii=False, indent=2))
        return 1 if data['conflicts'] else 0
    except (CheckError, ValueError, KeyError, TypeError, UnicodeError, OSError):
        # Exception messages from external IO may contain sensitive request data.
        exc = sys.exc_info()[1]
        message = str(exc) if isinstance(exc, CheckError) else 'Invalid/incomplete input or API response; verify configuration and retry'
        print(json.dumps({'status': 'error', 'error': message, 'data': None}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
