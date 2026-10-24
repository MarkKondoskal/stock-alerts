"""Public, read-only market sentiment & US macro releases.

No brokerage data or secrets in responses. Shares sources with Discord alerts:
Yahoo ^VIX, CNN Fear & Greed and FRED. Observation dates are not release dates.
"""
from __future__ import annotations

import csv
import io
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import quote

import requests

USER_AGENT = 'Mozilla/5.0 (compatible; StockAlertsDashboard/1.0; market-data-readonly)'
HEADERS = {'User-Agent': USER_AGENT, 'Accept': 'application/json,text/csv,*/*'}
CNN_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36', 'Referer': 'https://www.cnn.com/markets/fear-and-greed', 'Accept': 'application/json'}
FRED_CSV = 'https://fred.stlouisfed.org/graph/fredgraph.csv'
FRED_API = 'https://api.stlouisfed.org/fred/series/observations'
CNN_URL = 'https://production.dataviz.cnn.io/index/fearandgreed/graphdata'
VIX_URL = 'https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX'
FRED_SERIES = ('CPIAUCSL', 'CPILFESL', 'PCEPI', 'PCEPILFE', 'PAYEMS', 'UNRATE', 'ICSA', 'A191RL1Q225SBEA', 'DFEDTARL', 'DFEDTARU', 'VIXCLS')
_CACHE = {}
_CACHE_LOCK = threading.Lock()


def _num(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _cached(key, get, ttl=1200):
    now = time.monotonic()
    with _CACHE_LOCK:
        old = _CACHE.get(key)
        if old and now < old['expires']:
            return old['value'], old.get('stale', False)
    try:
        value = get()
        if value is None:
            raise ValueError('No usable market data')
        with _CACHE_LOCK:
            _CACHE[key] = {'value': value, 'expires': time.monotonic() + ttl, 'stale': False}
        return value, False
    except (requests.RequestException, ValueError, KeyError, TypeError, IndexError, csv.Error):
        with _CACHE_LOCK:
            old = _CACHE.get(key)
            # Serve a previously fetched value only with an explicit stale marker.
            if old and old['value'] is not None:
                old['expires'] = time.monotonic() + 180
                old['stale'] = True
                return old['value'], True
            _CACHE[key] = {'value': None, 'expires': time.monotonic() + 180, 'stale': False}
        return None, False


def _fred_points(series):
    if series not in FRED_SERIES:
        raise ValueError('Unsupported FRED series')
    key = os.environ.get('FRED_API_KEY', '').strip()
    if key:
        params = {'series_id': series, 'api_key': key, 'file_type': 'json', 'observation_start': '2024-01-01', 'sort_order': 'desc', 'limit': 48}
        response = requests.get(FRED_API, params=params, headers=HEADERS, timeout=12)
        response.raise_for_status()
        rows = response.json().get('observations', [])
        values = [(row.get('date'), _num(row.get('value'))) for row in rows]
    else:
        # FRED graph downloads are public, so no Render API key is required.
        response = requests.get(FRED_CSV, params={'id': series, 'cosd': '2024-01-01'}, headers=HEADERS, timeout=12)
        response.raise_for_status()
        rows = csv.DictReader(io.StringIO(response.text))
        values = []
        for row in rows:
            values.append((row.get('observation_date') or row.get('DATE'), _num(row.get(series))))
    points = [(date, value) for date, value in values if isinstance(date, str) and len(date) == 10 and value is not None]
    points.sort(key=lambda row: row[0])
    if not points:
        raise ValueError(f'No observations for {series}')
    return points[-48:]


def _fetch_vix():
    response = requests.get(VIX_URL, params={'range': '5d', 'interval': '1d'}, headers=HEADERS, timeout=10)
    response.raise_for_status()
    result = response.json()['chart']['result'][0]
    meta = result['meta']
    price = _num(meta.get('regularMarketPrice'))
    if price is None:
        raise ValueError('VIX quote not provided')
    timestamp = meta.get('regularMarketTime')
    as_of = datetime.fromtimestamp(int(timestamp), timezone.utc).isoformat() if timestamp else None
    previous = _num(meta.get('chartPreviousClose'))
    return {'value': round(price, 2), 'previous_close': previous, 'as_of': as_of, 'source': 'Yahoo Finance', 'url': 'https://finance.yahoo.com/quote/%5EVIX/', 'frequency': 'Market quote'}


def _fetch_fear_greed():
    response = requests.get(CNN_URL, headers=CNN_HEADERS, timeout=10)
    response.raise_for_status()
    result = response.json()['fear_and_greed']
    score = _num(result.get('score'))
    if score is None or not (0 <= score <= 100):
        raise ValueError('CNN supplied invalid Fear & Greed score')
    rating = str(result.get('rating') or '').strip().title()
    if rating.lower() not in ('extreme fear', 'fear', 'neutral', 'greed', 'extreme greed'):
        rating = ('Extreme Fear' if score <= 25 else 'Fear' if score < 45 else 'Neutral' if score <= 55 else 'Greed' if score < 75 else 'Extreme Greed')
    date = result.get('timestamp')
    return {'value': round(score, 1), 'rating': rating, 'as_of': str(date) if date else None, 'source': 'CNN', 'url': 'https://www.cnn.com/markets/fear-and-greed', 'frequency': 'Market sentiment'}


def _economic_item(id, title, category, points, unit, transform='level', precision=1):
    if not points:
        return None
    period, latest = points[-1]
    if transform == 'yoy':
        # Monthly inflation: exact 12-month lookback, not the preceding 12 observations
        # (which could be wrong when a period is missing).
        year = int(period[:4]) - 1
        old_period = f'{year:04d}{period[4:]}'
        previous = next((v for d, v in points if d == old_period), None)
        if previous is None or previous <= 0:
            return None
        value = (latest / previous - 1) * 100
    elif transform == 'difference':
        if len(points) < 2:
            return None
        value = latest - points[-2][1]
    else:
        value = latest
    if not math.isfinite(value):
        return None
    previous = None
    if transform == 'level' and len(points) >= 2:
        previous = round(points[-2][1], precision)
    return {'id': id, 'title': title, 'category': category, 'value': round(value, precision), 'unit': unit,
            'period': period, 'previous': previous, 'source': 'FRED', 'source_url': f'https://fred.stlouisfed.org/series/{id}',
            'description': {'yoy': 'Year-over-year change', 'difference': 'Change since previous observation', 'level': 'Latest reported level'}[transform]}


def _economic_rows(series_map):
    specs = [
        ('CPIAUCSL', 'CPI inflation', 'Inflation', '% YoY', 'yoy', 2),
        ('CPILFESL', 'Core CPI inflation', 'Inflation', '% YoY', 'yoy', 2),
        ('PCEPI', 'PCE inflation', 'Inflation', '% YoY', 'yoy', 2),
        ('PCEPILFE', 'Core PCE inflation', 'Inflation', '% YoY', 'yoy', 2),
        ('PAYEMS', 'Nonfarm payrolls', 'Jobs', 'K jobs', 'difference', 0),
        ('UNRATE', 'Unemployment rate', 'Jobs', '%', 'level', 1),
        ('ICSA', 'Initial jobless claims', 'Jobs', 'claims', 'level', 0),
        ('A191RL1Q225SBEA', 'Real GDP growth', 'Growth', '% QoQ annualized', 'level', 1),
    ]
    result = []
    for id, name, group, unit, transform, precision in specs:
        item = _economic_item(id, name, group, series_map.get(id), unit, transform, precision)
        if item:
            if id == 'ICSA':
                item['value'] = round(item['value'] / 1000, 0)
                item['unit'] = 'K claims'
                if item['previous'] is not None:
                    item['previous'] = round(item['previous'] / 1000, 0)
            result.append(item)
    lower = series_map.get('DFEDTARL')
    upper = series_map.get('DFEDTARU')
    if lower and upper:
        # Align target-range lower/upper by observation day.
        lower_d = dict(lower)
        date, high = upper[-1]
        low = lower_d.get(date)
        if low is not None:
            result.append({'id': 'DFEDTARU', 'title': 'Fed target rate', 'category': 'Federal Reserve',
                           'value': round(high, 2), 'lower': round(low, 2), 'unit': '% range', 'period': date,
                           'previous': None, 'source': 'FRED', 'source_url': 'https://fred.stlouisfed.org/series/DFEDTARU',
                           'description': 'Federal funds target range (not the effective rate)'})
    return sorted(result, key=lambda entry: (entry['period'], entry['title']), reverse=True)


def get_sentiment_dashboard():
    """Collect public market data; partial source failures never break the other cards."""
    jobs = {'vix': (_fetch_vix, 600), 'fear_greed': (_fetch_fear_greed, 900)}
    jobs.update({f'fred:{name}': (lambda name=name: _fred_points(name), 3 * 3600) for name in FRED_SERIES})
    results = {}
    # First cold load has a fixed number of tasks and bounded network timeouts.
    with ThreadPoolExecutor(max_workers=12) as executor:
        pending = {executor.submit(_cached, key, fn, ttl): key for key, (fn, ttl) in jobs.items()}
        for future in as_completed(pending):
            key = pending[future]
            try:
                value, stale = future.result()
                results[key] = (value, stale)
            except Exception:
                # A malformed provider response must not expose server diagnostics.
                results[key] = (None, False)
    series = {name: results.get(f'fred:{name}', (None, False))[0] for name in FRED_SERIES}
    vix, vix_stale = results.get('vix', (None, False))
    if vix is None and series.get('VIXCLS'):
        date, price = series['VIXCLS'][-1]
        vix = {'value': round(price, 2), 'previous_close': None, 'as_of': date,
               'source': 'FRED (daily close)', 'url': 'https://fred.stlouisfed.org/series/VIXCLS', 'frequency': 'Daily close'}
        vix_stale = results.get('fred:VIXCLS', (None, False))[1]
    fear, fear_stale = results.get('fear_greed', (None, False))
    if vix:
        vix['stale'] = vix_stale
    if fear:
        fear['stale'] = fear_stale
    rows = _economic_rows(series)
    for item in rows:
        id = item['id']
        item['stale'] = bool(results.get('fred:'+id, (None, False))[1])
    return {'vix': vix, 'fear_greed': fear, 'reports': rows,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'notes': ['The date next to each economic figure is its observation/reference period, not its release date.',
                      'Inflation is 12-month CPI/PCE change; payrolls are the monthly change in thousands.',
                      'Market data can be delayed or unavailable. No figures are estimated when a source fails.']}
