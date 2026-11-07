"""Canonical watchlist validation shared by the dashboard and alert tools."""
import math
import re


def ticker_symbol(value):
    symbol = str(value).strip().upper()
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9.^_-]{0,19}', symbol):
        raise ValueError('Invalid ticker symbol')
    return symbol


def positive_target(value):
    if isinstance(value, bool):
        raise ValueError('Targets must be positive finite numbers')
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError('Targets must be positive finite numbers')
    return number


def targets(values):
    if not isinstance(values, list):
        raise ValueError('Targets must be a list')
    return sorted({positive_target(value) for value in values})


def validate_watchlist(raw):
    if not isinstance(raw, dict):
        raise ValueError('Watchlist must be an object')
    result = {}
    for key, entry in raw.items():
        ticker = ticker_symbol(key)
        if ticker in result:
            raise ValueError('Duplicate normalized ticker')
        if isinstance(entry, list):
            entry = {'price_targets': entry}
        if not isinstance(entry, dict):
            raise ValueError('Each ticker must contain targets')
        valuations = entry.get('valuation_targets', entry.get('valuation', {}))
        if not isinstance(valuations, dict):
            raise ValueError('Valuation targets must be an object')
        cleaned = {}
        for metric, directions in valuations.items():
            if metric not in ('FxPE', 'PE', 'P/S'):
                raise ValueError('Unknown valuation metric')
            if isinstance(directions, list):
                directions = {'trim': directions}
            if not isinstance(directions, dict) or set(directions) - {'trim', 'buy'}:
                raise ValueError('Invalid valuation direction')
            buckets = {d: targets(directions.get(d, [])) for d in ('trim', 'buy')}
            if any(buckets.values()):
                cleaned[metric] = buckets
        result[ticker] = {'price_targets': targets(entry.get('price_targets', entry.get('price', []))),
                          'valuation_targets': cleaned}
    return result
