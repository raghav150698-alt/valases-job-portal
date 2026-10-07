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

    def test_vercel_refuses_default_local_sqlite(self):
        result = self.run_entry('import main', {'VERCEL': '1'})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Vercel requires JOBS_DATABASE_URL', result.stderr)

    def test_vercel_requires_deployed_origin_before_loading_app(self):
        result = self.run_entry('import main', {
            'VERCEL': '1',
            'JOBS_DATABASE_URL': 'postgresql+psycopg://example:placeholder@localhost/jobs',
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Set JOBS_PUBLIC_ORIGIN', result.stderr)


if __name__ == '__main__':
    unittest.main()
