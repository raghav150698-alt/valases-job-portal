from datetime import datetime, timedelta, timezone
from io import BytesIO
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from valases_jobs.main import create_app
from valases_jobs.matching import evidence, match_jobs
from valases_jobs.models import Account, LoginSession, Profile, SavedJob
from valases_jobs.settings import Settings


class JobsPlatformTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.app = create_app(Settings(demo=True, create_schema=True, secure_cookies=False), self.engine)
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.engine.dispose()

    def register(self, email="candidate@example.com"):
        result = self.client.post("/api/auth/register", json={"email": email, "password": "a-secure-password-123", "name": "Candidate",'accepted_terms':True})
        self.assertEqual(result.status_code, 201, result.text)

    def test_browse_without_account_and_demo_cannot_apply(self):
        response = self.client.get("/api/jobs")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(job["demo"] and job["apply_url"] is None for job in response.json()["items"]))

    def test_private_profile_and_saved_jobs_do_not_cross_accounts(self):
        self.register()
        self.assertEqual(self.client.put("/api/me/profile", json={"resume_text": "Private SQL project"}).status_code, 200)
        self.client.put("/api/me/saved/demo-1")
        self.client.put("/api/me/saved/demo-1")
        self.assertEqual(self.client.get("/api/me").json()["saved_jobs"], ["demo-1"])
        self.client.post("/api/auth/logout")
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        self.register("other@example.com")
        second = self.client.get("/api/me").json()
        self.assertEqual(second["profile"]["resume_text"], "")
        self.assertEqual(second["saved_jobs"], [])

    def test_login_and_deletion_revoke_sessions_and_remove_profile(self):
        self.register()
        self.client.put("/api/me/profile", json={"resume_text": "SQL and Python project"})
        self.client.put("/api/me/saved/demo-1")
        self.client.post("/api/auth/logout")
        bad = self.client.post("/api/auth/login", json={"email": "candidate@example.com", "password": "wrong-password-123"})
        self.assertEqual(bad.status_code, 401)
        good = self.client.post("/api/auth/login", json={"email": "candidate@example.com", "password": "a-secure-password-123"})
        self.assertEqual(good.status_code, 200)
        self.assertEqual(self.client.delete("/api/me").status_code, 200)
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        with Session(self.engine) as db:
            for model in (Account, Profile, SavedJob, LoginSession):
                self.assertIsNone(db.scalar(select(model)))

    def test_preview_free_but_full_matching_server_gated(self):
        preview = self.client.post("/api/matches/preview", json={"resume_text": "Built APIs in Python, SQL, JavaScript and Git. Testing with Selenium. React projects and Excel."})
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(len(preview.json()["items"]), 3)
        self.register()
        self.assertEqual(self.client.get("/api/me/matches").status_code, 402)

    def test_cross_origin_writes_and_invalid_sessions_rejected(self):
        result = self.client.post("/api/auth/register", headers={"Origin": "https://evil.example"}, json={"email": "test@example.com", "password": "password-123456"})
        self.assertEqual(result.status_code, 403)
        self.client.cookies.set("jobs_session", "made-up-session")
        self.assertEqual(self.client.get("/api/me").status_code, 401)

    def test_text_and_docx_extract_and_oversized_upload_rejected(self):
        text = "Python and SQL projects with automated testing"
        result = self.client.post("/api/resume/extract", files={"file": ("resume.txt", text.encode(), "text/plain")})
        self.assertEqual(result.json()["resume_text"], text)
        document = BytesIO()
        with ZipFile(document, "w") as archive:
            archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>' + text + '</w:t></w:r></w:p></w:body></w:document>')
        result = self.client.post("/api/resume/extract", files={"file": ("resume.docx", document.getvalue())})
        self.assertEqual(result.json()["resume_text"], text)
        result = self.client.post("/api/resume/extract", files={"file": ("huge.txt", b"x" * (2 * 1024 * 1024 + 1))})
        self.assertEqual(result.status_code, 413)

    def test_pdf_extract_and_malformed_upload(self):
        from reportlab.pdfgen import canvas
        document = BytesIO()
        pdf = canvas.Canvas(document)
        pdf.drawString(50, 700, "Python and SQL projects with automated testing")
        pdf.save()
        result = self.client.post("/api/resume/extract", files={"file": ("resume.pdf", document.getvalue())})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIn("Python and SQL", result.json()["resume_text"])
        result = self.client.post("/api/resume/extract", files={"file": ("broken.docx", b"not a zip")})
        self.assertEqual(result.status_code, 422)

    def test_expired_session_and_paid_expiry_fail_closed(self):
        self.register()
        with Session(self.engine) as db:
            user = db.scalar(select(Account))
            user.paid_until = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
        self.assertEqual(self.client.get("/api/me/matches").status_code, 402)
        with Session(self.engine) as db:
            login = db.scalar(select(LoginSession))
            login.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
        self.assertEqual(self.client.get("/api/me").status_code, 401)

    def test_bridge_builds_application_handoff_with_encoded_identifiers(self):
        self.app.state.bridge.settings.demo = False
        self.app.state.bridge.settings.valases_api_url = "https://valases.example/api"
        self.app.state.bridge.settings.candidate_portal_url = "https://candidate.valases.example"
        self.app.state.bridge.settings.bridge_key = "x" * 32
        import httpx
        response = httpx.Response(200, request=httpx.Request("GET", "https://valases.example/api/job-marketplace/jobs"),
            json={"items": [{"id": "1", "company": "Employer", "title": "Engineer", "organization_slug": "example", "job_code": "JOB & 1"}], "next_cursor": None})
        with patch("valases_jobs.bridge.httpx.Client") as factory:
            get = factory.return_value.__enter__.return_value.get
            get.return_value = response
            result = self.client.get("/api/jobs")
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["items"][0]["apply_url"], "https://candidate.valases.example/?apply_org=example&apply_job=JOB+%26+1")
            self.client.get("/api/jobs")
            self.assertEqual(get.call_count, 1)

    def test_unconfigured_connection_has_no_fake_fallback(self):
        self.app.state.bridge.settings.demo = False
        response = self.client.get("/api/jobs")
        self.assertEqual(response.status_code, 503)
        self.assertIn("not configured", response.json()["detail"])

    def test_public_deployment_rejects_demo_and_insecure_cookies(self):
        with self.assertRaises(ValueError):
            create_app(Settings(public_origin="https://jobs.valases.com", demo=True))
        with self.assertRaises(ValueError):
            create_app(Settings(public_origin="https://jobs.valases.com", secure_cookies=False))


class MatchingTests(unittest.TestCase):
    def test_exact_tokens_do_not_confuse_java_javascript_or_c_cpp(self):
        self.assertIsNone(evidence("JavaScript and C++ projects", "java"))
        self.assertIsNone(evidence("JavaScript and C++ projects", "c"))
        self.assertIsNotNone(evidence("JavaScript and C++ projects", "c++"))

    def test_no_keyword_stuffing_or_unsupported_jobs(self):
        jobs = [{"id": "1", "skills": ["Python", "SQL"]}, {"id": "2", "skills": ["Java"]}, {"id": "3", "skills": []}]
        first = match_jobs("Python project", {}, jobs)
        second = match_jobs("Python " * 200, {}, jobs)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["score"], second[0]["score"])
        self.assertIsNone(evidence("No Python experience", "python"))

    def test_experience_unknown_and_mismatch_cannot_be_strong(self):
        job = {"id": "1", "skills": ["Python"], "minimum_experience_years": 5}
        self.assertNotEqual(match_jobs("Python projects", {}, [job])[0]["band"], "Strong match")
        self.assertEqual(match_jobs("Python projects", {"experience_years": 1}, [job])[0]["band"], "Stretch role")

    def test_hard_work_preference_filters_and_empty_matches(self):
        jobs = [{"id": "1", "skills": ["Python"], "work_arrangement": "hybrid", "location": "Bengaluru"}]
        self.assertEqual(match_jobs("Python project", {"work_arrangement": "remote"}, jobs), [])
        self.assertEqual(match_jobs("Accounting project", {}, jobs), [])
