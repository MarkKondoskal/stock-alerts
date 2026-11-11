"""Apply this checkout's target changes to the latest private GitHub revision.

Targets are sets: concurrent additions survive removals of other targets.
An identical removed-and-readded target cannot be distinguished without IDs.
"""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from watchlist_rules import validate_watchlist


def rules(entry):
    result = {('PRICE', 'buy', value) for value in entry['price_targets']}
    for metric, directions in entry['valuation_targets'].items():
        for direction, values in directions.items():
            result.update((metric, direction, value) for value in values)
    return result


def merge_changes(base, local, remote):
    base, local, remote = map(validate_watchlist, (base, local, remote))
    empty = {'price_targets': [], 'valuation_targets': {}}
    result = dict(remote)
    for ticker in base.keys() | local.keys():
        before = rules(base.get(ticker, empty))
        after = rules(local.get(ticker, empty))
        if before == after and (ticker in base) == (ticker in local):
            continue
        merged = (rules(remote.get(ticker, empty)) - (before - after)) | (after - before)
        if not merged and ticker not in local:
            result.pop(ticker, None)
            continue
        entry = {'price_targets': [], 'valuation_targets': {}}
        for metric, direction, value in sorted(merged):
            if metric == 'PRICE':
                entry['price_targets'].append(value)
            else:
                entry['valuation_targets'].setdefault(metric, {'trim': [], 'buy': []})[direction].append(value)
        result[ticker] = entry
    return result


def request_with_retry(method, url, **kwargs):
    for attempt in range(3):
        try:
            response = getattr(requests, method)(url, **kwargs)
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 2:
                raise
        else:
            if response.status_code not in (429, 500, 502, 503, 504) or attempt == 2:
                return response
        time.sleep(2 ** attempt)


def publish(base, local, repo, branch, token):
    url = f'https://api.github.com/repos/{repo}/contents/alerts/watchlist.json'
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json'}
    for attempt in range(5):
        response = request_with_retry("get", url, params={'ref': branch}, headers=headers, timeout=20)
        response.raise_for_status()
        current = response.json()
        remote = json.loads(base64.b64decode(current['content']))
        merged = merge_changes(base, local, remote)
        if merged == validate_watchlist(remote):
            return
        content = base64.b64encode((json.dumps(merged, indent=2, allow_nan=False)+'\n').encode()).decode()
        response = request_with_retry("put", url, headers=headers, timeout=20,
                                json={'message': 'Update private watchlist targets', 'branch': branch,
                                      'sha': current['sha'], 'content': content})
        if response.status_code == 409:
            continue
        response.raise_for_status()
        return
    raise RuntimeError('Watchlist changed repeatedly; target updates were not confirmed')


def main():
    checkout = Path(os.environ['STOCKALERTS_PRIVATE_CHECKOUT'])
    base = json.loads(subprocess.check_output(['git', '-C', str(checkout), 'show',
                                              'HEAD:alerts/watchlist.json']))
    local = json.loads((checkout/'alerts/watchlist.json').read_text(encoding='utf-8'))
    publish(base, local, os.environ['STOCKALERTS_DATA_REPOSITORY'],
            os.environ.get('STOCKALERTS_DATA_BRANCH', 'main'), os.environ['STOCKALERTS_DATA_TOKEN'])


if __name__ == '__main__':
    main()
