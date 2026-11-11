from datetime import datetime
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'web'))

from intraday_performance import build_series


class IntradayPerformanceTest(unittest.TestCase):
    def test_combined_dkk_rebases_and_uses_last_danish_bar_after_close(self):
        start = '2026-11-11T15:55:00+00:00'
        late = '2026-11-11T19:00:00+00:00'
        now = datetime.fromisoformat(late)
        quotes = {
            'NOVO-B.CO': {start: 400},
            'AAA': {start: 100, late: 101},
            'SPY': {start: 500, late: 505},
            'DKK=X': {start: 6, late: 6.1},
        }
        result = build_series({'AAA': 2, 'NOVO-B.CO': 1}, 'DKK', quotes, now)
        self.assertEqual([point['value'] for point in result['performance']], [0, 2.0125])
        self.assertEqual([point['value'] for point in result['spy']], [0, 2.6833])
        self.assertEqual(result['oldest_quote_at'], start)

    def test_missing_stock_and_old_session_do_not_create_points(self):
        old = '2026-11-10T19:00:00+00:00'
        latest = '2026-11-11T19:00:00+00:00'
        result = build_series({'AAA': 1}, 'USD', {'SPY': {latest: 500}, 'AAA': {old: 100}},
                              datetime.fromisoformat(latest))
        self.assertEqual(result['performance'], [])
        self.assertIsNone(result['oldest_quote_at'])
