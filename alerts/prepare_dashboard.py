"""Prepare dashboard results outside page requests; store only in the private repo."""
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'web')]
import account_public
from private_holdings import private_snapshot
from prepared import digest, pack
from watchlist_market import quote
from watchlist_rules import validate_watchlist
from performance_files import LEGACY_NAMES
from alerts.publish_dashboard_data import publish


def build(checkout):
    import yfinance as yf
    us = json.loads((checkout/'portfolio/merrill_portfolio.json').read_text(encoding='utf-8'))
    dk = json.loads((checkout/'portfolio/nordnet_portfolio.json').read_text(encoding='utf-8'))
    watchlist = validate_watchlist(json.loads((checkout/'alerts/watchlist.json').read_text(encoding='utf-8')))
    generated = datetime.now(timezone.utc).isoformat()
    positions = account_public._positions(us, dk, 'combined')
    tickers = {p['ticker'] for p in positions}
    # One shared download, rather than downloading separately for every chart selection.
    history = account_public._load_history(tickers | {'DKK=X'}, date.today()-timedelta(days=3660), None)
    original = account_public._load_history
    account_public._load_history = lambda symbols, start, intraday: {
        ticker: {day: value for day, value in history.get(ticker, {}).items() if day >= start.isoformat()}
        for ticker in set(symbols) | {'SPY'}}

    def read_csv(path):
        file = checkout/path
        if not file.exists():
            file = file.with_name(LEGACY_NAMES.get(file.name, file.name))
        return file.read_text(encoding='utf-8')

    bundle = {'schema': 1, 'generated_at': generated, 'accounts': [digest(us), digest(dk)],
              'public': {}, 'private': {}, 'analytics': {}, 'watchlist': {}}
    try:
        for account in ('combined', 'us', 'dk'):
            for currency in ('USD', 'DKK'):
                for etfs in (False, True):
                    key = f'{account}:{currency}:{int(etfs)}'
                    bundle['public'][key] = account_public.snapshot(us, dk, account, currency, etfs)
                    bundle['private'][key] = private_snapshot(us, dk, account, currency, etfs)
                    for period in account_public.PERIODS:
                        bundle['analytics'][key+':'+period] = account_public.analytics(
                            us, dk, account, period, read_csv, currency, etfs)
    finally:
        account_public._load_history = original

    def market(ticker):
        try:
            return ticker, quote(yf.Ticker(ticker).get_info() or {}, generated)
        except Exception:
            # Missing provider data stays unavailable, never fabricated.
            return ticker, {'price': None, 'valuations': {}, 'fetched_at': generated,
                            'price_as_of': None, 'currency': '', 'unavailable': True}
    with ThreadPoolExecutor(max_workers=3) as pool:
        bundle['watchlist'] = dict(pool.map(market, sorted(watchlist)))
    if tickers and any(not bundle['public'][key]['holdings'] for key in ['combined:USD:0']):
        raise ValueError('Prepared holdings are empty; preserving last successful snapshot')
    return bundle


if __name__ == '__main__':
    bundle = build(Path(os.environ['STOCKALERTS_PRIVATE_CHECKOUT']))
    publish('portfolio/dashboard_snapshot.json', pack(bundle))
    print('Published prepared dashboard data; no account details printed.')
