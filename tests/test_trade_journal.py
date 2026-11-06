import base64
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'web'))

from app import app
from private_holdings import realized_summary
from trade_journal import journal_trades


class TradeJournalTest(unittest.TestCase):
    def test_public_projection_and_private_update(self):
        first = dict(ticker='ABC', date='2026-10-20', action='BUY', quantity=7, price_usd=321)
        second = dict(ticker='XYZ', date='2026-10-21', action='SELL', event_id='private-id',
                      journal={'note': 'Private note', 'published': False})
        account = {'transactions': [first, second]}
        key = next(journal_trades(account))[0]
        body = {'account': 'us', 'trade_id': key, 'note': 'Thesis intact.', 'published': True}
        headers = {'Authorization': 'Bearer secret'}
        with patch.dict(os.environ, dict(DASHBOARD_PASSWORD='secret', GITHUB_TOKEN='token',
                                         GITHUB_REPOSITORY='example/code', GITHUB_DATA_REPOSITORY='example/private')), \
             patch('app.get_file', return_value=(account, 'original-sha')), \
             patch('app._account_documents', return_value=(account, {})), patch('app.requests.put') as put:
            client = app.test_client()
            self.assertEqual(client.patch('/api/private/trades/journal', json=body).status_code, 401)
            self.assertEqual(client.get('/api/public/trade-activity').json, {'trades': []})
            put.return_value.status_code = 200
            self.assertEqual(client.patch('/api/private/trades/journal', json=body, headers=headers).status_code, 200)
            write = put.call_args.kwargs['json']
            self.assertEqual(write['sha'], 'original-sha')
            self.assertEqual(json.loads(base64.b64decode(write['content']))['transactions'][0]['quantity'], 7)
            response = client.get('/api/public/trade-activity')
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertEqual(response.json, {'trades': [{'date': '2026-10-20', 'ticker': 'ABC',
                                                          'action': 'BUY', 'note': 'Thesis intact.'}]})
            self.assertEqual(next(journal_trades(account))[0], key)
            client.patch('/api/private/trades/journal', json={**body, 'published': False}, headers=headers)
            self.assertEqual(client.get('/api/public/trade-activity').json, {'trades': []})

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
