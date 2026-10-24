"""Offline smoke tests for the public/private transaction integration release."""
import json
import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'web'))
sys.path.insert(0, str(BASE / 'alerts'))
from trade_manager import record_trade

if 'yfinance' not in sys.modules:
    sys.modules['yfinance'] = types.ModuleType('yfinance')
from watchlist_manager import _make_embeds, _compact_targets


class WatchlistCompactLayout(unittest.TestCase):
    def test_one_line_per_ticker_and_preserves_full_rules(self):
        rows = [
            ['ASTOR.NGM','$23.40','$12','—','—','436.3x','+2266.6%'],
            ['AMZN','$248.00','$180','20.0x','23.8x','3.4x','+19.2%'],
        ]
        details = ['`ASTOR.NGM` · $12, FxPE trim≥30x, P/S buy≤15x']
        embeds = _make_embeds(rows, len(rows), details)
        self.assertEqual(len(embeds), 2)
        self.assertIn('P/E', embeds[0]['description'])
        self.assertIn('FPE', embeds[0]['description'])
        self.assertIn('YoY', embeds[0]['description'])
        table = embeds[0]['description'].split('```text\n', 1)[1].split('\n```', 1)[0]
        self.assertEqual(len(table.splitlines()), 3)
        self.assertLessEqual(max(map(len,table.splitlines())), 68)
        self.assertIn('FxPE trim≥30x', embeds[1]['description'])
        self.assertEqual(_compact_targets(['$310','$315']), '$310,$315')
        self.assertTrue(len(_compact_targets(['$120.50','$105.25','$100'])) <= 12)


class PrivateTradeTests(unittest.TestCase):
    def test_both_broker_ledgers_can_record_future_trades(self):
        # Real private data repo isn't distributed in this public patch.
        sample = {'positions_as_of':'2026-10-22',
                  'positions':[{'ticker':'MSFT','quantity':4,'average_cost_per_share':300,'cost_currency':'USD'}],
                  'transactions': []}
        base = {'account':'us','action':'BUY','ticker':'MSFT','date':'2026-10-23',
                'quantity':'1','price':'420','currency':'USD','client_trade_id':str(uuid.uuid4())}
        result,event=record_trade(sample,base)
        self.assertEqual(result['positions'][0]['quantity'],5)
        self.assertEqual(event['event_id'],base['client_trade_id'])
        self.assertAlmostEqual(result['positions'][0]['average_cost_per_share'],324)
        with self.assertRaisesRegex(ValueError,'already recorded'):
            record_trade(result,base)
        with self.assertRaisesRegex(ValueError,'Cannot sell'):
            record_trade(sample,{**base,'action':'SELL','quantity':100,'client_trade_id':str(uuid.uuid4())})

    def test_nordnet_currency_validation(self):
        source={'positions_as_of':'2026-10-15','positions':[{'ticker':'AMZN','quantity':11,
               'average_cost_per_share':200,'cost_currency':'USD'}],'transactions':[]}
        trade={'account':'dk','action':'BUY','ticker':'AMZN','date':'2026-10-23',
               'quantity':1,'price':250,'currency':'USD'}
        result,event=record_trade(source,trade)
        self.assertEqual(event['price_currency'],'USD')
        self.assertEqual(result['positions'][0]['quantity'],12)
        with self.assertRaisesRegex(ValueError,'currency'):
            record_trade(source,{**trade,'currency':'DKK'})


if __name__=='__main__':unittest.main()
