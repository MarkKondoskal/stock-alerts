from copy import deepcopy
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
import requests

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'web')]
import app
from research_library import initial,public,validate


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,dict(DASHBOARD_PASSWORD='test',GITHUB_TOKEN='fake',GITHUB_REPOSITORY='test/code',GITHUB_DATA_REPOSITORY='test/data'))
        self.env.start();self.addCleanup(self.env.stop)
        self.client=app.app.test_client();self.auth={'Authorization':'Bearer test'}

    def test_public_projection_filters_drafts_and_private_notes(self):
        doc=initial();doc['articles'][0]['private_notes']='PRIVATE SECRET'
        draft={**deepcopy(doc['articles'][0]),'id':'draft','title':'Secret draft','published':False,'featured':False}
        doc['articles'].append(draft)
        result=public(doc)
        self.assertEqual(len(result['articles']),1)
        self.assertNotIn('PRIVATE SECRET',str(result));self.assertNotIn('Secret draft',str(result))
        self.assertNotIn('private_notes',result['articles'][0])

    def test_validation_rejects_unsafe_urls_duplicate_ids_and_bad_visibility(self):
        for url in ('javascript:alert(1)','http://example.com/post','https://name:secret@example.com/post'):
            doc=initial();doc['articles'][0]['url']=url
            with self.assertRaises(ValueError):validate(doc)
        doc=initial();doc['articles'].append(deepcopy(doc['articles'][0]))
        with self.assertRaises(ValueError):validate(doc)
        doc=initial();doc['articles'][0]['published']='yes'
        with self.assertRaises(ValueError):validate(doc)

    def test_missing_file_seeds_intro_and_uses_creation_revision(self):
        error=requests.HTTPError(response=Mock(status_code=404))
        with patch.object(app,'get_file',side_effect=error):
            result=self.client.get('/api/private/research',headers=self.auth)
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.headers['ETag'],'"new"')
            self.assertIn('/p/first-substack',result.json['articles'][0]['url'])

    def test_private_read_and_write_require_auth(self):
        with patch.object(app,'get_file') as get,patch.object(app.requests,'put') as put:
            self.assertEqual(self.client.get('/api/private/research').status_code,401)
            self.assertEqual(self.client.put('/api/private/research',json=initial()).status_code,401)
            get.assert_not_called();put.assert_not_called()

    def test_create_conflict_and_successful_revision_checked_save(self):
        response=Mock(status_code=200);response.json.return_value={'content':{'sha':'b'*40}}
        with patch.object(app.requests,'put',return_value=response) as put:
            self.assertEqual(self.client.put('/api/private/research',headers=self.auth,json=initial()).status_code,428)
            put.assert_not_called()
            created=self.client.put('/api/private/research',headers={**self.auth,'If-Match':'"new"'},json=initial())
            self.assertEqual(created.status_code,200)
            self.assertNotIn('sha',put.call_args.kwargs['json'])
            self.assertIn('/test/data/contents/research/library.json',put.call_args.args[0])
            self.assertEqual(created.headers['Cache-Control'],'private, no-store')
            self.client.put('/api/private/research',headers={**self.auth,'If-Match':'"'+'a'*40+'"'},json=initial())
            self.assertEqual(put.call_args.kwargs['json']['sha'],'a'*40)
            response.status_code=409
            self.assertEqual(self.client.put('/api/private/research',headers={**self.auth,'If-Match':'"new"'},json=initial()).status_code,409)

    def test_public_api_never_falls_back_to_seed_on_permission_failure(self):
        with patch.object(app,'get_file',side_effect=requests.HTTPError(response=Mock(status_code=403))):
            self.assertEqual(self.client.get('/api/public/research').status_code,502)

    def test_removing_all_articles_stays_empty(self):
        self.assertEqual(public({'articles':[]})['articles'],[])
