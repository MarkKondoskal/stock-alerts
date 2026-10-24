"""Offline regression checks for alert delivery and state handling.

Run from repository root: python -m unittest discover -s tests -v
All external calls are mocked; no market or Discord requests are made.
"""
import importlib
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    import yfinance  # noqa: F401
except ImportError:
    sys.modules['yfinance'] = types.ModuleType('yfinance')

from alerts import economic_alert, sentiment_alert, stock_alert, watchlist_manager


class BugfixRegressionTests(unittest.TestCase):
    def test_fred_index_units(self):
        self.assertEqual(economic_alert.format_fred_value('CPIAUCSL', 336.298), '336.298')
        self.assertEqual(economic_alert.format_fred_value('PCEPI', 120.15), '120.150')
        self.assertEqual(economic_alert.format_fred_value('UNRATE', 4.5), '4.50%')

    def test_failed_fear_greed_delivery_preserves_state(self):
        state = {'vix': {}, 'fear_greed_state': 'normal', 'vix_last_price': None}
        with patch.object(sentiment_alert, 'load_state', return_value=state), \
             patch.object(sentiment_alert, 'save_state'), \
             patch.object(sentiment_alert, 'send_discord_sentiment_alert', return_value=False), \
             patch.object(sentiment_alert.requests, 'get') as get:
            get.return_value.json.return_value = {'fear_and_greed': {'score': 15, 'rating': 'Extreme Fear'}}
            sentiment_alert.check_fear_and_greed()
            self.assertEqual(state['fear_greed_state'], 'normal')

    def test_second_alert_network_error_keeps_only_undelivered_price_target(self):
        state = {'X': {'price_targets': [90, 110], 'valuation_targets': {}}}
        ticker = types.SimpleNamespace(fast_info=types.SimpleNamespace(last_price=80, day_low=80))
        response = Mock(status_code=204)
        with patch.object(stock_alert, 'load_watchlist', return_value=state), \
             patch.object(stock_alert, 'save_watchlist') as saver, \
             patch.object(stock_alert.yf, 'Tickers', create=True,
                          return_value=types.SimpleNamespace(tickers={'X': ticker})), \
             patch.object(stock_alert.requests, 'post', side_effect=[response,
                          stock_alert.requests.RequestException('network down')]), \
             patch.object(stock_alert, 'DISCORD_WEBHOOK_URL', 'https://example.invalid/webhook'):
            stock_alert.check_prices()
            self.assertEqual(saver.call_args.args[0]['X']['price_targets'], [110])

    def test_failed_watchlist_save_raises_and_leaves_original_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = Path(tmp) / 'watchlist.json'
            original.write_text('{"X": {"price_targets": [90]}}', encoding='utf-8')
            with patch.object(stock_alert, 'WATCHLIST_FILE', str(original)), \
                 patch.object(stock_alert.os, 'replace', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    stock_alert.save_watchlist({'X': {'price_targets': []}})
            self.assertIn('[90]', original.read_text(encoding='utf-8'))
            self.assertEqual(list(Path(tmp).glob('*.tmp')), [])

    def test_status_discord_failure_exits_nonzero(self):
        with patch.object(watchlist_manager, 'send_watchlist_to_discord', return_value=False), \
             patch.object(sys, 'argv', ['watchlist_manager.py', 'STATUS', '', '', 'PRICE', 'TRIM']):
            with self.assertRaises(SystemExit) as exc:
                watchlist_manager.main()
            self.assertEqual(exc.exception.code, 1)


if __name__ == '__main__':
    unittest.main()
