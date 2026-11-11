import unittest
from unittest.mock import patch
from types import SimpleNamespace
from alerts import stock_alert
import account_public
import public_cache


class Followup(unittest.TestCase):
    def test_empty_watchlist_is_successful_noop(self):
        with patch.object(stock_alert, 'load_watchlist', return_value={}):
            self.assertTrue(stock_alert.check_prices())

    def test_missing_session_is_not_success(self):
        with patch.object(stock_alert, 'load_watchlist', return_value={'X': {'price_targets': [90], 'valuation_targets': {}}}), patch.object(stock_alert.yf, 'Tickers', create=True, return_value=SimpleNamespace(tickers={'X': object()})), patch.object(stock_alert, 'session_prices', return_value=(None, None)):
            self.assertFalse(stock_alert.check_prices())

    def test_gainers_require_common_end(self):
        history = {'X': {'2026-10-07': 100, '2026-11-06': 110},
                   'OLD': {'2026-09-01': 100, '2026-10-01': 120}}
        with patch.object(account_public, '_market_history', return_value=history):
            rows = account_public._gainers([{'ticker': 'X'}, {'ticker': 'OLD'}], '1M')
        self.assertEqual([r['ticker'] for r in rows], ['X'])
        self.assertEqual(rows[0]['through'], '2026-11-06')

    def test_cache_is_bounded_in_time_and_invalidated(self):
        public_cache.clear()
        with patch.object(public_cache, 'monotonic', return_value=0), patch('builtins.input', return_value={'value': 1}) as build:
            public_cache.cached('x', build)['value'] = 99
            self.assertEqual(public_cache.cached('x', build)['value'], 1)
            self.assertEqual(build.call_count, 1)
            public_cache.clear()
            public_cache.cached('x', build)
            self.assertEqual(build.call_count, 2)
        with patch.object(public_cache, 'monotonic', return_value=31):
            self.assertEqual(public_cache.cached('x', lambda: 2), 2)

    def test_transport_retry_and_permanent_failure(self):
        from alerts import publish_watchlist as publisher
        from unittest.mock import Mock
        with patch.object(publisher.requests, 'get', side_effect=[publisher.requests.Timeout(), Mock(status_code=200)]) as get, patch.object(publisher.time, 'sleep'):
            self.assertEqual(publisher.request_with_retry('get', 'https://example.invalid').status_code, 200)
            self.assertEqual(get.call_count, 2)
        with patch.object(publisher.requests, 'get', return_value=Mock(status_code=403)) as get:
            self.assertEqual(publisher.request_with_retry('get', 'https://example.invalid').status_code, 403)
            self.assertEqual(get.call_count, 1)
