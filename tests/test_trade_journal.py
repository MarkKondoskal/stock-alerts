import base64
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'web'))

from app import app
from private_holdings import private_snapshot, realized_summary
from trade_journal import journal_trades, public_activity
from trade_manager import record_trade


class TradeJournalTest(unittest.TestCase):
    def test_public_projection_and_private_update(self):
        first = dict(ticker='ABC', date='2026-10-20', action='BUY', quantity=7, price_usd=321)
        second = dict(ticker='XYZ', date='2026-10-21', action='SELL', event_id='private-id',
                      journal={'note': 'Private note', 'published': False})
        account = {'transactions': [first, second]}
        public_first = {'date': '2026-10-20', 'ticker': 'ABC', 'action': 'BUY', 'position_change': 'New holding', 'note': '', 'buy_price': 321, 'buy_currency': 'USD'}
        public_second = {'date': '2026-10-21', 'ticker': 'XYZ', 'action': 'SELL', 'position_change': None, 'note': ''}
        default_activity = {'trades': [public_second, public_first]}
        key = next(journal_trades(account))[0]
        body = {'account': 'us', 'trade_id': key, 'note': 'Thesis intact.', 'published': True}
        headers = {'Authorization': 'Bearer secret'}
        with patch.dict(os.environ, dict(DASHBOARD_PASSWORD='secret', GITHUB_TOKEN='token',
                                         GITHUB_REPOSITORY='example/code', GITHUB_DATA_REPOSITORY='example/private')), \
             patch('app.get_file', return_value=(account, 'original-sha')), \
             patch('app._account_documents', return_value=(account, {})), patch('app.requests.put') as put:
            client = app.test_client()
            self.assertEqual(client.patch('/api/private/trades/journal', json=body).status_code, 401)
            self.assertEqual(client.get('/api/public/trade-activity').json, default_activity)
            self.assertEqual(client.get('/api/public/trade-activity?account=us').json, default_activity)
            self.assertEqual(client.get('/api/public/trade-activity?account=dk').json, {'trades': []})
            self.assertEqual(client.get('/api/public/trade-activity?account=unknown').status_code, 400)
            put.return_value.status_code = 200
            self.assertEqual(client.patch('/api/private/trades/journal', json=body, headers=headers).status_code, 200)
            write = put.call_args.kwargs['json']
            self.assertEqual(write['sha'], 'original-sha')
            self.assertEqual(json.loads(base64.b64decode(write['content']))['transactions'][0]['quantity'], 7)
            response = client.get('/api/public/trade-activity')
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertEqual(response.json, {'trades': [public_second, {**public_first, 'note': 'Thesis intact.'}]})
            self.assertEqual(next(journal_trades(account))[0], key)
            client.patch('/api/private/trades/journal', json={**body, 'published': False}, headers=headers)
            self.assertEqual(client.get('/api/public/trade-activity').json, default_activity)

    def test_realized_summary_respects_currency_and_scope(self):
        us = {'transactions': [dict(action='SELL', ticker='ABC', realized_gain_in_quote_currency=20),
                               dict(action='SELL', ticker='VOO', realized_gain_in_quote_currency=8),
                               dict(action='SELL', ticker='DEF')]}
        dk = {'transactions': [dict(action='SELL', ticker='XYZ.CO', price_currency='DKK',
                                    realized_gain_in_quote_currency=-65)]}
        accounts = (('us', us), ('dk', dk))
        self.assertEqual(realized_summary(accounts, 'combined', 'USD', False, 6.5),
                         {'amount': 10, 'included': 2, 'missing': 1})
        self.assertEqual(realized_summary(accounts, 'us', 'DKK', True, 6.5),
                         {'amount': 182, 'included': 2, 'missing': 1})

    def test_new_trade_is_public_but_its_note_requires_sharing(self):
        source = {'positions': [], 'transactions': []}
        account, event = record_trade(source, {
            'account': 'us', 'action': 'BUY', 'ticker': 'ABC',
            'date': '2025-10-17', 'quantity': 4, 'price': 25, 'currency': 'USD',
        })
        public = {'date': '2025-10-17', 'ticker': 'ABC', 'action': 'BUY', 'position_change': 'New holding', 'note': ''}
        public.update(buy_price=25, buy_currency='USD')
        self.assertEqual(public_activity([account]), [public])
        event['journal'] = {'note': 'My reason', 'published': False}
        self.assertEqual(public_activity([account]), [public])
        event['journal']['published'] = True
        self.assertEqual(public_activity([account]), [{**public, 'note': 'My reason'}])

    def test_private_dashboard_document_is_not_cached(self):
        response = app.test_client().get('/')
        with response:
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertIn('id="private-realized"', response.get_data(as_text=True))

    def test_nordnet_cash_basis_realized_and_total(self):
        def trade(day, action, qty, cash):
            return dict(trade_date=day, action=action, ticker='ABC', quantity=qty,
                        net_cash_movement_dkk=cash, price_currency='DKK')
        dk = {'transactions': [
            trade('2025-01-01', 'BUY', 5, -100),
            trade('2025-01-02', 'SELL', 5, 130),
            trade('2025-01-03', 'BUY', 2, -40),
        ], 'positions': [{'ticker': 'ABC', 'quantity': 2,
                          'average_cost_per_share': 20, 'cost_currency': 'DKK'}]}
        with patch('private_holdings._quote_prices', return_value=({'ABC': 10}, 6.5)):
            result = private_snapshot({}, dk, 'dk', 'DKK')
        self.assertEqual(result['realized'], {'amount': 30, 'included': 1, 'missing': 0})
        self.assertEqual(result['total_pl'], result['unrealized_pl'] + 30)
        self.assertFalse(result['total_pl_partial'])
        dk['transactions'][0]['net_cash_movement_dkk'] = None
        self.assertEqual(realized_summary((('dk', dk),), 'dk', 'DKK', True, 6.5),
                         {'amount': None, 'included': 0, 'missing': 1})

    def test_public_position_change_bands_and_reopening(self):
        events = [
            ('BUY', 4), ('BUY', 3), ('SPLIT', 7), ('SELL', 7), ('SELL', 7), ('BUY', 2),
        ]
        trades = [dict(date=f'2025-01-0{i}', ticker='XYZ', action=action, quantity=units, split_ratio=2)
                  for i, (action, units) in enumerate(events, 1)]
        activity = public_activity([{'transactions': trades}])
        self.assertEqual([row['position_change'] for row in activity], [
            'New holding', 'Closed position', 'Reduced position by 50–100%',
            'Increased position by 50–100%', 'New holding',
        ])
        self.assertNotIn('quantity', activity[0])
