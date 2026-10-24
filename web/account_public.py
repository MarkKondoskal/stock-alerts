"""Safe projections of private Merrill/Nordnet files for the public dashboard.

Never return position quantities, position dollar values, cash, or transaction ledgers.
Reconstructed performance is based on separately validated CSVs, not current holdings.
"""
import csv
import io
import math
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from threading import Lock
from public_analytics import SECTORS, _load_history

PERIODS = {'1D':1,'1W':7,'1M':30,'3M':90,'6M':183,'YTD':None,'1Y':365,'3Y':1096,'ALL':None}
SECTORS.update({'VOO':'ETF / Broad Market','IWM':'ETF / Small Cap','MBGL':'Industrials',
                'NBIS':'Technology','NOVO-B.CO':'Health Care','GOOGL':'Communication Services'})
_CACHE={}
_LOCK=Lock()

def _cached(key, build, duration=180):
    with _LOCK:
        entry=_CACHE.get(key)
        if entry and time.time()-entry[0] < duration: return entry[1]
    result=build()
    with _LOCK:
        if len(_CACHE)>80: _CACHE.clear()
        _CACHE[key]=(time.time(),result)
    return result

def _num(value):
    try:
        v=float(value)
        return v if math.isfinite(v) else None
    except (ValueError,TypeError):return None

def _positions(us,dk,account):
    positions=[]
    for key,document in [('us',us),('dk',dk)]:
        if account not in ('combined',key):continue
        for h in document['positions']:
            quantity=_num(h.get('quantity'))
            cost=_num(h.get('average_cost_per_share'))
            ticker=str(h.get('ticker','')).upper().strip()
            if not ticker or quantity is None or quantity<=0:continue
            currency=str(h.get('cost_currency','USD' if key=='us' else 'DKK')).upper()
            positions.append({'ticker':ticker,'quantity':quantity,'cost':cost,
                              'currency':currency,'account':key,
                              'sector':SECTORS.get(ticker,'Other / unclassified')})
    return positions

def _market_history(tickers, period):
    return _load_history(tickers,date.today()-timedelta(days=8 if period in ('1D','1W') else (PERIODS.get(period) or 3650)+8),
                         period if period in ('1D','1W') else None)

def _quote_prices(tickers):
    # USD/DKK is required for the combined account's weights.
    history=_load_history(set(tickers)|{'DKK=X'},date.today()-timedelta(days=12),None)
    prices={k: list(sorted(h.items()))[-1][1] for k,h in history.items() if h}
    fx=prices.get('DKK=X')
    return prices,fx

def snapshot(us,dk,account):
    positions=_positions(us,dk,account)
    def build():
        prices,fx=_quote_prices({p['ticker'] for p in positions})
        holdings={}; missing=set(); sector_values=defaultdict(float)
        for p in positions:
            ticker=p['ticker']; price=prices.get(ticker)
            if price is None:
                missing.add(ticker)
                continue
            # Yahoo quote currency: Nordnet's NOVO-B.CO is DKK; others here USD.
            quote_currency='DKK' if ticker=='NOVO-B.CO' else 'USD'
            if account=='combined' and fx is None:
                raise ValueError('USD/DKK exchange rate unavailable; cannot compute combined allocations')
            multiplier=(1 if quote_currency=='USD' else (1/fx if fx else 1)) if account!='dk' else ((fx if fx else None) if quote_currency=='USD' else 1)
            if multiplier is None:raise ValueError('USD/DKK exchange rate unavailable')
            amount=p['quantity']*price*multiplier
            row=holdings.setdefault(ticker,{'ticker':ticker,'sector':p['sector'],'market_value_private':0,
                                            'cost_basis_private':0,'quantity_private':0,'currency':quote_currency,
                                            'latest':price,'accounts':set()})
            row['market_value_private']+=amount
            row['quantity_private']+=p['quantity']
            # Brokerage cost and market quote must be in the same currency for per-share return.
            if p['cost'] is not None:
                cost_in_quote=p['cost'] if p['currency']==quote_currency else (p['cost']*fx if p['currency']=='DKK' else p['cost']/fx) if fx else None
                if cost_in_quote is not None:row['cost_basis_private']+=p['quantity']*cost_in_quote
            row['accounts'].add(p['account'])
            sector_values[p['sector']]+=amount
        total=sum(row['market_value_private'] for row in holdings.values())
        result=[]
        for row in holdings.values():
            qty=row['quantity_private']; cost=row['cost_basis_private']/qty if qty and row['cost_basis_private']>0 else None
            result.append({'ticker':row['ticker'],'sector':row['sector'],
                           'cost_per_share':round(cost,2) if cost else None,
                           'current_price':round(row['latest'],2),
                           'currency':row['currency'],
                           'allocation_pct':round(100*row['market_value_private']/total,2) if total else None,
                           'return_since_cost_pct':round((row['latest']/cost-1)*100,2) if cost else None})
        for ticker in sorted(missing):
            if ticker not in holdings:
                item = next(p for p in positions if p['ticker']==ticker)
                result.append({'ticker':ticker,'sector':item['sector'],'cost_per_share':round(item['cost'],2) if item['cost'] else None,
                               'current_price':None,'currency':item['currency'],'allocation_pct':None,
                               'return_since_cost_pct':None})
        result.sort(key=lambda x: (x['allocation_pct'] is None,-(x['allocation_pct'] or 0)))
        return {'holdings':result,'sectors':[{'sector':s,'allocation_pct':round(100*v/total,2)} for s,v in sorted(sector_values.items(),key=lambda x:-x[1])] if total else [],
                'basis':'latest market value','missing_tickers':sorted(missing),
                'as_of':datetime.now(timezone.utc).isoformat(), 'account':account}
    return _cached(('snapshot',account,tuple(sorted((p['ticker'],p['quantity'],p['cost']) for p in positions))),build)

def _series(csv_text, portfolio_col, spy_col):
    result=[]
    for row in csv.DictReader(io.StringIO(csv_text)):
        p=_num(row.get(portfolio_col));s=_num(row.get(spy_col)); day=row.get('date')
        if day and p is not None and s is not None:result.append((day,p,s))
    return sorted(result)

def _select_period(rows,period):
    if not rows:return []
    last=date.fromisoformat(rows[-1][0]); start=(date(last.year-1,12,31) if period=='YTD' else
        last-timedelta(days=PERIODS[period]) if PERIODS[period] is not None else date.min)
    # A valid chart must have an observation at or before the start boundary.
    initial=[i for i,row in enumerate(rows) if date.fromisoformat(row[0])<=start]
    if period!='ALL' and not initial: return []
    begin=initial[-1] if initial else 0
    selected=rows[begin:]
    if len(selected)<2:return []
    basep,bases=selected[0][1],selected[0][2]
    if 1+basep/100<=0 or 1+bases/100<=0:return []
    return [{'date':day,'portfolio':round(((1+p/100)/(1+basep/100)-1)*100,3),
             'spy':round(((1+s/100)/(1+bases/100)-1)*100,3)} for day,p,s in selected]

def _gainers(positions,period):
    tickers=set(p['ticker'] for p in positions)
    history=_market_history(tickers,period)
    results=[]
    for ticker in tickers:
        vals=[v for _,v in sorted(history.get(ticker,{}).items())]
        if len(vals)>=2 and vals[0]>0:
            results.append({'ticker':ticker,'return_pct':round((vals[-1]/vals[0]-1)*100,2)})
    return sorted(results,key=lambda x:-x['return_pct'])

def analytics(us,dk,account,period,read_csv):
    if period not in PERIODS:raise ValueError('Invalid period')
    positions=_positions(us,dk,account)
    if account=='combined':
        performance=[]
        note='Combined historical return is not yet available: past US/DK invested account weights and currency conversions must be reconciled. No synthetic average is shown.'
    elif account=='us':
        text=read_csv('portfolio/performance/merrill_2026_ytd_provisional.csv')
        # Use one shared, USD-denominated SPY history for all account views.
        # Match benchmark and portfolio dates before period rebasing.
        common_spy_text=read_csv('portfolio/performance/nordnet_all_available_provisional.csv')
        common_spy={r['date']:_num(r.get('spy_usd_pct'))
                    for r in csv.DictReader(io.StringIO(common_spy_text))}
        rows=[]
        for r in csv.DictReader(io.StringIO(text)):
            day=r.get('date'); p=_num(r.get('portfolio_pct')); benchmark=common_spy.get(day)
            if day and p is not None and benchmark is not None:
                rows.append((day,p,benchmark))
        performance=_select_period(sorted(rows),period)
        note='Provisional US invested-securities return (USD) vs SPY (USD). Excludes ADBE, idle cash and dividends.'
    else:
        text=read_csv('portfolio/performance/nordnet_all_available_provisional.csv')
        performance=_select_period(_series(text,'portfolio_pct','spy_usd_pct'),period)
        note='Provisional Nordnet invested-securities return (DKK) compared with SPY (USD). Currency effects are included in Nordnet returns but not the benchmark; excludes idle cash and dividends.'
    gainers=_cached(('gainers',account,period,tuple(sorted(p['ticker'] for p in positions))),
                    lambda:_gainers(positions,period),600)
    return {'period':period,'account':account,
            'performance':[{'date':p['date'],'value':p['portfolio']} for p in performance],
            'spy':[{'date':p['date'],'value':p['spy']} for p in performance],
            'gainers':gainers, 'performance_note':note,
            'available_from':performance[0]['date'] if performance else None,
            'missing_tickers':sorted(set(p['ticker'] for p in positions)-set(g['ticker'] for g in gainers)),
            'spy_selected_period':None}
