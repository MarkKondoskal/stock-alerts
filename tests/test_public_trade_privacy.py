"""Verify public projection exposes dates, not private account trade details."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'web'))
import account_public

class PublicProjectionPrivacy(unittest.TestCase):
    def test_snapshot_exposes_freshness_without_quantities_or_trades(self):
        us={'positions_as_of':'2026-10-23',
            'positions':[{'ticker':'MSFT','quantity':2,'cost_currency':'USD','average_cost_per_share':300}],
            'transactions':[{'ticker':'MSFT','price_usd':300,'quantity':2,'action':'BUY'}]}
        dk={'positions_as_of':'2026-10-22','positions':[],'transactions':[]}
        with patch.object(account_public,'_quote_prices',return_value=({'MSFT':400.0,'DKK=X':6.5},6.5)):
            data=account_public.snapshot(us,dk,'combined',include_etfs=False)
        self.assertEqual(data['positions_as_of'],{'us':'2026-10-23','dk':'2026-10-22'})
        self.assertEqual(len(data['holdings']),1)
        self.assertEqual(data['holdings'][0]['ticker'],'MSFT')
        encoded=json.dumps(data)
        for field in ('quantity','transactions','price_usd','market_value_private','cost_basis_private'):
            self.assertNotIn(field,encoded)

if __name__=='__main__':unittest.main()
