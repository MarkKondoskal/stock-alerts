"""Regression tests for public + private sentiment feature (offline)."""
import csv
import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

WEB = Path(__file__).resolve().parents[1] / 'web'
sys.path.insert(0, str(WEB))
import sentiment_data as sd

class TestSentiment(unittest.TestCase):
    def setUp(self):
        sd._CACHE.clear()

    def test_index_levels_are_not_inflation_percentages(self):
        points = [(f'2025-{month:02d}-01',100+month) for month in range(1,13)] + [('2026-01-01',114)]
        row = sd._economic_item('CPIAUCSL','CPI inflation','Inflation', points, '% YoY', 'yoy', 2)
        self.assertAlmostEqual(row['value'], 114/101*100-100, places=2)
        self.assertNotEqual(row['value'],114)
        self.assertEqual(row['period'],'2026-01-01')

    def test_no_wrong_yoy_if_missing_month(self):
        points=[('2025-01-01',100),('2025-02-01',101),('2026-02-01',109)]
        self.assertEqual(sd._economic_item('PCEPI','PCE','Inflation',points,'% YoY','yoy',2)['value'],7.92)
        self.assertIsNone(sd._economic_item('PCEPI','PCE','Inflation',[('2025-01-01', 100),('2026-02-01', 110)],'% YoY','yoy',2))

    def test_jobs_change_not_payroll_total(self):
        row = sd._economic_item('PAYEMS','Payrolls','Jobs',[('2026-01-01',160000),('2026-02-01',160138)],'K jobs','difference',0)
        self.assertEqual(row['value'],138)
        self.assertEqual(row['unit'],'K jobs')

    def test_fed_range_uses_matching_observation_dates(self):
        data={'DFEDTARL':[('2026-10-22',3.5),('2026-10-23',3.5)],'DFEDTARU':[('2026-10-23',3.75)]}
        report = next(x for x in sd._economic_rows(data) if x['title']=='Fed target rate')
        self.assertEqual(report['lower'], 3.5)
        self.assertEqual(report['value'],3.75)

    def test_fred_csv_fallback_with_no_api_key(self):
        class Response:
            text = 'observation_date,CPIAUCSL\n2026-01-01,321.2\n2026-02-01,.\n2026-03-01,325.2\n'
            def raise_for_status(self): pass
        with patch.dict(os.environ, {'FRED_API_KEY':''}), patch.object(sd.requests,'get', return_value=Response()) as mocked:
            points=sd._fred_points('CPIAUCSL')
            self.assertEqual(points, [('2026-01-01',321.2),('2026-03-01',325.2)])
            self.assertEqual(mocked.call_args.kwargs['params']['id'],'CPIAUCSL')
            self.assertNotIn('api_key',mocked.call_args.kwargs['params'])

    def test_fred_series_whitelist(self):
        with self.assertRaises(ValueError): sd._fred_points('NOPE')

    def test_provider_error_returns_unavailable_not_fake_value(self):
        from requests import Timeout
        with patch.dict(os.environ, {'FRED_API_KEY': ''}), \
             patch.object(sd, '_fetch_vix', side_effect=Timeout('blocked')), \
             patch.object(sd, '_fetch_fear_greed', side_effect=Timeout('blocked')), \
             patch.object(sd, '_fred_bulk_csv', side_effect=Timeout('blocked')), \
             patch.object(sd, '_economic_alert_fallback', return_value=[]):
            payload=sd.get_sentiment_dashboard()
        self.assertIsNone(payload['vix'])
        self.assertIsNone(payload['fear_greed'])
        self.assertEqual(payload['reports'],[])
        self.assertNotIn('GITHUB_TOKEN',str(payload))

    def test_user_interfaces_and_endpoint_exist(self):
        public=(WEB/'static/public.html').read_text()
        private=(WEB/'static/index.html').read_text()
        api=(WEB/'app.py').read_text()
        self.assertIn('id="sentimentTab"',public)
        self.assertIn('id="sentimentPanel"',public)
        self.assertIn('data-tab="sentiment"',private)
        self.assertIn('id="sentiment-private"',private)
        self.assertIn('@app.get("/api/public/sentiment")',api)
        self.assertIn('sentiment_ui.js',public)
        self.assertIn('sentiment_ui.js',private)

if __name__ == '__main__': unittest.main()
