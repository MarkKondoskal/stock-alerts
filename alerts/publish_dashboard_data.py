"""Publish private history or prepared data using revision-checked GitHub writes."""
import base64
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alerts.publish_watchlist import request_with_retry


def merge_history(remote, local):
    events = {event['id']: event for event in remote}
    for event in local:
        if event['updated_at'] >= events.get(event['id'], {}).get('updated_at', ''):
            events[event['id']] = event
    return sorted(events.values(), key=lambda e: (e['created_at'], e['id']))[-1000:]


def publish(path, local, history=False):
    repo = os.environ['STOCKALERTS_DATA_REPOSITORY']
    branch = os.environ.get('STOCKALERTS_DATA_BRANCH') or 'main'
    url = f'https://api.github.com/repos/{repo}/contents/{path}'
    headers = {'Authorization': 'Bearer '+os.environ['STOCKALERTS_DATA_TOKEN'],
               'Accept': 'application/vnd.github+json'}
    for attempt in range(5):
        response = request_with_retry('get', url, params={'ref': branch}, headers=headers, timeout=20)
        sha = None
        remote = [] if history else {}
        if response.status_code != 404:
            response.raise_for_status()
            data = response.json()
            sha = data['sha']
            remote = json.loads(base64.b64decode(data['content']))
        if not history and remote.get('generated_at', '') > local.get('generated_at', ''):
            return
        merged = merge_history(remote, local) if history else local
        if merged == remote:
            return
        payload = {'message': 'Refresh private '+('alert history' if history else 'dashboard snapshot'),
                   'branch': branch,
                   'content': base64.b64encode((json.dumps(merged, separators=(',', ':'), allow_nan=False)+'\n').encode()).decode()}
        if sha:
            payload['sha'] = sha
        result = request_with_retry('put', url, headers=headers, json=payload, timeout=25)
        if result.status_code == 409 or (result.status_code == 422 and sha is None):
            continue
        result.raise_for_status()
        return
    raise RuntimeError('Could not confirm private dashboard data was saved')


if __name__ == '__main__':
    path = Path(os.environ['STOCKALERTS_ALERT_HISTORY_FILE'])
    if path.exists():
        publish('alerts/alert_history.json', json.loads(path.read_text(encoding='utf-8')), history=True)
