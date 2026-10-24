"""Authenticated portfolio valuations, never exposed from a public route.

Uses the same account documents, ticker universe and latest closing-price source as
account_public.snapshot. Market values are indicative invested-securities values:
no cash, fees, accrued dividends or broker-reported realized P/L are included.
"""
from collections import defaultdict
from datetime import datetime, timezone

from account_public import _positions, _quote_prices


def private_snapshot(us, dk, account='combined', currency='USD', include_etfs=False):
    if account not in ('combined', 'us', 'dk') or currency not in ('USD', 'DKK'):
        raise ValueError('Unsupported portfolio selection')
    positions = _positions(us, dk, account, include_etfs=include_etfs)
    # This must use the same price/FX source as the public snapshot.
    prices, fx = _quote_prices({p['ticker'] for p in positions})
    if positions and (fx is None or fx <= 0):
        raise ValueError('Current USD/DKK rate unavailable; refusing to mix currencies')

    rows = {}
    sectors = defaultdict(float)
    missing = set()
    for p in positions:
        ticker = p['ticker']
        quote_ccy = 'DKK' if ticker.endswith('.CO') else 'USD'
        quote_price = prices.get(ticker)
        quote_price = float(quote_price) if quote_price is not None else None
        # Group ticker across both accounts; retain each account's own quantity.
        row = rows.setdefault(ticker, {
            'ticker': ticker, 'sector': p['sector'], 'currency': currency,
            'accounts': set(), 'quantity': 0.0,
            'market_value': 0.0, 'cost_basis': 0.0,
            'cost_known': True, 'price_known': True,
        })
        row['accounts'].add(p['account'])
        row['quantity'] += p['quantity']
        if quote_price is None or quote_price <= 0:
            row['price_known'] = False
            missing.add(ticker)
            continue
        quote_to_display = (1.0 if quote_ccy == currency else
                            fx if currency == 'DKK' else 1.0 / fx)
        row['market_value'] += p['quantity'] * quote_price * quote_to_display
        if p['cost'] is None or p['cost'] <= 0:
            row['cost_known'] = False
            continue
        native_to_display = (1.0 if p['currency'] == currency else
                             fx if p['currency'] == 'USD' else 1.0 / fx)
        row['cost_basis'] += p['quantity'] * p['cost'] * native_to_display

    # A missing price or cost is not a zero-valued position. Never include its
    # apparent zero in totals or misleading allocation/P&L calculations.
    priced = [r for r in rows.values() if r['price_known']]
    total_value = sum(r['market_value'] for r in priced)
    known_cost = sum(r['cost_basis'] for r in priced if r['cost_known'])
    known_market = sum(r['market_value'] for r in priced if r['cost_known'])
    complete_cost = all(r['cost_known'] for r in priced)
    complete_prices = len(priced) == len(rows)
    holdings = []
    for r in rows.values():
        valued = r['price_known']
        basis = r['cost_basis'] if valued and r['cost_known'] else None
        value = r['market_value'] if valued else None
        qty = r['quantity']
        pnl = value - basis if value is not None and basis is not None else None
        holdings.append({
            'ticker': r['ticker'], 'sector': r['sector'], 'accounts': sorted(r['accounts']),
            'currency': currency, 'quantity': round(qty, 6),
            'average_cost_per_share': round(basis / qty, 4) if basis is not None and qty else None,
            'current_price': round(value / qty, 4) if value is not None and qty else None,
            'market_value': round(value, 2) if value is not None else None,
            'cost_basis': round(basis, 2) if basis is not None else None,
            'unrealized_pl': round(pnl, 2) if pnl is not None else None,
            'return_since_cost_pct': round(100 * pnl / basis, 2) if pnl is not None and basis > 0 else None,
            'allocation_pct': round(100 * value / total_value, 2) if value is not None and total_value > 0 else None,
        })
        if value is not None:
            sectors[r['sector']] += value
    holdings.sort(key=lambda r: (r['market_value'] is None, -(r['market_value'] or 0), r['ticker']))

    return {
        'account': account, 'currency': currency, 'include_etfs': include_etfs,
        'holdings': holdings,
        'position_count': len(positions), 'ticker_count': len(rows),
        'market_value': round(total_value, 2),
        'cost_basis': round(known_cost, 2) if complete_cost and complete_prices else None,
        'unrealized_pl': round(known_market - known_cost, 2) if complete_cost and complete_prices else None,
        'unrealized_pl_pct': round(100 * (known_market - known_cost) / known_cost, 2)
                             if complete_cost and complete_prices and known_cost > 0 else None,
        'sectors': [{'sector': name, 'market_value': round(value, 2),
                     'allocation_pct': round(100 * value / total_value, 2) if total_value else None}
                    for name, value in sorted(sectors.items(), key=lambda kv: -kv[1])],
        'missing_tickers': sorted(missing),
        'incomplete_cost_tickers': sorted(r['ticker'] for r in priced if not r['cost_known']),
        'positions_as_of': {key: document.get('positions_as_of') for key, document in
                            (('us', us), ('dk', dk)) if account in ('combined', key)},
        'as_of': datetime.now(timezone.utc).isoformat(),
        'valuation_basis': 'latest available closing prices; cash excluded',
        'cost_basis_note': 'Average open-position costs translated using the latest USD/DKK rate; not a tax or realized P/L statement.',
    }
