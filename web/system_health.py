"""Authenticated summary of scheduled work and verified data freshness."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

import requests

CHECKS = (
    ('Portfolio history update', 'daily_portfolio_performance.yml', True, 32),
    ('Discord heartbeat delivery', 'heartbeat.yml', False, 32),
    ('Stock quote refresh', 'stock_checker.yml', False, 20),
    ('Economic data fetch', 'economic_alert.yml', False, 6),
    ('Earnings report', 'earnings_report.yml', False, 48),
)


def summarize(runs, now, hours):
    latest = runs[0] if runs else {}
    completed = next((run for run in runs if run.get('status') == 'completed'), {})
    success = next((run for run in runs if run.get('conclusion') == 'success'), {})
    timestamp = success.get('updated_at')
    if timestamp:
        age = now - datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        stale = age.total_seconds() > hours * 3600
    else:
        stale = True
    return {'latest_status': latest.get('status'), 'latest_outcome': completed.get('conclusion'),
            'latest_at': latest.get('created_at'), 'last_success_at': timestamp,
            'stale': stale, 'failed': completed.get('conclusion') not in ('success', None)}


def dashboard(get_runs, get_file, now=None):
    now = now or datetime.now(timezone.utc)
    weekend = now.weekday() in (0, 5, 6)

    def check(item):
        name, workflow, private_repo, hours = item
        try:
            return {'name': name, **summarize(get_runs(workflow, private_repo), now,
                                              hours + (60 if weekend else 0))}
        except (requests.RequestException, ValueError, KeyError, TypeError, RuntimeError):
            return {'name': name, 'unavailable': True}

    def history(name, filename, key):
        try:
            data, _ = get_file('portfolio/performance/' + filename, data=True)
            through = date.fromisoformat(data[key])
            days = 4 if weekend else 2
            return {'name': name, 'through': through.isoformat(),
                    'stale': (now.date() - through).days >= days}
        except (requests.RequestException, ValueError, KeyError, TypeError, RuntimeError):
            return {'name': name, 'unavailable': True}

    with ThreadPoolExecutor(max_workers=len(CHECKS)) as pool:
        workflows = list(pool.map(check, CHECKS))
    return {'as_of': now.isoformat(), 'workflows': workflows, 'data': [
        history('Merrill performance', 'merrill_2026_ytd_summary.json', 'through'),
        history('Nordnet performance', 'nordnet_performance_summary.json', 'history_through'),
        history('Combined performance', 'combined_2026_ytd_summary.json', 'end')]}
