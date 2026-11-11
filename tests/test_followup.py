from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from alerts import economic_alert, stock_alert
import account_public
import public_cache


class Followup(unittest.TestCase):
    def test_empty_watchlist_is_successful_noop(self):
        with patch.object(stock_alert, 'load_watchlist', return_value={}):
            self.assertTrue(stock_alert.check_prices())

    def test_missing_session_during_regular_hours_is_not_success(self):
        now = datetime(2026, 11, 11, 15, 30, tzinfo=timezone.utc)
        ticker = Mock()
        ticker.history.return_value = SimpleNamespace(
            empty=False, index=[now - timedelta(days=1)]
        )
        ticker.get_history_metadata.return_value = {
            'currentTradingPeriod': {
                'regular': {
                    'start': (now - timedelta(hours=1)).timestamp(),
                    'end': (now + timedelta(hours=5, minutes=30)).timestamp(),
                }
            }
        }
        watchlist = {'X': {'price_targets': [90], 'valuation_targets': {}}}
        with (
            patch.object(stock_alert, 'datetime') as clock,
            patch.object(stock_alert, 'load_watchlist', return_value=watchlist),
            patch.object(
                stock_alert.yf, 'Tickers',
                return_value=SimpleNamespace(tickers={'X': ticker}),
            ),
            patch.object(stock_alert, 'send_discord_alert') as send_alert,
            patch.object(stock_alert, 'save_watchlist') as save_watchlist,
        ):
            clock.now.return_value = now
            self.assertFalse(stock_alert.check_prices())
            send_alert.assert_not_called()
            save_watchlist.assert_not_called()

    def test_fomc_statement_parses_an_unchanged_fractional_range(self):
        path = '/newsevents/pressreleases/monetary20261028a.htm'
        url = f'https://www.federalreserve.gov{path}'
        index = Mock(text=f'<a href="{path}">FOMC statement</a>')
        statement = Mock(text='<p>The Committee decided to maintain the target range '
                              'for the federal funds rate at 3-3/4 to 4 percent.</p>')

        with patch.object(economic_alert.requests, 'get', side_effect=[index, statement]):
            result = economic_alert.fetch_latest_fomc_statement()

        self.assertEqual(result, {'date': '2026-10-28', 'lower': 3.75, 'upper': 4.0, 'url': url})

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
        with patch.object(publisher.requests, 'get', side_effect=[publisher.requests.Timeout(), Mock(status_code=200)]) as get, patch.object(publisher.time, 'sleep'):
            self.assertEqual(publisher.request_with_retry('get', 'https://example.invalid').status_code, 200)
            self.assertEqual(get.call_count, 2)
        with patch.object(publisher.requests, 'get', return_value=Mock(status_code=403)) as get:
            self.assertEqual(publisher.request_with_retry('get', 'https://example.invalid').status_code, 403)
            self.assertEqual(get.call_count, 1)
