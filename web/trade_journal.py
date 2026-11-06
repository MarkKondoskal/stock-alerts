"""Trade journal storage and explicit public projection."""
import hashlib
import json

from account_public import _num


def journal_trades(document):
    for index, trade in enumerate(document.get('transactions', [])):
        if trade.get('action') not in ('BUY', 'SELL', 'SPLIT'):
            continue
        key = trade.get('event_id') or trade.get('source_transaction_id')
        if not key:
            # Include the index to distinguish identical imported fills.
            original = {k: v for k, v in trade.items() if k != 'journal'}
            identity = json.dumps([index, original], sort_keys=True).encode()
            key = hashlib.sha256(identity).hexdigest()
        yield key, trade


def journal_update(body, trade):
    note = body.get('note')
    published = body.get('published')
    if not isinstance(note, str) or len(note) > 2000 or type(published) is not bool:
        raise ValueError('Enter a note of up to 2,000 characters and choose its visibility.')
    if published and trade['action'] not in ('BUY', 'SELL'):
        raise ValueError('Only buys and sells can be shared publicly.')
    return {'note': note.strip(), 'published': published}


def position_change(action, before, after):
    if before is None or after is None:
        return None
    if action == 'BUY' and before <= 1e-7:
        return 'New holding'
    if action == 'SELL' and after <= 1e-7:
        return 'Closed position'
    change = abs(after - before) / before
    band = next(label for limit, label in (
        (0.25, 'less than 25%'), (0.5, '25–50%'), (1, '50–100%'),
        (float('inf'), '100% or more'),
    ) if change < limit)
    verb = 'Increased' if action == 'BUY' else 'Reduced'
    return f'{verb} position by {band}'


def public_activity(documents):
    rows = []

    def day(trade):
        return trade.get('date') or trade.get('trade_date') or ''

    for document in documents:
        positions = {}
        for trade in sorted(document.get('transactions', []), key=day):
            action, ticker = trade.get('action'), trade.get('ticker')
            if not ticker or action not in ('BUY', 'SELL', 'DRIP', 'SPINOFF', 'SPLIT'):
                continue
            before = positions.get(ticker, 0.0)
            units = _num(trade.get('quantity'))
            recorded_after = _num(trade.get('position_quantity_after'))
            if action == 'SPLIT':
                ratio = _num(trade.get('split_ratio'))
                after = before * ratio if before is not None and ratio and ratio > 0 else None
            elif units is None or units <= 0:
                after = None
            else:
                delta = -units if action == 'SELL' else units
                if recorded_after is not None and recorded_after >= 0:
                    after, before = recorded_after, max(0.0, recorded_after - delta)
                else:
                    after = before + delta if before is not None else None
                    if after is not None:
                        after = max(0.0, after) if after >= -1e-7 else None
            positions[ticker] = after
            if action not in ('BUY', 'SELL'):
                continue
            journal = trade.get('journal', {})
            row = {'date': day(trade), 'ticker': ticker, 'action': action,
                   'position_change': position_change(action, before, after),
                   'note': journal.get('note', '') if journal.get('published') is True else ''}
            if action == 'BUY':
                price = _num(trade.get('price_usd'))
                currency = 'USD'
                if price is None:
                    price = _num(trade.get('execution_price_per_share'))
                    currency = trade.get('price_currency')
                if price is not None and price > 0 and currency in ('USD', 'DKK'):
                    row.update(buy_price=price, buy_currency=currency)
            rows.append(row)
    return sorted(reversed(rows), key=lambda row: row['date'], reverse=True)
