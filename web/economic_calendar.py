"""Official US release schedules with point-in-time ALFRED observations."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from functools import lru_cache
import os
import re
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ET = ZoneInfo('America/New_York')
BLS = 'https://www.bls.gov/schedule/{year}/home.htm'
BEA = 'https://www.bea.gov/news/schedule/'
FED = 'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm'
MONTH = r'(January|February|March|April|May|June|July|August|September|October|November|December)'
SERIES = {
    'CPI inflation (MoM)': ('CPIAUCSL', 'pch', '%'),
    'PCE inflation (MoM)': ('PCEPI', 'pch', '%'),
    'Nonfarm payrolls (MoM)': ('PAYEMS', 'chg', 'k jobs'),
    'Unemployment rate': ('UNRATE', 'lin', '%'),
    'Real GDP (annualized QoQ)': ('A191RL1Q225SBEA', 'lin', '%'),
    'FOMC target range': ('DFEDTARL', 'lin', '%'),
}
SEED = (
    ('2026-10-28', 'FOMC target range', '', ''),
    ('2026-10-29', 'PCE inflation (MoM)', '2026-09-01', ''),
    ('2026-10-29', 'Real GDP (annualized QoQ)', '2026-07-01', 'Advance'),
    ('2026-11-06', 'Nonfarm payrolls (MoM)', '2026-10-01', ''),
    ('2026-11-06', 'Unemployment rate', '2026-10-01', ''),
    ('2026-11-10', 'CPI inflation (MoM)', '2026-10-01', ''),
    ('2026-11-25', 'PCE inflation (MoM)', '2026-10-01', ''),
    ('2026-11-25', 'Real GDP (annualized QoQ)', '2026-07-01', 'Second'),
    ('2026-12-04', 'Nonfarm payrolls (MoM)', '2026-11-01', ''),
    ('2026-12-04', 'Unemployment rate', '2026-11-01', ''),
    ('2026-12-09', 'FOMC target range', '', ''),
    ('2026-12-10', 'CPI inflation (MoM)', '2026-11-01', ''),
    ('2026-12-23', 'PCE inflation (MoM)', '2026-11-01', ''),
    ('2026-12-23', 'Real GDP (annualized QoQ)', '2026-07-01', 'Third'),
    *((day, 'FOMC target range', '', '') for day in (
        '2027-01-27', '2027-03-17', '2027-04-28', '2027-06-09',
        '2027-07-28', '2027-09-15', '2027-10-27', '2027-12-08')),
)


def table_rows(url):
    response = requests.get(url, timeout=4, headers={'User-Agent': 'StockAlerts release calendar'})
    response.raise_for_status()
    return [' '.join(row.stripped_strings) for row in BeautifulSoup(response.text, 'html.parser').select('tr')]


def monthly(month, year):
    return datetime.strptime(f'{year} {month}', '%Y %B').date().isoformat()


def parse_rows(rows, year, agency):
    for row in rows:
        stamp = re.search(MONTH + r'\s+(\d{1,2}),?(?:\s+(\d{4}))?\s+0?8:30\s*(?:AM|a.m.)', row, re.I)
        if not stamp:
            continue
        month, day, release_year = stamp.groups()
        release = date.fromisoformat(monthly(month, release_year or year)).replace(day=int(day)).isoformat()
        month_release = re.search(
            r'(Consumer Price Index for|Employment Situation for|Personal Income and Outlays,)\s+'
            + MONTH + r'\s+(\d{4})', row, re.I)
        if month_release:
            name, reference_month, reference_year = month_release.groups()
            if agency == 'bea' and name.startswith('Personal'):
                names = ('PCE inflation (MoM)',)
            elif agency == 'bls' and name.startswith('Consumer'):
                names = ('CPI inflation (MoM)',)
            elif agency == 'bls' and name.startswith('Employment'):
                names = ('Nonfarm payrolls (MoM)', 'Unemployment rate')
            else:
                continue
            for name in names:
                yield release, name, monthly(reference_month, reference_year), ''
        elif agency == 'bea':
            gdp = re.search(r'\bGDP \((Advance|Second|Third) Estimate\).*?([1-4])(?:st|nd|rd|th) Quarter (\d{4})', row)
            if gdp:
                stage, quarter, ref_year = gdp.groups()
                yield release, 'Real GDP (annualized QoQ)', date(int(ref_year), int(quarter)*3-2, 1).isoformat(), stage


def observations(series, units, vintage, start, end, key):
    response = requests.get('https://api.stlouisfed.org/fred/series/observations', timeout=4, params={
        'series_id': series, 'units': units, 'api_key': key, 'file_type': 'json',
        'realtime_start': vintage.isoformat(), 'realtime_end': vintage.isoformat(),
        'observation_start': start.isoformat(), 'observation_end': end.isoformat(),
    })
    response.raise_for_status()
    return {date.fromisoformat(o['date']): float(o['value'])
            for o in response.json()['observations'] if o['value'] != '.'}


def statement_url(day):
    return 'https://www.federalreserve.gov/newsevents/pressreleases/monetary' + day.strftime('%Y%m%d') + 'a.htm'


def fomc_actual(day):
    from fractions import Fraction

    response = requests.get(statement_url(day), timeout=4)
    response.raise_for_status()
    text = ' '.join(BeautifulSoup(response.text, 'html.parser').stripped_strings)
    number = r'(\d+(?:\.\d+|[-– ]\d/\d)?)'
    match = re.search(r'target range for the federal funds rate.{0,150}?\b(?:at|to|of)\s+'
                      + number + r'\s+(?:to|through)\s+' + number + r'\s*percent',
                      text, re.I)
    if not match:
        return None

    def value(raw):
        pieces = re.split(r'[-– ]', raw)
        return float(pieces[0]) + (float(Fraction(pieces[1])) if len(pieces) > 1 else 0)

    return f'{value(match[1]):g}–{value(match[2]):g}%'


def has_vintage(series, day, key):
    response = requests.get('https://api.stlouisfed.org/fred/series/vintagedates', timeout=4, params={
        'series_id': series, 'api_key': key, 'file_type': 'json',
        'realtime_start': day.isoformat(), 'realtime_end': day.isoformat(),
    })
    response.raise_for_status()
    return day.isoformat() in response.json()['vintage_dates']


def readings(name, reference, release, stage, now):
    key = os.getenv('FRED_API_KEY')
    series, units, label = SERIES[name]
    day = release.date()
    yesterday = day - timedelta(days=1)
    vintage = min(yesterday, now.date())
    try:
        if not reference:
            actual = fomc_actual(day) if now >= release else None
            if not key:
                return None, actual
            values = [observations(series_id, units, vintage, vintage, vintage, key).get(vintage)
                      for series_id in (series, 'DFEDTARU')]
            previous = f'{values[0]:g}–{values[1]:g}%' if None not in values else None
            return previous, actual
        if not key:
            return None, None
        ref = date.fromisoformat(reference)
        prev = ref if stage in ('Second', 'Third') else (
            ref - timedelta(days=1 if not stage else 75)).replace(day=1)
        previous = observations(series, units, vintage, prev, prev, key).get(prev)
        actual = (observations(series, units, day, ref, ref, key).get(ref)
                  if now >= release and (stage not in ('Second', 'Third') or has_vintage(series, day, key)) else None)
        return tuple(f'{value:+.1f} {label}' if value is not None and label == 'k jobs'
                     else f'{value:.2f}%' if value is not None else None
                     for value in (previous, actual))
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return None, None


@lru_cache(maxsize=2)
def calendar(cache_bucket):
    now = datetime.now(ET)
    earliest, latest = now.date() - timedelta(days=35), now.date() + timedelta(days=45)
    events = {(n, r, s, d if n == 'FOMC target range' else ''): d for d, n, r, s in SEED}
    unavailable = []
    sources = [('bls', BLS.format(year=y), y) for y in range(earliest.year, latest.year + 1)]
    sources += [('bea', BEA + suffix, y) for y, suffix in
                ((now.year, 'full'), (now.year+1, 'next-year')) if y <= latest.year]
    for agency, url, year in sources:
        try:
            fetched = list(parse_rows(table_rows(url), year, agency))
            if not fetched:
                raise ValueError('Empty release schedule')
            events.update({(name, ref, stage, ''): day for day, name, ref, stage in fetched})
        except (requests.RequestException, ValueError):
            unavailable.append(agency.upper())

    def event(item):
        (name, reference, stage, _), raw = item
        day = date.fromisoformat(raw)
        if not earliest <= day <= latest:
            return None
        fomc = name == 'FOMC target range'
        release = datetime.combine(day, time(14) if fomc else time(8, 30), ET)
        previous, actual = readings(name, reference, release, stage, now)
        source = FED if fomc else BEA if name.startswith(('PCE', 'Real GDP')) else BLS.format(year=day.year)
        return dict(name=name, reference=reference, estimate=stage, release=release.isoformat(),
                    upcoming=now < release, previous=previous, actual=actual, forecast=None,
                    schedule_source=source,
                    reading_source=statement_url(day) if fomc and now >= release
                    else 'https://alfred.stlouisfed.org/series?seid=' + SERIES[name][0])

    with ThreadPoolExecutor(max_workers=16) as pool:
        rows = [row for row in pool.map(event, events.items()) if row]
    return {'events': sorted(rows, key=lambda row: (row['release'], row['name'])),
            'schedule_warnings': sorted(set(unavailable)),
            'readings_configured': bool(os.getenv('FRED_API_KEY'))}
