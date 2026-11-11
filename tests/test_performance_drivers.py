import csv
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'web'))
from performance_drivers import drivers
import app


def csv_data(rows):
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=['previous_date','date','currency','market_move','fraction'])
    writer.writeheader()
    for previous, day, currency, fractions in rows:
        writer.writerow(dict(previous_date=previous,date=day,currency=currency,
                             market_move=json.dumps({'PRIVATE':987654321}),fraction=json.dumps(fractions)))
    return stream.getvalue()


class DriversTests(unittest.TestCase):
    def setUp(self):
        self.points = [{'date':'2026-01-01','value':0}, {'date':'2026-01-02','value':10},
                       {'date':'2026-01-03','value':21}]
        self.text = csv_data([('2026-01-01','2026-01-02','USD',{'SOLD':.1}),
                              ('2026-01-02','2026-01-03','USD',{'HELD':.1}),
                              ('2026-01-01','2026-01-02','DKK',{'WRONG':.5})])

    def test_linked_contributions_include_sold_positions_without_private_amounts(self):
        result = drivers(self.points,'combined','USD',False,lambda _:self.text)
        rows = {row['ticker']:row['contribution_pp'] for row in result['drivers']}
        self.assertEqual(rows, {'SOLD':10,'HELD':11})
        self.assertEqual(result['drivers_total_pp'],21)
        self.assertNotIn('987654321',json.dumps(result))
        self.assertNotIn('market_move_amount',json.dumps(result))

    def test_missing_interval_hides_incomplete_contribution(self):
        result = drivers(self.points[::2],'us','USD',True,lambda _:self.text)
        self.assertEqual(result['drivers'],[])

    def test_non_reconciling_data_is_not_presented_as_valid(self):
        result = drivers([self.points[0],self.points[1],{**self.points[2],'value':30}],
                         'us','USD',True,lambda _:self.text)
        self.assertEqual(result['drivers'],[])
        self.assertIn('do not reconcile',result['drivers_note'])

    def test_modes_use_account_currency_and_etf_filter(self):
        for account in ('combined','us','dk'):
            for etfs in (True,False):
                paths=[]
                def read(path):paths.append(path);return self.text
                drivers(self.points,account,'USD',etfs,read)
                self.assertEqual(paths,[f'portfolio/performance/attribution_{account}{"" if etfs else "_excluded"}.csv'])

    def test_unavailable_input_does_not_break_analytics(self):
        with patch('builtins.input',side_effect=OSError('missing')) as read:
            self.assertEqual(drivers(self.points,'us','USD',False,read)['drivers'],[])

    def test_prepared_compatibility_enrichment_uses_matching_period_only(self):
        with patch.object(app,'_prepared_bundle',return_value={}), \
             patch('prepared.select',return_value={'performance':self.points,'spy':[], 'private_value':12345}), \
             patch.object(app,'_private_csv',return_value=self.text):
            result=app._prepared_result('analytics','combined:USD:0:1M',{}, {})
        self.assertEqual(result['drivers_total_pp'],21)
        self.assertNotIn('private_value',result)
