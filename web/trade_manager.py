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
    if account not in FILES: raise ValueError('Choose Merrill or Nordnet')
    action = str(incoming.get('action','')).upper()
    if action not in ('BUY','SELL'): raise ValueError('Action must be BUY or SELL')
    ticker = str(incoming.get('ticker','')).strip().upper()
    if not TICKER.fullmatch(ticker): raise ValueError('Invalid ticker')
    raw_date = str(incoming.get('date',''))
    try: trade_day = date.fromisoformat(raw_date)
    except ValueError: raise ValueError('Invalid trade date')
    if trade_day > date.today(): raise ValueError('Trade date cannot be in the future')
    if trade_day.weekday() >= 5: raise ValueError('Trade date must be a market weekday')
    if trade_day < date(2023,1,1): raise ValueError('Historical dates before 2023 require manual reconciliation')
    qty = positive_decimal(incoming.get('quantity'), 'Quantity')
    px = positive_decimal(incoming.get('price'), 'Price')
    if qty.as_tuple().exponent < -8: raise ValueError('Maximum 8 decimals for shares')
    currency = str(incoming.get('currency','')).upper()
    if currency not in ('USD','DKK'):raise ValueError('Choose USD or DKK quote currency')
    if account == 'us' and currency != 'USD': raise ValueError('Merrill prices must be in USD')
    if account == 'dk' and ticker.endswith('.CO') and currency!='DKK':raise ValueError('Danish-listed shares must use DKK')
    # Any backdated trade can invalidate later position/cost snapshots.
    if raw_date < source.get('positions_as_of',''):
        raise ValueError('Backdated trades require reconciliation. Use a date on or after the last positions snapshot.')
    data = deepcopy(source)
    positions = data.setdefault('positions',[])
    item = next((p for p in positions if p.get('ticker')==ticker),None)
    old_q=Decimal(str(item.get('quantity',0))) if item else Decimal('0')
    if action=='SELL' and qty>old_q:raise ValueError('Cannot sell more shares than owned')
    if item and item.get('cost_currency',currency)!=currency:
        raise ValueError('Price currency differs from existing position')
    avg=Decimal(str(item.get('average_cost_per_share',0))) if item else Decimal('0')
    new_q=old_q+(qty if action=='BUY' else -qty)
    # Weighted average is only an approximation when the broker uses tax-lot accounting.
    new_avg=((old_q*avg+qty*px)/new_q) if action=='BUY' else avg
    if action=='BUY' and not item:
        item={'ticker':ticker,'cost_currency':currency,'source':'manual_trade_manager'}
        positions.append(item)
    if new_q==0:
        positions.remove(item)
    else:
        item['quantity']=float(new_q)
        item['average_cost_per_share']=float(round(new_avg,6))
        if account=='us':item['broker_reported_cost_basis']=float(round(new_q*new_avg,2))
        else:item['reconstructed_open_cost_in_quote_currency']=float(round(new_q*new_avg,2))
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
               'net_cash_movement_dkk':None,'fee_dkk':0}
    data.setdefault('transactions',[]).append(event)
    data['positions_as_of']=max(source.get('positions_as_of',raw_date),raw_date)
    data['manual_trade_last_updated']=date.today().isoformat()
    return data,event
