import unittest
from fastapi.testclient import TestClient
from valases_jobs.public_preview import create_preview_app


class PublicPreviewTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_preview_app())

    def test_sample_inventory_and_filters_are_labelled(self):
        response = self.client.get('/api/jobs')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['total'], 4)
        self.assertTrue(all(job['demo'] and job['apply_url'] is None for job in response.json()['items']))
        remote = self.client.get('/api/jobs?arrangement=remote').json()
        self.assertEqual(remote['total'], 2)
        self.assertTrue(all(job['work_arrangement'] == 'remote' for job in remote['items']))
        self.assertEqual(self.client.get('/api/jobs?q=unmatched-role').json()['total'], 0)
        self.assertEqual(len(self.client.get('/api/jobs?offset=1&limit=1').json()['items']), 1)

    def test_matching_is_bounded_and_sample_only(self):
        response = self.client.post('/api/matches/preview', json={
            'resume_text': 'Sample experience: Built Python APIs, SQL reports and testing with Git.',
            'preferences': {'work_arrangement': 'any'},
        })
        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.json()['total'], 0)
        self.assertLessEqual(len(response.json()['items']), 3)
        self.assertTrue(all(item['job']['demo'] and item['job']['apply_url'] is None for item in response.json()['items']))
        self.assertEqual(self.client.post('/api/matches/preview', json={'resume_text': 'too short'}).status_code, 422)
        self.assertEqual(self.client.post('/api/matches/preview', content=b'x' * (129 * 1024)).status_code, 413)

    def test_all_real_actions_are_rejected_by_server(self):
        paths = ['/api/auth/register', '/api/auth/login', '/api/auth/logout',
                 '/api/auth/verification', '/api/auth/reset', '/api/me/profile',
                 '/api/me/saved/demo-1', '/api/resume/extract', '/api/billing/orders',
                 '/api/billing/webhook', '/api/applications', '/anything-new']
        for path in paths:
            for method in ['POST', 'PUT', 'PATCH', 'DELETE']:
                with self.subTest(path=path, method=method):
                    self.assertEqual(self.client.request(method, path, json={}).status_code, 403)
        self.assertEqual(self.client.get('/api/me').status_code, 401)
        self.assertEqual(self.client.get('/api/me/export').status_code, 403)
        self.assertEqual(self.client.get('/api/billing/orders').status_code, 403)

    def test_preview_page_assets_and_readiness_are_explicit(self):
        page = self.client.get('/')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Public preview', page.text)
        self.assertIn('accounts', page.text.lower())
        self.assertEqual(self.client.get('/assets/app.js').status_code, 200)
        self.assertEqual(self.client.get('/assets/workspace.css').status_code, 200)
        ready = self.client.get('/ready').json()
        self.assertTrue(ready['ready'])
        self.assertFalse(ready['production_ready'])
        self.assertEqual(ready['mode'], 'public_preview')
        self.assertFalse(self.client.get('/api/config').json()['checkout_enabled'])
        self.assertIn('noindex', page.headers['X-Robots-Tag'])
        self.assertIn('no accounts', self.client.get('/privacy').text.lower())
