"""Offline integration tests for prepared data, proximity, and alert persistence."""
import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'web')]
import app
from alerts import alert_history, publish_dashboard_data, prepare_dashboard
from prepared import digest, select, pack, unpack
from watchlist_market import enrich, quote


class DashboardAdditions(unittest.TestCase):
    def test_directional_proximity_and_missing_metrics(self):
        targets = {'price_targets': [80], 'valuation_targets': {'PE': {'buy': [20], 'trim': [40]}}}
        result = enrich(targets, {'price': 100, 'valuations': {'PE': 25}})
        self.assertEqual([r['change_pct'] for r in result['proximity']], [-20, -20, 60])
        self.assertTrue(all(r['met'] is False for r in result['proximity']))
        self.assertTrue(enrich(targets, {'price': 70})['proximity'][0]['met'])
        self.assertIsNone(enrich(targets)['proximity'][0]['change_pct'])

    def test_quote_preserves_currency_and_observation_time(self):
        result = quote({'currentPrice': 400, 'currency': 'DKK', 'regularMarketTime': 1800000000,
                        'forwardPE': -1, 'trailingPE': float('nan')}, datetime.now(timezone.utc).isoformat())
        self.assertEqual(result['currency'], 'DKK')
        self.assertIsNotNone(result['price_as_of'])
        self.assertIsNone(result['valuations']['PE'])
        self.assertIsNone(result['valuations']['FxPE'])

    def test_journal_records_intent_before_delivery_and_acceptance_after(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'STOCKALERTS_ALERT_HISTORY_FILE': str(Path(tmp)/'events.json')}):
            def send():
                rows = json.loads((Path(tmp)/'events.json').read_text())
                self.assertEqual(rows[0]['status'], 'pending')
                return True
            self.assertTrue(alert_history.deliver(send, ticker='X', metric='PRICE', direction='buy', target=10, actual=9))
            self.assertEqual(json.loads((Path(tmp)/'events.json').read_text())[0]['status'], 'accepted')

    def test_uncertain_delivery_preserves_attempt(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'STOCKALERTS_ALERT_HISTORY_FILE': str(Path(tmp)/'events.json')}):
            with self.assertRaises(TimeoutError):
                alert_history.deliver(Mock(side_effect=TimeoutError()), ticker='X', metric='PE', direction='trim', target=30, actual=31)
            self.assertEqual(json.loads((Path(tmp)/'events.json').read_text())[0]['status'], 'unknown')

    def test_history_merge_is_idempotent_and_keeps_other_attempts(self):
        first = {'id': 'a', 'created_at': '1', 'updated_at': '1', 'status': 'pending'}
        accepted = {**first, 'updated_at': '2', 'status': 'accepted'}
        other = {'id': 'b', 'created_at': '2', 'updated_at': '2', 'status': 'accepted'}
        merged = publish_dashboard_data.merge_history([first, other], [accepted])
        self.assertEqual(merged, [accepted, other])
        self.assertEqual(publish_dashboard_data.merge_history(merged, [first]), merged)

    def test_first_history_publish_and_conflict_retry(self):
        event = {'id': 'a', 'created_at': '1', 'updated_at': '1', 'status': 'accepted'}
        env = {'STOCKALERTS_DATA_REPOSITORY': 'test/private', 'STOCKALERTS_DATA_TOKEN': 'mock'}
        existing = Mock(status_code=200)
        existing.json.return_value = {'sha': 'new', 'content': base64.b64encode(b'[]').decode()}
        with patch.dict(os.environ, env), patch.object(publish_dashboard_data, 'request_with_retry',
                side_effect=[Mock(status_code=404), Mock(status_code=422), existing, Mock(status_code=200)]) as request:
            publish_dashboard_data.publish('alerts/alert_history.json', [event], history=True)
        self.assertEqual(request.call_args.kwargs['json']['sha'], 'new')

    def test_prepared_data_rejected_after_trade_or_when_expired(self):
        now = datetime(2026, 11, 10, 15, tzinfo=timezone.utc)
        us, dk = {'positions': []}, {'positions': []}
        bundle = {'schema': 1, 'generated_at': now.isoformat(), 'accounts': [digest(us), digest(dk)], 'public': {'key': {'holdings': []}}}
        self.assertEqual(select(bundle, 'public', 'key', us, dk, now), {'holdings': []})
        self.assertIsNone(select(bundle, 'public', 'key', {'positions': [1]}, dk, now))
        self.assertIsNone(select(bundle, 'public', 'key', us, dk, now+timedelta(hours=3)))
        self.assertEqual(unpack(pack(bundle)), bundle)

    def test_history_requires_auth_and_does_not_expose_extra_fields(self):
        env = dict(DASHBOARD_PASSWORD='test', GITHUB_TOKEN='fake', GITHUB_REPOSITORY='test/code', GITHUB_DATA_REPOSITORY='test/data')
        event = {'id': 'a', 'created_at': '2026-11-07', 'status': 'accepted', 'webhook': 'secret'}
        with patch.dict(os.environ, env), patch.object(app, 'get_file', return_value=([event], 'sha')):
            client = app.app.test_client()
            self.assertEqual(client.get('/api/private/alert-history').status_code, 401)
            response = client.get('/api/private/alert-history', headers={'Authorization': 'Bearer test'})
            self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
            self.assertNotIn('secret', response.get_data(as_text=True))

    def test_prepared_public_route_never_returns_private_section(self):
        us, dk = {'positions': []}, {'positions': []}
        bundle = {'schema': 1, 'generated_at': datetime.now(timezone.utc).isoformat(), 'accounts': [digest(us), digest(dk)],
                  'public': {'combined:USD:0': {'holdings': [], 'sectors': []}},
                  'private': {'combined:USD:0': {'quantity': 987654, 'market_value': 123456}}}
        with patch.object(app, '_account_documents', return_value=(us, dk)), patch.object(app, '_prepared_bundle', return_value=bundle), patch('account_public.snapshot', side_effect=AssertionError('Live fallback should not run')):
            response = app.app.test_client().get('/api/public/analytics/snapshot')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'holdings': [], 'sectors': []})

    def test_watchlist_has_targets_without_quotes_on_first_install(self):
        targets = {'X': {'price_targets': [10], 'valuation_targets': {}}}
        with patch.object(app, 'get_file', return_value=(targets, 'sha')), patch.object(app, '_prepared_bundle', return_value={}):
            response = app.app.test_client().get('/api/public/watchlist-market')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['X']['price_targets'], [10])
        self.assertIsNone(response.json['X']['proximity'][0]['change_pct'])

    def test_generator_builds_all_modes_from_one_history_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkout = Path(tmp)
            (checkout/'portfolio/performance').mkdir(parents=True)
            (checkout/'alerts').mkdir()
            for name in ('merrill', 'nordnet'):
                (checkout/f'portfolio/{name}_portfolio.json').write_text((ROOT/f'tests/fixtures/{name}_portfolio.json').read_text())
            (checkout/'alerts/watchlist.json').write_text('{"AMZN":{"price_targets":[100],"valuation_targets":{}}}')
            csv = 'date,portfolio_pct,spy_usd_pct,spy_dkk_pct,portfolio_usd_pct,portfolio_dkk_pct\n2025-12-31,0,0,0,0,0\n2026-11-06,10,5,5,10,10\n'
            for name in ('nordnet_all_available', 'merrill_history', 'merrill_no_etf_history', 'combined_history', 'combined_no_etf_history'):
                (checkout/f'portfolio/performance/{name}_provisional.csv').write_text(csv)
            recent = datetime.now(timezone.utc).date().isoformat()
            history = {ticker: {'2025-12-31': value, recent: value} for ticker, value in [('AMZN', 190), ('VOO', 500), ('NOVO-B.CO', 450), ('DKK=X', 6.5), ('SPY', 600)]}
            with patch.object(prepare_dashboard.account_public, '_load_history', return_value=history) as load, patch('yfinance.Ticker', create=True) as ticker:
                ticker.return_value.get_info.return_value = {'currentPrice': 190, 'currency': 'USD'}
                bundle = prepare_dashboard.build(checkout)
            self.assertEqual(load.call_count, 1)
            self.assertEqual(len(bundle['analytics']), 108)
            self.assertEqual(len(bundle['private']), 12)
            self.assertLess(len(json.dumps(pack(bundle))), 900000)
