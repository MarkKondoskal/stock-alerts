"""Use stable performance filenames with a fallback for pre-migration files."""
import requests

LEGACY_NAMES = {
    'merrill_history_provisional.csv': 'merrill_2026_ytd_provisional.csv',
    'merrill_history_summary.json': 'merrill_2026_ytd_summary.json',
    'combined_history_provisional.csv': 'combined_2026_ytd_provisional.csv',
    'combined_history_summary.json': 'combined_2026_ytd_summary.json',
    'merrill_no_etf_history_provisional.csv': 'merrill_no_etf_2026_ytd_provisional.csv',
    'merrill_no_etf_history_summary.json': 'merrill_no_etf_2026_ytd_summary.json',
    'combined_no_etf_history_provisional.csv': 'combined_no_etf_2026_ytd_provisional.csv',
    'combined_no_etf_history_summary.json': 'combined_no_etf_2026_ytd_summary.json',
}


def read_history(path, fetch):
    folder, _, name = path.rpartition('/')
    try:
        return fetch(path)
    except requests.HTTPError as error:
        if error.response is None or error.response.status_code != 404 or name not in LEGACY_NAMES:
            raise
    return fetch(f'{folder}/{LEGACY_NAMES[name]}')
