import os
from pathlib import Path
import sys
import unittest
from datetime import date, datetime, timezone
from unittest.mock import Mock, patch

import requests
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'web'))

from account_public import _select_period
from performance_files import read_history
from app import app
from economic_calendar import fomc_actual, parse_rows
from system_health import summarize
from trade_manager import correct_trade, record_trade


class StockUpgrades(unittest.TestCase):
    def trade(self, **changes):
        return dict({'account': 'us', 'action': 'BUY', 'ticker': 'ABC',
                     'date': '2025-10-17', 'quantity': '10', 'price': '10',
                     'fee': '5', 'currency': 'USD', 'client_trade_id': str(uuid4())}, **changes)

    def test_buy_sell_split_and_replay(self):
        for account, currency in (('us', 'USD'), ('dk', 'DKK')):
            with self.subTest(account=account):
                buy = self.trade(account=account, currency=currency, ticker='ABC.CO' if account == 'dk' else 'ABC')
                start = {'positions': [], 'transactions': [], 'positions_as_of': '2025-10-16'}
                data, initial = record_trade(start, buy)
                split = self.trade(**{**buy, 'action': 'SPLIT', 'quantity': '2', 'fee': '0',
                                      'client_trade_id': str(uuid4()), 'date': '2025-10-20'})
                data, _ = record_trade(data, split)
                self.assertEqual(data['positions'][0]['average_cost_per_share'], 5.25)
                sell = self.trade(**{**buy, 'action': 'SELL', 'quantity': '4', 'price': '8',
                                     'fee': '2', 'client_trade_id': str(uuid4()), 'date': '2025-10-21'})
                data, event = record_trade(data, sell)
                self.assertEqual(event['realized_gain_in_quote_currency'], 9)
                self.assertEqual(data['positions'][0]['quantity'], 16)
                correction = self.trade(**{**buy, 'fee': '15', 'client_trade_id': str(uuid4()),
                                           'corrects': initial['event_id']})
                data, replacement = correct_trade(data, correction)
                self.assertEqual(data['transactions'][-1]['realized_gain_in_quote_currency'], 7)
                self.assertEqual(data['trade_audit'][0]['superseded_by'], replacement['event_id'])
                self.assertEqual(start['positions'], [])

    def test_duplicate_and_conflicting_retry(self):
        body = self.trade()
        data, event = record_trade({'positions': [], 'transactions': []}, body)
        with self.assertRaisesRegex(ValueError, 'Matching'):
            record_trade(data, {**body, 'client_trade_id': str(uuid4())})
        env = dict(DASHBOARD_PASSWORD='secret', GITHUB_TOKEN='token',
                   GITHUB_REPOSITORY='example/code', GITHUB_DATA_REPOSITORY='example/private')
        with patch.dict(os.environ, env), patch('app.get_file', return_value=(data, 'sha')), patch('app.requests.put') as put:
            client = app.test_client()
            headers = {'Authorization': 'Bearer secret'}
            self.assertEqual(client.get('/api/private/system-health').status_code, 401)
            self.assertEqual(client.post('/api/private/trades', json=body).status_code, 401)
            retry = client.post('/api/private/trades', json=body, headers=headers)
            self.assertEqual(retry.json['event_id'], event['event_id'])
            self.assertTrue(retry.json['already_recorded'])
            conflict = client.post('/api/private/trades', json={**body, 'price': '11'}, headers=headers)
            self.assertEqual(conflict.status_code, 409)
            put.assert_not_called()

    def test_legacy_history_fallback_only_for_missing_file(self):
        path = 'portfolio/performance/merrill_history_provisional.csv'
        for status in (404, 403):
            fetch = Mock(side_effect=[
                requests.HTTPError(response=Mock(status_code=status)), 'old history',
            ])
            if status == 404:
                self.assertEqual(read_history(path, fetch), 'old history')
                fetch.assert_called_with('portfolio/performance/merrill_2026_ytd_provisional.csv')
            else:
                with self.assertRaises(requests.HTTPError):
                    read_history(path, fetch)
                fetch.assert_called_once_with(path)

    def test_ytd_uses_previous_year_close_across_new_year(self):
        rows = [('2026-12-29', 12, 6), ('2026-12-30', 20, 10),
                ('2027-01-04', 26, 12.2)]
        result = _select_period(rows, 'YTD', today=date(2027, 1, 4))
        self.assertEqual(result, [
            {'date': '2026-12-30', 'portfolio': 0, 'spy': 0},
            {'date': '2027-01-04', 'portfolio': 5, 'spy': 2},
        ])
        self.assertEqual(_select_period(rows[:2], 'YTD', today=date(2027, 1, 1)), [])

    def test_calendar_uses_release_and_reference_dates_separately(self):
        jobs = ['Friday, November 06, 2026 08:30 AM Employment Situation for October 2026']
        self.assertEqual(len(list(parse_rows(jobs, 2026, 'bls'))), 2)
        gdp = ['November 25 8:30 AM News GDP (Second Estimate) and Corporate Profits, 3rd Quarter 2026']
        self.assertEqual(list(parse_rows(gdp, 2026, 'bea'))[0][2:], ('2026-07-01', 'Second'))
        response = Mock(text='<p>maintain the target range for the federal funds rate at 3-3/4 to 4 percent</p>')
        with patch('economic_calendar.requests.get', return_value=response):
            self.assertEqual(fomc_actual(datetime(2026, 10, 28).date()), '3.75\u20134%')

    def test_failed_run_keeps_last_success_and_flags_staleness(self):
        items = [{'status': 'completed', 'conclusion': 'failure'},
                 {'status': 'completed', 'conclusion': 'success', 'updated_at': '2026-11-01T12:00:00Z'}]
        status = summarize(items, datetime(2026, 11, 3, tzinfo=timezone.utc), 24)
        self.assertTrue(status['failed'])
        self.assertTrue(status['stale'])
        self.assertEqual(status['last_success_at'], items[1]['updated_at'])
