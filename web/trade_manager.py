"""Authenticated manual trade journaling. This DOES NOT execute brokerage orders."""
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
import re
import uuid

TICKER = re.compile(r'^[A-Z0-9][A-Z0-9.\-^]{0,19}$')
FILES = {'us': 'portfolio/merrill_portfolio.json', 'dk': 'portfolio/nordnet_portfolio.json'}

def positive_decimal(value, field):
    if isinstance(value, bool):
        raise ValueError(f'{field} must be numeric')
    try:
        n = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f'{field} must be numeric')
    if not n.is_finite() or n <= 0 or n > Decimal('1000000000'):
        raise ValueError(f'{field} must be positive and finite')
    return n

def record_trade(source, incoming):
    """Return copy of account data + event. Callers must commit with GitHub SHA."""
    if not isinstance(incoming,dict): raise ValueError('Invalid trade')
    account = incoming.get('account')
    if account not in ('us', 'dk'): raise ValueError('Choose Merrill or Nordnet')
    action = str(incoming.get('action','')).upper()
    if action not in ('BUY','SELL','SPLIT'): raise ValueError('Action must be BUY, SELL or SPLIT')
    ticker = str(incoming.get('ticker','')).strip().upper()
    if not TICKER.fullmatch(ticker): raise ValueError('Invalid ticker')
    raw_date = str(incoming.get('date',''))
    try: trade_day = date.fromisoformat(raw_date)
    except ValueError: raise ValueError('Invalid trade date')
    raw_date = trade_day.isoformat()
    if trade_day > date.today(): raise ValueError('Trade date cannot be in the future')
    if trade_day.weekday() >= 5: raise ValueError('Trade date must be a market weekday')
    if trade_day < date(2023,1,1): raise ValueError('Historical dates before 2023 require manual reconciliation')
    split = action == 'SPLIT'
    ratio = positive_decimal(incoming.get('quantity'), 'Split ratio') if split else None
    if split and (ratio == 1 or ratio < Decimal('0.000001') or ratio > 10000):
        raise ValueError('Split ratio must change the share count and be between 0.000001 and 10000')
    qty = Decimal(0) if split else positive_decimal(incoming.get('quantity'), 'Quantity')
    px = Decimal(0) if split else positive_decimal(incoming.get('price'), 'Price')
    raw_fee = incoming.get('fee')
    if raw_fee is None or raw_fee == '':
        fee = Decimal(0)
    else:
        try:
            fee = Decimal(str(raw_fee))
        except InvalidOperation:
            raise ValueError('Brokerage fee must be numeric')
        if not fee.is_finite() or not 0 <= fee <= Decimal('1000000000'):
            raise ValueError('Brokerage fee must be finite and nonnegative')
    if split and fee:
        raise ValueError('Split entries cannot include brokerage fees')
    if qty.as_tuple().exponent < -8: raise ValueError('Maximum 8 decimals for shares')
    currency = str(incoming.get('currency','')).upper()
    if currency not in ('USD','DKK'):raise ValueError('Choose USD or DKK quote currency')
    if account == 'us' and currency != 'USD': raise ValueError('Merrill prices must be in USD')
    if account == 'dk' and ticker.endswith('.CO') and currency!='DKK':raise ValueError('Danish-listed shares must use DKK')
    fee_currency = str(incoming.get('fee_currency') or currency).upper()
    if fee_currency not in ('USD', 'DKK'):
        raise ValueError('Choose USD or DKK brokerage fee currency')
    fee_rate = Decimal(1)
    if fee and fee_currency != currency:
        fee_rate = positive_decimal(incoming.get('fee_exchange_rate'), 'Fee conversion rate')
    original_fee = fee
    fee *= fee_rate
    if fee > Decimal('1000000000'):
        raise ValueError('Converted fee exceeds the supported range')
    # Any backdated trade can invalidate later position/cost snapshots.
    if raw_date < source.get('positions_as_of',''):
        raise ValueError('Backdated trades require reconciliation. Use a date on or after the last positions snapshot.')
    data = deepcopy(source)
    positions = data.setdefault('positions',[])
    item = next((p for p in positions if p.get('ticker')==ticker),None)
    prior_position = deepcopy(item)
    old_q=Decimal(str(item.get('quantity',0))) if item else Decimal('0')
    if split and old_q <= 0: raise ValueError('A split requires an open position')
    if action=='SELL' and qty>old_q:raise ValueError('Cannot sell more shares than owned')
    if item and item.get('cost_currency',currency)!=currency:
        raise ValueError('Price currency differs from existing position')
    basis_key = ('broker_reported_cost_basis' if account == 'us'
                 else 'reconstructed_open_cost_in_quote_currency')
    avg = Decimal(str(item.get('average_cost_per_share') or 0)) if item else Decimal(0)
    basis = Decimal(str(item.get('manual_open_basis', item.get(basis_key) or old_q * avg))) if item else Decimal(0)
    if old_q and basis <= 0:
        raise ValueError('Reconcile the opening cost basis before editing this position')
    realized = None
    if split:
        new_q = (old_q * ratio).quantize(Decimal('0.00000001'))
        if new_q <= 0:
            raise ValueError('Split leaves no shares at supported precision')
    elif action == 'BUY':
        new_q = old_q + qty
        basis += qty * px + fee
    else:
        new_q = old_q - qty
        sold_basis = basis * qty / old_q
        realized = qty * px - fee - sold_basis
        basis -= sold_basis
    new_avg = basis / new_q if new_q else Decimal(0)
    if action=='BUY' and not item:
        item={'ticker':ticker,'cost_currency':currency,'source':'manual_trade_manager'}
        positions.append(item)
    if new_q==0:
        positions.remove(item)
    else:
        item['quantity']=float(new_q)
        item['average_cost_per_share']=float(round(new_avg,6))
        item[basis_key] = float(round(basis, 2))
        item['manual_open_basis'] = str(basis)
        item['cost_currency']=currency
        item['source']='manual_trade_manager_estimated_cost_basis'
    # Caller-provided UUID is used as an idempotency key for uncertain network responses.
    client_id=incoming.get('client_trade_id')
    if client_id is not None:
        try: event_id=str(uuid.UUID(str(client_id)))
        except (ValueError, TypeError, AttributeError):
            raise ValueError('Invalid transaction request ID')
        if any(t.get('event_id') == event_id for t in source.get('transactions', [])):
            raise ValueError('This transaction was already recorded. Refresh trade history.')
    else:
        event_id=str(uuid.uuid4())
    if account=='us':
        event={'date':raw_date,'ticker':ticker,'action':action,'quantity':float(qty),'price_usd':float(px),
               'source':'manual_private_dashboard','verification':'user_reported','event_id':event_id}
    else:
        event={'trade_date':raw_date,'ticker':ticker,'action':action,'quantity':float(qty),
               'execution_price_per_share':float(px),'price_currency':currency,
               'source_transaction_id':'manual-'+event_id,'source':'manual_private_dashboard','event_id':event_id,
               'net_cash_movement_dkk':None,
               'fee_dkk':float(original_fee if fee_currency == 'DKK' else fee)
                         if 'DKK' in (fee_currency, currency) else None}
    reference = str(incoming.get('broker_reference') or '').strip()
    if len(reference) > 100:
        raise ValueError('Broker reference may contain up to 100 characters')
    if reference and any(reference == t.get('broker_reference') for t in data.get('transactions', [])):
        raise ValueError('Broker reference is already recorded for this account')
    fingerprint = [raw_date, action, ticker, currency, float(ratio if split else qty), float(px), float(fee)]
    if not reference and any(t.get('trade_fingerprint') == fingerprint
                             for t in data.get('transactions', [])):
        raise ValueError('Matching transaction exists. Use distinct broker references for identical fills.')
    event.update(fee_original=float(original_fee), fee_currency=fee_currency,
                 fee_exchange_rate=float(fee_rate), trade_fingerprint=fingerprint, position_quantity_after=float(new_q),
                 broker_reference=reference or None, source='manual_private_dashboard', fee_in_quote_currency=float(fee),
                 realized_gain_in_quote_currency=float(round(realized, 2)) if realized is not None else None,
                 prior_position=prior_position, prior_positions_as_of=source.get('positions_as_of', ''),
                 request=canonical_request(incoming))
    if split:
        event.update(split_ratio=float(ratio), quantity=float(new_q - old_q))
    data.setdefault('transactions',[]).append(event)
    data['positions_as_of']=max(source.get('positions_as_of',raw_date),raw_date)
    data['manual_trade_last_updated']=date.today().isoformat()
    return data,event


def canonical_request(incoming):
    return {key: str(incoming.get(key) or '').strip()
            for key in ('account', 'action', 'ticker', 'date', 'quantity', 'price',
                        'currency', 'fee', 'fee_currency', 'fee_exchange_rate', 'corrects', 'broker_reference')}


def prior_request(source, request_id):
    return next((t for t in [*source.get('transactions', []), *source.get('trade_audit', [])]
                 if t.get('event_id') == request_id), None)


def correct_trade(source, incoming):
    """Replace a checkpointed manual entry and replay the later manual entries."""
    events = source.get('transactions', [])
    target = next((i for i, t in enumerate(events)
                   if t.get('event_id') == incoming.get('corrects')), None)
    if target is None or 'request' not in events[target]:
        raise ValueError('Select a current trade recorded with the upgraded Trade Manager')
    tail = events[target:]
    original = tail[0]
    latest = tail[-1]
    if source.get('positions_as_of') != (latest.get('date') or latest.get('trade_date')):
        raise ValueError('The account snapshot has changed. Reconcile it before correcting a trade.')
    if any('request' not in t for t in tail):
        raise ValueError('Later imported trades require manual reconciliation')
    latest_by_ticker = {trade['ticker']: trade for trade in tail}
    held = {position['ticker']: position['quantity'] for position in source['positions']}
    if any(held.get(ticker, 0) != trade['position_quantity_after']
           for ticker, trade in latest_by_ticker.items()):
        raise ValueError('Holdings have changed outside Trade Manager. Reconcile before correcting.')
    data = deepcopy(source)
    for trade in reversed(tail):
        positions = data['positions']
        positions[:] = [p for p in positions if p['ticker'] != trade['ticker']]
        if trade['prior_position'] is not None:
            positions.append(deepcopy(trade['prior_position']))
    data['transactions'] = deepcopy(events[:target])
    data['positions_as_of'] = original['prior_positions_as_of']
    data, replacement = record_trade(data, incoming)
    for trade in tail[1:]:
        data, _ = record_trade(data, {**trade['request'],
                                     'account': incoming['account'],
                                     'client_trade_id': trade['event_id']})
    data.setdefault('trade_audit', []).append({**deepcopy(original),
                                               'superseded_by': replacement['event_id']})
    return data, replacement
