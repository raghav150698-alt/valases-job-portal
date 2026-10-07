"""Exercise the actual deployment module without contacting external providers."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]


class VercelEntrypointTests(unittest.TestCase):
    def run_entry(self, code, overrides):
        env = {k: v for k, v in os.environ.items() if not k.startswith("JOBS_") and k != "VERCEL"}
        env.update(overrides)
        return subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=30)

    def test_root_and_static_assets_are_served_from_deployment_module(self):
        code = """
from fastapi.testclient import TestClient
from main import app
with TestClient(app) as client:
    page = client.get('/')
    assert page.status_code == 200 and 'Valases' in page.text
    asset = client.get('/assets/app.js')
    assert asset.status_code == 200 and len(asset.content) > 100
    assert any(route.path == '/api/auth/register' for route in app.routes)
"""
        result = self.run_entry(code, {})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_provider_postgresql_urls_use_installed_driver(self):
        from sqlalchemy import create_engine
        from valases_jobs.settings import Settings
        tail = "example:placeholder@localhost/jobs?sslmode=require"
        for scheme in ("postgres://", "postgresql://", "postgresql+psycopg://"):
            with self.subTest(scheme=scheme):
                settings = Settings(database_url=scheme + tail)
                self.assertEqual(settings.database_url, "postgresql+psycopg://" + tail)
                engine = create_engine(settings.database_url)
                self.assertEqual(engine.dialect.driver, "psycopg")
                engine.dispose()  # No connection is opened by this check.

    def test_unconfigured_vercel_reports_requirements_and_blocks_actions(self):
        code = """
from fastapi.testclient import TestClient
from main import app
with TestClient(app) as client:
    ready = client.get('/ready')
    assert ready.status_code == 503 and ready.json()['ready'] is False
    assert 'Dedicated PostgreSQL database is required' in ready.json()['issues']
    assert any('JOBS_PUBLIC_ORIGIN' in issue for issue in ready.json()['issues'])
    assert client.get('/').status_code == 503
    assert client.post('/api/auth/register', json={}).status_code == 503
    assert client.post('/api/payments/webhook', json={}).status_code == 503
"""
        result = self.run_entry(code, {'VERCEL': '1'})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_database_accepted_and_remaining_setup_reported_without_secrets(self):
        secret = 'sentinel-password-never-log'
        code = """
from fastapi.testclient import TestClient
from main import app
with TestClient(app) as client:
    ready = client.get('/ready')
    assert ready.status_code == 503
    issues = ready.json()['issues']
    assert 'Dedicated PostgreSQL database is required' not in issues
    assert 'Shared Redis rate limiting is not configured' in issues
    assert 'Data encryption key is missing' in issues
    assert 'sentinel-password-never-log' not in ready.text
    assert 'postgresql://' not in ready.text
"""
        result = self.run_entry(code, {
            'VERCEL': '1',
            'JOBS_DATABASE_URL': 'postgresql://example:' + secret + '@localhost/jobs',
            'JOBS_PUBLIC_ORIGIN': 'https://valases-job-portal.vercel.app',
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(secret, result.stderr)

    def test_invalid_setting_does_not_leak_input(self):
        code = """
from fastapi.testclient import TestClient
from main import app
with TestClient(app) as client:
    response = client.get('/ready')
    assert response.status_code == 503
    assert response.json()['error_type'] == 'ValidationError'
    assert 'sentinel-private-input' not in response.text
"""
        result = self.run_entry(code, {'VERCEL': '1', 'JOBS_SMTP_PORT': 'sentinel-private-input'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('sentinel-private-input', result.stderr)


if __name__ == '__main__':
    unittest.main()
