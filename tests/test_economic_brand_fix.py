"""Offline regression tests: economic-source fallback and public/private branding."""
import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import date, datetime, timezone

WEB = Path(__file__).resolve().parents[1] / 'web'
sys.path.insert(0, str(WEB))
import sentiment_data as sd

class TestEconomicsAndBranding(unittest.TestCase):
    def setUp(self):
        sd._CACHE.clear()

    def test_multiple_fred_series_use_one_public_csv_download(self):
        class Response:
            text = 'observation_date,CPIAUCSL,PAYEMS,UNRATE\n2026-08-01,333,159000,4.3\n2026-09-01,336,159044,4.2\n'
            def raise_for_status(self): pass
        with patch.object(sd.requests,'get',return_value=Response()) as mocked:
            result = sd._fred_bulk_csv()
        self.assertEqual(mocked.call_count, 1)
        self.assertIn('CPIAUCSL',mocked.call_args.kwargs['params']['id'])
        self.assertEqual(result['PAYEMS'][-1],('2026-09-01',159044))
        self.assertEqual(result['UNRATE'][-1][1],4.2)

    def test_fallback_only_exposes_true_units_and_flags_cache(self):
        now = date.today().replace(day=1).isoformat()
        state = {
            'CPIAUCSL':{'date':now, 'value':336.298},
            'PCEPI':{'date':now, 'value':131.579},
            'PAYEMS':{'date':now, 'value':159044.0},
            'UNRATE':{'date':now, 'value':4.2},
            'FED_FUNDS_TARGET_RANGE':{'date':now,'lower':3.5,'upper':3.75},
        }
        import json
        with patch.object(Path,'read_text',return_value=json.dumps(state)):
            rows=sd._economic_alert_fallback()
        d={r['id']:r for r in rows}
        self.assertEqual(d['CPIAUCSL']['unit'],'index')
        self.assertEqual(d['CPIAUCSL']['value'],336.298)
        self.assertEqual(d['PCEPI']['unit'],'index')
        self.assertEqual(d['PAYEMS']['unit'],'K employed')
        self.assertEqual(d['UNRATE']['unit'],'%')
        self.assertTrue(all(r['stale'] for r in rows))
        self.assertEqual(d['DFEDTARU']['lower'],3.5)

    def test_api_keeps_bot_cache_if_live_fred_unavailable(self):
        from requests import Timeout
        mockrow={'id':'UNRATE','title':'Unemployment rate','category':'Jobs','unit':'%', 'value':4.2,
                 'period':'2026-09-01','stale':True, 'source':'FRED (bot cache)'}
        with patch.dict(os.environ, {'FRED_API_KEY':''}), \
             patch.object(sd, '_fred_bulk_csv', side_effect=Timeout('blocked')), \
             patch.object(sd, '_economic_alert_fallback', return_value=[mockrow]), \
             patch.object(sd, '_fetch_vix', return_value={'value':19.45}), \
             patch.object(sd, '_fetch_fear_greed', return_value={'value':21}):
            out=sd.get_sentiment_dashboard()
        self.assertEqual(out['economic_data_status'],'cached')
        self.assertEqual(len(out['reports']),1)
        self.assertEqual(out['reports'][0]['value'],4.2)
        self.assertNotIn('GITHUB_TOKEN',str(out))

    def test_branding_is_consistent_and_pwa_logo_reused(self):
        public=(WEB/'static/public.html').read_text()
        private=(WEB/'static/index.html').read_text()
        self.assertIn('<h1>StockAlerts</h1>',public)
        self.assertIn('<b>StockAlerts</b>',private)
        self.assertNotIn('StockAlerts Core',private)
        self.assertNotIn('Portfolio Dashboard</h1>',public)
        self.assertIn('public-brand-logo',public)
        self.assertIn('brand-logo',private)
        self.assertTrue((WEB/'static/pwa/icon-192.png').is_file())

if __name__=='__main__': unittest.main()
