"""Market quote projection and directional distance to each configured target."""
from datetime import datetime, timezone
import math


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else None
    except (TypeError, ValueError):
        return None


def quote(info, fetched_at):
    stamp = info.get('regularMarketTime')
    price = number(info.get('currentPrice')) or number(info.get('regularMarketPrice'))
    stale = bool(number(stamp) and (datetime.fromisoformat(fetched_at) - datetime.fromtimestamp(stamp, timezone.utc)).total_seconds() > 5*86400)
    if stale:
        price = None
    return {'price': price, 'stale_price': stale,
            'currency': str(info.get('currency') or ''),
            'valuations': {metric: number(info.get(key)) for metric, key in
                           [('FxPE', 'forwardPE'), ('PE', 'trailingPE'), ('P/S', 'priceToSalesTrailing12Months')]},
            'price_as_of': datetime.fromtimestamp(stamp, timezone.utc).isoformat() if number(stamp) else None,
            'fetched_at': fetched_at}


def enrich(targets, market=None):
    market = market or {}
    checks = []
    values = [('PRICE', 'buy', value) for value in targets.get('price_targets', [])]
    for metric, directions in targets.get('valuation_targets', {}).items():
        if isinstance(directions, list):
            directions = {'trim': directions}
        for direction in ('buy', 'trim'):
            values += [(metric, direction, value) for value in directions.get(direction, [])]
    for metric, direction, target in values:
        actual = number(market.get('price') if metric == 'PRICE' else market.get('valuations', {}).get(metric))
        target = number(target)
        if target is None:
            continue
        met = actual <= target if actual and direction == 'buy' else actual >= target if actual else None
        checks.append({'metric': metric, 'direction': direction, 'target': target,
                       'change_pct': round((target / actual - 1) * 100, 2) if actual else None,
                       'met': met})
    return {**targets, 'market': market, 'proximity': checks}
