"""Percentage-only contribution projection, reconciled to the displayed return."""
import math
import requests
from advanced_analytics import attribution


def drivers(performance, account, currency, include_etfs, read_csv):
    unavailable = {'drivers': [], 'drivers_note': 'Verified contribution data is unavailable for this selection.'}
    if len(performance) < 2:
        return unavailable
    mode = account + ('' if include_etfs else '_excluded')
    try:
        points = [{'date': p['date'], 'portfolio': float(p['value'])} for p in performance]
        rows = attribution(read_csv(f'portfolio/performance/attribution_{mode}.csv'), points, currency)
        if not rows or any(not math.isfinite(row['contribution_pp']) for row in rows):
            return unavailable
        total = sum(row['contribution_pp'] for row in rows)
        expected = points[-1]['portfolio'] - points[0]['portfolio']
        if not math.isfinite(expected) or abs(total - expected) > 0.05:
            return {'drivers': [], 'drivers_note': 'Contribution inputs do not reconcile with this return series. Awaiting a matching calculation update.'}
        return {'drivers': [{'ticker': row['ticker'], 'contribution_pp': row['contribution_pp']} for row in rows],
                'drivers_note': f"{points[0]['date']} to {points[-1]['date']}. Historical holdings, including positions sold during the period. Provisional securities-only contribution; rounded values may differ slightly from portfolio return.",
                'drivers_total_pp': round(total, 3)}
    except (OSError, ValueError, TypeError, KeyError, requests.RequestException):
        return unavailable
