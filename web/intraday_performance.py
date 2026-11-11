"""Calculate an indicative 1D return from five-minute quotes."""
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from threading import Lock
from zoneinfo import ZoneInfo

from account_public import _cached, _positions
from public_analytics import _load_history

FX = 'DKK=X'
NEW_YORK = ZoneInfo('America/New_York')
COPENHAGEN = ZoneInfo('Europe/Copenhagen')
DOWNLOAD_LOCK = Lock()


def intraday(us, dk, account, currency, include_etfs):
    shares = defaultdict(float)
    for position in _positions(us, dk, account, include_etfs):
        shares[position['ticker']] += position['quantity']
    if not shares:
        return {'performance': [], 'spy': [], 'performance_note': 'No holdings match this selection.'}
    tickers = frozenset(shares) | ({FX} if currency == 'DKK' or any(t.endswith('.CO') for t in shares) else set())
    now = datetime.now(timezone.utc)
    # Reuse one download across concurrent refreshes for the same ticker set.
    with DOWNLOAD_LOCK:
        history = _cached(('intraday-5m', tickers), lambda: _load_history(tickers, now.date(), '1D'), 240)
    return build_series(shares, currency, history, now)


def build_series(shares, currency, history, now):
    session = now.astimezone(NEW_YORK).date()
    series = {}
    for ticker, observations in history.items():
        points = []
        for stamp, price in observations.items():
            instant = datetime.fromisoformat(stamp)
            if instant.tzinfo is not None and instant <= now and instant.astimezone(NEW_YORK).date() == session:
                points.append((instant, price))
        points.sort()
        series[ticker] = ([point[0] for point in points], [point[1] for point in points])

    def quote(ticker, at):
        times, values = series.get(ticker, ([], []))
        index = bisect_right(times, at) - 1
        if index < 0:
            return None
        stamp = times[index]
        if at - stamp <= timedelta(minutes=20):
            return values[index], stamp
        # Only carry a same-session Danish quote from around the regular close.
        if (ticker.endswith('.CO') and at.astimezone(COPENHAGEN).time() >= time(17, 10)
                and stamp.astimezone(COPENHAGEN).time() >= time(16, 40)):
            return values[index], stamp
        return None

    portfolio, benchmark = [], []
    base_value = base_spy = None
    oldest = None
    needs_fx = currency == 'DKK' or any(t.endswith('.CO') for t in shares)
    for at, spy in zip(*series.get('SPY', ([], []))):
        fx = quote(FX, at) if needs_fx else None
        required = [(ticker, quantity, quote(ticker, at)) for ticker, quantity in shares.items()]
        if any(observation is None for _, _, observation in required):
            continue
        if needs_fx and fx is None:
            continue
        total, timestamps = 0.0, [at]
        for ticker, quantity, (price, stamp) in required:
            native = 'DKK' if ticker.endswith('.CO') else 'USD'
            if native != currency:
                price *= fx[0] if currency == 'DKK' else 1 / fx[0]
            total += quantity * price
            timestamps.append(stamp)
        if fx is not None:
            timestamps.append(fx[1])
        if currency == 'DKK':
            spy *= fx[0]
        if base_value is None:
            base_value, base_spy = total, spy
        portfolio.append({'date': at.isoformat(), 'value': round(100 * (total / base_value - 1), 4)})
        benchmark.append({'date': at.isoformat(), 'value': round(100 * (spy / base_spy - 1), 4)})
        oldest = min(timestamps)

    return {
        'performance': portfolio, 'spy': benchmark,
        'oldest_quote_at': oldest.isoformat() if oldest else None,
        'performance_note': ('Provisional price return using current holdings, from the first matched five-minute bar. '
                             'Danish positions can use their last local quote after Copenhagen closes.'
                             if portfolio else 'Waiting for matched intraday quotes from the current U.S. session.'),
    }
