"""Risk and attribution calculations with explicit public fields."""
import csv
import io
import json
import math
from collections import defaultdict
from statistics import stdev


def risk_metrics(points, daily=True):
    if not points:
        return {'max_drawdown_pct': None, 'volatility_pct': None,
                'relative_pp': None, 'rolling': [], 'drawdowns': []}
    levels = [1 + row['portfolio'] / 100 for row in points]
    spy = [1 + row['spy'] / 100 for row in points]
    peak = levels[0]
    drawdowns = []
    rolling = []
    for i, (row, level) in enumerate(zip(points, levels)):
        peak = max(peak, level)
        drawdowns.append({'date': row['date'], 'value': round((level / peak - 1) * 100, 3)})
        if daily and i >= 21:
            rolling.append({'date': row['date'],
                            'portfolio_pct': round((level / levels[i-21] - 1) * 100, 3),
                            'spy_pct': round((spy[i] / spy[i-21] - 1) * 100, 3)})
    daily_returns = [b/a - 1 for a, b in zip(levels, levels[1:])]
    return {'max_drawdown_pct': min(row['value'] for row in drawdowns),
            'volatility_pct': round(stdev(daily_returns) * math.sqrt(252) * 100, 3)
            if daily and len(daily_returns) > 1 else None,
            'relative_pp': round(points[-1]['portfolio'] - points[-1]['spy'], 3),
            'drawdowns': drawdowns, 'rolling': rolling}


def attribution(text, points, currency, private=False):
    if len(points) < 2:
        return []
    rows = {r['date']: r for r in csv.DictReader(io.StringIO(text)) if r['currency'] == currency}
    linked, amounts = defaultdict(float), defaultdict(float)
    for previous, current in zip(points, points[1:]):
        row = rows.get(current['date'])
        if row is None or row['previous_date'] != previous['date']:
            return []
        level = 1 + previous['portfolio'] / 100
        for ticker, fraction in json.loads(row['fraction']).items():
            linked[ticker] += fraction * level * 100
        if private:
            for ticker, amount in json.loads(row['market_move']).items():
                amounts[ticker] += amount
    result = [{'ticker': ticker, 'contribution_pp': round(value, 3)}
              for ticker, value in sorted(linked.items(), key=lambda item: -abs(item[1]))]
    if private:
        for row in result:
            row['market_move_amount'] = round(amounts[row['ticker']], 2)
    return result
