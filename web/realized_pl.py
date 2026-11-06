"""Private realized P/L from recorded gains and matched Nordnet cash movements."""
from account_public import _num


def trade_gains(account, document):
    """Yield each sale and its available gain/currency without modifying the ledger."""
    basis = {}
    date_key = 'trade_date' if account == 'dk' else 'date'
    for trade in sorted(document.get('transactions', []), key=lambda row: row.get(date_key) or ''):
        action = trade.get('action')
        ticker = trade.get('ticker')
        gain = _num(trade.get('realized_gain_in_quote_currency'))
        currency = 'USD' if account == 'us' else trade.get('price_currency')
        if account == 'dk':
            quantity, cost = basis.get(ticker, (0.0, 0.0))
            units = _num(trade.get('quantity')) or 0
            cash = _num(trade.get('net_cash_movement_dkk'))
            if action == 'BUY' and units > 0:
                basis[ticker] = (quantity + units, cost - cash
                                 if cost is not None and cash is not None and cash < 0 else None)
            elif action == 'SPLIT':
                basis[ticker] = (round(quantity * float(trade['split_ratio']), 8), cost)
            elif action == 'SELL' and units > 0:
                if quantity > 0 and units <= quantity + 1e-7:
                    remaining = max(0.0, quantity - units)
                    sold_cost = cost * min(1.0, units / quantity) if cost is not None else None
                    if gain is None and sold_cost is not None and cash is not None and cash > 0:
                        gain, currency = round(cash - sold_cost, 2), 'DKK'
                    basis[ticker] = (remaining, cost - sold_cost if sold_cost is not None else None) if remaining > 1e-7 else (0.0, 0.0)
                else:
                    # Missing opening shares prevent reconstruction until a known position reset.
                    basis[ticker] = (0.0, None)
        if action == 'SELL':
            yield trade, gain, currency
