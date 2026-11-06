"""Trade journal storage and explicit public projection."""
import hashlib
import json


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


def public_activity(documents):
    rows = []
    for document in documents:
        for _, trade in journal_trades(document):
            journal = trade.get('journal', {})
            if journal.get('published') is not True or trade['action'] not in ('BUY', 'SELL'):
                continue
            rows.append({'date': trade.get('date') or trade.get('trade_date'),
                         'ticker': trade['ticker'], 'action': trade['action'],
                         'note': journal.get('note', '')})
    return sorted(rows, key=lambda row: row['date'] or '', reverse=True)
