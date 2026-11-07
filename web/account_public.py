"""Safe projections of private Merrill/Nordnet files for the public dashboard.

Never return position quantities, position dollar values, cash, or transaction ledgers.
Reconstructed performance is based on separately validated CSVs, not current holdings.
"""
import csv
import io
import math
import requests
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from threading import Lock
from public_analytics import SECTORS, _load_history

ETF_TICKERS = frozenset({'VOO', 'IWM'})

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

def _positions(us,dk,account,include_etfs=True):
    positions=[]
    for key,document in [('us',us),('dk',dk)]:
        if account not in ('combined',key):continue
        for h in document['positions']:
            quantity=_num(h.get('quantity'))
            cost=_num(h.get('average_cost_per_share'))
            ticker=str(h.get('ticker','')).upper().strip()
            if not ticker or quantity is None or quantity<=0:continue
            if not include_etfs and ticker in ETF_TICKERS:continue
            currency=str(h.get('cost_currency','USD' if key=='us' else 'DKK')).upper()
            positions.append({'ticker':ticker,'quantity':quantity,'cost':cost,
                              'currency':currency,'account':key,
                              'sector':SECTORS.get(ticker,'Other / unclassified')})
    return positions

def _market_history(tickers, period):
    today = date.today()
    start = (date(today.year - 1, 12, 31) if period == 'YTD' else
             today - timedelta(days=PERIODS.get(period) or 3650))
    return _load_history(tickers, start - timedelta(days=8), None)


class QuotePrices(dict):
    """Prices with observation dates retained for freshness reporting."""
    def __init__(self):
        super().__init__()
        self.dates = {}
        self.stale = []


def _quote_prices(tickers):
    history = _load_history(set(tickers) | {'DKK=X'}, date.today()-timedelta(days=12), None)
    prices = QuotePrices()
    for ticker, observations in history.items():
        if not observations:
            continue
        day, value = sorted(observations.items())[-1]
        age = (date.today() - date.fromisoformat(day)).days
        if age < 0 or age > 5 or _num(value) is None or value <= 0:
            prices.stale.append(ticker)
            continue
        prices[ticker] = value
        prices.dates[ticker] = day
    return prices, prices.get('DKK=X')


def quote_metadata(prices):
    dates = getattr(prices, 'dates', {})
    return {'quote_dates': dates, 'market_data_through': min(dates.values()) if dates else None,
            'stale_tickers': sorted(getattr(prices, 'stale', []))}


def snapshot(us,dk,account,currency="USD",include_etfs=False):
    positions=_positions(us,dk,account,include_etfs)
    def build():
        prices,fx=_quote_prices({p['ticker'] for p in positions})
        holdings={}; missing=set(); sector_values=defaultdict(float)
        for p in positions:
            ticker=p['ticker']; price=prices.get(ticker)
            if price is None:
                missing.add(ticker)
                continue
            quote_currency='DKK' if ticker.endswith('.CO') else 'USD'
            if fx is None:
                raise ValueError('USD/DKK exchange rate unavailable; cannot compute combined allocations')
            multiplier=(1 if quote_currency=='USD' else 1/fx) if currency=='USD' else (fx if quote_currency=='USD' else 1)
            if multiplier is None:raise ValueError('USD/DKK exchange rate unavailable')
            amount=p['quantity']*price*multiplier
            row=holdings.setdefault(ticker,{'ticker':ticker,'sector':p['sector'],'market_value_private':0,
                                            'currency':currency})
            row['market_value_private']+=amount
            sector_values[p['sector']]+=amount
        total=sum(row['market_value_private'] for row in holdings.values())
        result=[]
        for row in holdings.values():
            result.append({'ticker':row['ticker'],'sector':row['sector'],
                           'currency':row['currency'],
                           'allocation_pct':round(100*row['market_value_private']/total,2) if total else None})
        for ticker in sorted(missing):
            if ticker not in holdings:
                item = next(p for p in positions if p['ticker']==ticker)
                result.append({'ticker':ticker,'sector':item['sector'],'currency':currency,'allocation_pct':None})
        result.sort(key=lambda x: (x['allocation_pct'] is None,-(x['allocation_pct'] or 0)))
        return {'holdings':result,'sectors':[{'sector':s,'allocation_pct':round(100*v/total,2)} for s,v in sorted(sector_values.items(),key=lambda x:-x[1])] if total else [],
                'basis':'latest market value','missing_tickers':sorted(missing),
                **quote_metadata(prices),
                'as_of':datetime.now(timezone.utc).isoformat(),
                # Snapshot dates are public metadata only; no raw trades/quantities.
                'positions_as_of':{
                    key:doc.get('positions_as_of') for key,doc in (('us',us),('dk',dk))
                    if account in ('combined',key)
                },
                'account':account,'currency':currency,'include_etfs':include_etfs}
    return _cached(('snapshot',account,currency,include_etfs,tuple(sorted((p['ticker'],p['quantity'],p['cost']) for p in positions))),build)

def _series(csv_text, portfolio_col, spy_col):
    result=[]
    for row in csv.DictReader(io.StringIO(csv_text)):
        p=_num(row.get(portfolio_col));s=_num(row.get(spy_col)); day=row.get('date')
        if day and p is not None and s is not None:result.append((day,p,s))
    return sorted(result)

def _select_period(rows, period, today=None):
    if not rows:return []
    last=date.fromisoformat(rows[-1][0]); start=(date((today or date.today()).year - 1, 12, 31) if period=='YTD' else
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
        observations = sorted(history.get(ticker, {}).items())
        baseline = observations[0][1] if observations else 0
        rows = [(day, (value / baseline - 1) * 100, (value / baseline - 1) * 100)
                for day, value in observations] if baseline > 0 else []
        # Use the same baseline rules as the portfolio chart, not the fetch buffer.
        selected = _select_period(rows, period)
        if selected:
            results.append({'ticker': ticker, 'return_pct': round(selected[-1]['portfolio'], 2)})
    return sorted(results,key=lambda x:-x['return_pct'])

def _fx_levels(nordnet_text):
    """Relative USD/DKK from the validated Nordnet USD and DKK SPY series.

    Uses existing daily benchmark observations instead of a fresh live FX quote.
    Both SPY series share the same price history and starting date.
    """
    levels={}
    for r in csv.DictReader(io.StringIO(nordnet_text)):
        usd=_num(r.get('spy_usd_pct')); dkk=_num(r.get('spy_dkk_pct'))
        if usd is not None and dkk is not None and 1+usd/100>0:
            levels[r['date']]=(1+dkk/100)/(1+usd/100)
    return levels


def _convert_series(rows, from_currency, to_currency, fx):
    if from_currency==to_currency: return rows
    base_day=next((day for day,_,_ in rows if day in fx),None)
    if base_day is None: return []
    base_fx=fx[base_day]
    out=[]
    for day,portfolio,benchmark in rows:
        if day not in fx: continue
        factor=fx[day]/base_fx
        factor=factor if from_currency=='USD' else 1/factor
        # Only portfolio is converted; benchmark is supplied separately below.
        out.append((day, ((1+portfolio/100)*factor-1)*100, benchmark))
    return out


def analytics(us,dk,account,period,read_csv,currency='USD',include_etfs=False):
    if period not in PERIODS or currency not in ('USD','DKK'):
        raise ValueError('Invalid analytics period or currency')
    positions=_positions(us,dk,account,include_etfs)
    nordnet_text=read_csv('portfolio/performance/nordnet_all_available_provisional.csv')
    nordnet=list(csv.DictReader(io.StringIO(nordnet_text)))
    benchmark={r['date']:_num(r.get('spy_usd_pct' if currency=='USD' else 'spy_dkk_pct')) for r in nordnet}
    fx=_fx_levels(nordnet_text)
    note=''
    if account=='combined':
        # Daily combined weights must be calculated from dated securities positions,
        # never averaged from two portfolio return percentages.
        try:
            combined_text=read_csv('portfolio/performance/combined_history_provisional.csv' if include_etfs else 'portfolio/performance/combined_no_etf_history_provisional.csv')
            key='portfolio_usd_pct' if currency=='USD' else 'portfolio_dkk_pct'
            rows=[(r['date'],_num(r.get(key)),benchmark.get(r['date']))
                  for r in csv.DictReader(io.StringIO(combined_text))]
            rows=[r for r in rows if r[1] is not None and r[2] is not None]
            note='Provisional combined invested-securities return, weighted by each account’s historical market value, in '+currency+'. Excludes idle cash, ADBE and unrecorded dividends.'
        except (ValueError,KeyError,RuntimeError,OSError,requests.RequestException):
            rows=[]
            note='This performance mode requires its private calculation workflow. Run Daily Portfolio Performance in the private repository. Older combined periods are not yet supported.'
    elif account=='us':
        try:
            text=read_csv('portfolio/performance/merrill_history_provisional.csv' if include_etfs else 'portfolio/performance/merrill_no_etf_history_provisional.csv')
            raw=[(r['date'],_num(r.get('portfolio_pct')),benchmark.get(r['date']))
                 for r in csv.DictReader(io.StringIO(text))]
            raw=[r for r in raw if r[1] is not None and r[2] is not None]
            rows=_convert_series(raw,'USD',currency,fx)
            note=f'Provisional Merrill invested-securities return in {currency}, SPY in {currency}. Excludes ADBE, idle cash and dividends.'
        except (ValueError,KeyError,RuntimeError,OSError,requests.RequestException):
            rows=[]
            note='ETF-excluded historical returns are not published yet. Run Daily Portfolio Performance in the private repository.'
    else:
        if not include_etfs and any(t.get('ticker') in ETF_TICKERS for t in dk.get('transactions', [])):
            try:
                nordnet = list(csv.DictReader(io.StringIO(read_csv(
                    'portfolio/performance/nordnet_no_etf_all_available_provisional.csv'))))
            except (ValueError, KeyError, RuntimeError, OSError, requests.RequestException):
                nordnet = []
        raw=[(r['date'],_num(r.get('portfolio_pct')),benchmark.get(r['date'])) for r in nordnet]
        raw=[r for r in raw if r[1] is not None and r[2] is not None]
        rows=_convert_series(raw,'DKK',currency,fx)
        note=f'Provisional Nordnet invested-securities return in {currency}, SPY in {currency}. Excludes idle cash and dividends.'
    note += ' ETFs included.' if include_etfs else ' ETFs excluded.'
    performance=_select_period(sorted(rows),period)
    gainers=_cached(('gainers',account,period,include_etfs,tuple(sorted(p['ticker'] for p in positions))),
                    lambda:_gainers(positions,period),600)
    return {'period':period,'account':account,'currency':currency,'include_etfs':include_etfs,
            'performance':[{'date':p['date'],'value':p['portfolio']} for p in performance],
            'spy':[{'date':p['date'],'value':p['spy']} for p in performance],
            'gainers':gainers,'performance_note':note,
            'available_from':performance[0]['date'] if performance else None,
            'performance_through':performance[-1]['date'] if performance else None,
            'missing_tickers':sorted(set(p['ticker'] for p in positions)-set(g['ticker'] for g in gainers)),
            'spy_selected_period':None}
