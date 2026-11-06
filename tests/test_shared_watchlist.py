import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'web'))

from app import app


class SharedWatchlistTest(unittest.TestCase):
    def test_editor_commits_against_loaded_private_revision(self):
        revision = 'a' * 40
        new_revision = 'b' * 40
        env = dict(DASHBOARD_PASSWORD='secret', GITHUB_TOKEN='token',
                   GITHUB_REPOSITORY='example/website', GITHUB_DATA_REPOSITORY='example/data')
        auth = {'Authorization': 'Bearer secret'}
        with patch.dict(os.environ, env), patch('app.get_file', return_value=({}, revision)) as get, \
             patch('app.requests.put') as put:
            client = app.test_client()
            watchlist = client.get('/api/watchlist', headers=auth)
            self.assertEqual(watchlist.headers['ETag'], '"' + revision + '"')
            get.assert_called_once_with('alerts/watchlist.json', data=True)
            self.assertEqual(client.put('/api/watchlist', headers=auth, json={}).status_code, 428)
            put.assert_not_called()
            put.return_value.json.return_value = {'content': {'sha': new_revision}}
            headers = {**auth, 'If-Match': watchlist.headers['ETag']}
            saved = client.put('/api/watchlist', headers=headers, json={})
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(saved.headers['ETag'], '"' + new_revision + '"')
            self.assertIn('/example/data/contents/alerts/watchlist.json', put.call_args.args[0])
            self.assertEqual(put.call_args.kwargs['json']['sha'], revision)
            put.return_value.raise_for_status.side_effect = requests.HTTPError(response=Mock(status_code=409))
            self.assertEqual(client.put('/api/watchlist', headers=headers, json={}).status_code, 409)
