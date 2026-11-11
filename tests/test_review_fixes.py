"""Offline regression coverage for the project review findings."""
import base64
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'web')]
import app
import account_public
from alerts import stock_alert, publish_watchlist
from watchlist_rules import validate_watchlist


def watch(prices):
    return {'X': {'price_targets': prices, 'valuation_targets': {}}}


class ReviewFixes(unittest.TestCase):
    def test_api_rejects_unsafe_tickers_and_targets_without_writing(self):
        env = dict(DASHBOARD_PASSWORD='test', GITHUB_TOKEN='mock',
                   GITHUB_REPOSITORY='test/code', GITHUB_DATA_REPOSITORY='test/data')
        headers = {'Authorization': 'Bearer test', 'If-Match': '"'+'a'*40+'"'}
        with patch.dict(os.environ, env), patch.object(app, 'put_file') as put:
            for value in ('Infinity', 'NaN', -1, 0, True, None):
                self.assertEqual(app.app.test_client().put('/api/watchlist', headers=headers,
                                 json=watch([value])).status_code, 400)
            self.assertEqual(app.app.test_client().put('/api/watchlist', headers=headers,
                             json={'<IMG SRC=X>': {}}).status_code, 400)
            put.assert_not_called()

    def test_legacy_rules_remain_supported(self):
        result = validate_watchlist({'ma': {'price': [100], 'valuation': {'PE': [20]}}})
        self.assertEqual(result['MA']['valuation_targets']['PE']['trim'], [20])

    def test_delivery_failure_is_failure_and_successful_removals_are_saved(self):
        fake = SimpleNamespace(tickers={'X': object()})
        with patch.object(stock_alert, 'load_watchlist', return_value=watch([90, 100])), \
             patch.object(stock_alert.yf, 'Tickers', return_value=fake, create=True), \
             patch.object(stock_alert, 'session_prices', return_value=(80, 79)), \
             patch.object(stock_alert, 'send_discord_alert', side_effect=[True, False]), \
             patch.object(stock_alert, 'save_watchlist') as save:
            self.assertFalse(stock_alert.check_prices())
            self.assertEqual(save.call_args.args[0], watch([100]))

    def test_valuation_fetch_failure_is_failure(self):
        ticker = Mock()
        ticker.get_info.side_effect = RuntimeError('offline')
        state = {'X': {'price_targets': [], 'valuation_targets': {'PE': {'buy': [20]}}}}
        with patch.object(stock_alert, 'load_watchlist', return_value=state), \
             patch.object(stock_alert.yf, 'Tickers', return_value=SimpleNamespace(tickers={'X': ticker}), create=True), \
             patch.object(stock_alert, 'session_prices', return_value=(80, 79)), \
             patch.object(stock_alert, 'save_watchlist') as save:
            self.assertFalse(stock_alert.check_prices())
            save.assert_not_called()

    def test_old_session_cannot_trigger_price_alert(self):
        ticker = Mock()
        ticker.history.return_value = SimpleNamespace(empty=False,
            index=[datetime.now(timezone.utc)-timedelta(days=1)])
        self.assertEqual(stock_alert.session_prices(ticker), (None, None))

    def test_ytd_uses_prior_year_close_not_download_buffer(self):
        year = date.today().year
        data = {'X': {f'{year-1}-12-20': 50, f'{year-1}-12-31': 100, f'{year}-01-02': 110}}
        with patch.object(account_public, '_market_history', return_value=data):
            self.assertEqual(account_public._gainers([{'ticker': 'X'}], 'YTD')[0]['return_pct'], 10)

    def test_month_requires_baseline_and_excludes_buffer(self):
        data = {'X': {'2026-09-20': 50, '2026-10-01': 100, '2026-10-31': 110},
                'NEW': {'2026-10-20': 50, '2026-10-31': 100}}
        with patch.object(account_public, '_market_history', return_value=data):
            self.assertEqual(account_public._gainers([{'ticker': 'X'}, {'ticker': 'NEW'}], '1M'),
                             [{'ticker': 'X', 'return_pct': 10, 'from': '2026-10-01', 'through': '2026-10-31'}])

    def test_old_quotes_are_excluded_and_dates_retained(self):
        today = date.today()
        data = {'X': {(today-timedelta(days=6)).isoformat(): 100},
                'Y': {(today-timedelta(days=1)).isoformat(): 50},
                'DKK=X': {today.isoformat(): 6.5}}
        with patch.object(account_public, '_load_history', return_value=data):
            prices, fx = account_public._quote_prices({'X', 'Y'})
        self.assertNotIn('X', prices)
        self.assertEqual(fx, 6.5)
        self.assertEqual(account_public.quote_metadata(prices)['stale_tickers'], ['X'])
        self.assertEqual(prices.dates['Y'], (today-timedelta(days=1)).isoformat())

    def test_concurrent_additions_survive_target_removal(self):
        merge = publish_watchlist.merge_changes
        self.assertEqual(merge(watch([90, 100]), watch([100]), watch([90, 100, 110])), watch([100, 110]))
        self.assertEqual(merge(watch([90]), {}, watch([90, 110])), watch([110]))
        self.assertEqual(merge(watch([90]), watch([90, 100]), {}), watch([100]))
        self.assertEqual(merge(watch([90]), {}, {}), {})

    def test_publish_reloads_and_merges_after_sha_conflict(self):
        def response(prices, sha):
            return Mock(json=lambda: {'sha': sha, 'content': base64.b64encode(json.dumps(watch(prices)).encode()).decode()})
        with patch.object(publish_watchlist.requests, 'get', side_effect=[response([90], 'a'), response([90, 110], 'b')]), \
             patch.object(publish_watchlist.requests, 'put', side_effect=[Mock(status_code=409), Mock(status_code=200)]) as put:
            publish_watchlist.publish(watch([90]), {}, 'test/data', 'main', 'mock')
        payload = put.call_args.kwargs['json']
        self.assertEqual(payload['sha'], 'b')
        self.assertEqual(json.loads(base64.b64decode(payload['content'])), watch([110]))
