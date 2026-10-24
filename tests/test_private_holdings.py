"""Mocked currency, valuation, privacy and state tests. No market/network calls."""
import json
import os
import sys
import unittest
import importlib.util
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'web'))
from private_holdings import private_snapshot
import account_public

FIX = Path(__file__).resolve().parents[2]


def sample_accounts():
    with (FIX / 'merrill_portfolio.json').open() as f:
        us = json.load(f)
    with (FIX / 'nordnet_portfolio.json').open() as f:
        dk = json.load(f)
    return us, dk


class PrivateHoldingsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.us, cls.dk = sample_accounts()

    @staticmethod
    def quotes(_):
        prices = {p['ticker']: 100.0 for d in [PrivateHoldingsTest.us, PrivateHoldingsTest.dk]
                  for p in d['positions']}
        prices['NOVO-B.CO'] = 450.0  # DKK-listed asset
        return prices, 6.5

    def test_all_account_counts_and_excluded_etfs(self):
        with patch('private_holdings._quote_prices', side_effect=self.quotes):
            combined = private_snapshot(self.us, self.dk)
            self.assertEqual(combined['position_count'], 26)
            self.assertEqual(combined['ticker_count'], 23)
            self.assertNotIn('VOO', {r['ticker'] for r in combined['holdings']})
            included = private_snapshot(self.us, self.dk, include_etfs=True)
            self.assertEqual(included['position_count'], 28)
            self.assertEqual(included['ticker_count'], 25)
            self.assertAlmostEqual(sum(r['allocation_pct'] for r in included['holdings']), 100, places=1)
            self.assertEqual(len(private_snapshot(self.us, self.dk, 'dk')['holdings']), 13)
            self.assertEqual(len(private_snapshot(self.us, self.dk, 'us')['holdings']), 13)

    def test_currency_consistency_and_unrealized(self):
        with patch('private_holdings._quote_prices', side_effect=self.quotes):
            usd = private_snapshot(self.us, self.dk, 'combined', 'USD')
            dkk = private_snapshot(self.us, self.dk, 'combined', 'DKK')
            self.assertAlmostEqual(dkk['market_value'], usd['market_value'] * 6.5, delta=.15)
            self.assertAlmostEqual(dkk['cost_basis'], usd['cost_basis'] * 6.5, delta=.15)
            self.assertAlmostEqual(dkk['unrealized_pl'], usd['unrealized_pl'] * 6.5, delta=.15)
            self.assertIn('positions_as_of', usd)
            self.assertTrue(any(r['quantity'] > 0 for r in usd['holdings']))

    def test_missing_quote_not_zero(self):
        def missing(_):
            prices, fx = self.quotes(None)
            prices.pop('AMZN')
            return prices, fx
        with patch('private_holdings._quote_prices', side_effect=missing):
            result = private_snapshot(self.us,self.dk)
            amazon = next(row for row in result['holdings'] if row['ticker'] == 'AMZN')
            self.assertIsNone(amazon['market_value'])
            self.assertIsNone(amazon['allocation_pct'])
            self.assertIsNone(result['cost_basis'])
            self.assertIn('AMZN',result['missing_tickers'])

    def test_new_trade_updates_only_correct_account(self):
        from trade_manager import record_trade
        from datetime import date
        us = json.loads(json.dumps(self.us))
        # Use a current/future date relative to the snapshot, not an old purchase.
        trade = dict(account='us', action='BUY', ticker='NEWTEST', date='2026-10-23',
                     quantity=2, price=90, currency='USD')
        # Match real API naming by adapting to actual form fields (see trade manager).
        # Date is passed unchanged by the private API.
        updated, _ = record_trade(us, trade)
        with patch('private_holdings._quote_prices', side_effect=self.quotes):
            before = private_snapshot(self.us, self.dk, 'us')
            after = private_snapshot(updated, self.dk, 'us')
            self.assertEqual(after['ticker_count'], before['ticker_count'] + 1)
            self.assertEqual(private_snapshot(self.us, self.dk, 'dk')['ticker_count'], 13)

    @unittest.skipUnless(importlib.util.find_spec('flask'), 'Flask is unavailable in the offline test container')
    def test_api_must_require_password_and_public_stays_sanitized(self):
        from app import app
        os.environ.update({'DASHBOARD_PASSWORD':'demo-test-password',
                           'GITHUB_TOKEN':'fake','GITHUB_REPOSITORY':'org/code',
                           'GITHUB_DATA_REPOSITORY':'org/data'})
        client = app.test_client()
        for route in ['/api/private/holdings/snapshot', '/api/private/holdings/analytics']:
            self.assertEqual(client.get(route).status_code,401)
        with patch('app._account_documents', return_value=(self.us,self.dk)), \
             patch('private_holdings._quote_prices',side_effect=self.quotes), \
             patch('account_public._quote_prices',side_effect=self.quotes):
            response = client.get('/api/private/holdings/snapshot',headers={'Authorization':'Bearer demo-test-password'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
            self.assertIn('market_value',response.get_json()['holdings'][0])
            response_public=client.get('/api/public/analytics/snapshot')
            # Public independently requests Yahoo quotes; mock matching data source.
            self.assertEqual(response_public.status_code, 200)
            public_text=response_public.get_data(as_text=True)
            self.assertNotIn('"quantity"',public_text)
            self.assertNotIn('"market_value"',public_text)
            self.assertNotIn('"cost_basis"',public_text)


if __name__ == '__main__':
    unittest.main()
