"""Public, explicitly enabled preview. No database or external service clients."""
from copy import deepcopy
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from valases_jobs.body_limit import BodyLimit
from valases_jobs.demo import JOBS
from valases_jobs.matching import match_jobs

WEB = Path(__file__).parent / "web"


class PreviewPreferences(BaseModel):
    location: str = Field(default="", max_length=180)
    work_arrangement: str = Field(default="any", pattern="^(any|remote|hybrid|on_site)$")
    experience_years: float | None = Field(default=None, ge=0, le=80)


class PreviewProfile(BaseModel):
    resume_text: str = Field(min_length=20, max_length=120000)
    preferences: PreviewPreferences = Field(default_factory=PreviewPreferences)


def sample_jobs():
    return [{**deepcopy(job), "demo": True, "apply_url": None} for job in JOBS]


def create_preview_app():
    app = FastAPI(title="Valases Jobs public preview", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(BodyLimit, maximum=128 * 1024)

    @app.middleware("http")
    async def preview_boundary(request, call_next):
        if request.method not in {"GET", "HEAD"} and not (
                request.method == "POST" and request.url.path == "/api/matches/preview"):
            return JSONResponse({"detail": "This is a public preview. Accounts, uploads, applications, payments and email are disabled."}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response

    @app.get("/api/config")
    def public_config():
        return {"name": "Valases Jobs", "public_preview": True, "demo": True,
                "checkout_enabled": False, "connected": False, "monthly_price_inr": 79,
                "matching_version": "skills-evidence-v2", "support_email": ""}

    @app.get("/api/jobs")
    def jobs(q: str = Query("", max_length=200), location: str = Query("", max_length=180),
             arrangement: str = Query("", max_length=80), employment_type: str = Query("", max_length=80),
             offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
        work = set(filter(None, arrangement.split(",")))
        types = set(filter(None, employment_type.split(",")))
        items = [job for job in sample_jobs()
                 if q.lower() in (job["title"] + " " + job["company"] + " " + " ".join(job["skills"])).lower()
                 and location.lower() in job["location"].lower()
                 and (not work or job["work_arrangement"] in work)
                 and (not types or job["employment_type"] in types)]
        return {"items": items[offset:offset + limit], "total": len(items), "demo": True, "paginated": True}

    @app.post("/api/matches/preview")
    def matches(body: PreviewProfile):
        if len(body.resume_text.strip()) < 20:
            raise HTTPException(422, "Use at least 20 characters of sample experience text")
        results = match_jobs(body.resume_text, body.preferences.model_dump(), sample_jobs())
        return {"items": results[:3], "total": len(results), "preview": True, "demo": True}

    @app.get("/api/me")
    def no_account():
        raise HTTPException(401, "Accounts are disabled in the public preview")

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": "public_preview"}

    @app.get("/ready")
    def ready():
        return {"ready": True, "mode": "public_preview", "production_ready": False}

    @app.get("/")
    def index():
        html = (WEB / "index.html").read_text(encoding="utf-8")
        html = html.replace('<body>', '<body class="public-preview"><section class="preview-banner" role="status"><strong>Public preview</strong> · Sample vacancies only. Accounts, applications, payments and email are disabled. Use sample experience text for matching.</section>')
        return HTMLResponse(html)

    @app.get("/{notice}")
    def notice(notice: str):
        if notice not in {"privacy", "terms", "contact"}:
            raise HTTPException(404, "Page not found")
        return HTMLResponse('<!doctype html><html lang="en"><meta charset="utf-8"><title>Valases Jobs preview</title><body><a href="/">Back to preview</a><h1>Public preview</h1><p>All vacancies are synthetic. No accounts, file uploads, applications, payments or emails are accepted. Sample text is processed for matching without being saved by this application. Use fictional experience rather than personal information.</p></body></html>')

    app.mount("/assets", StaticFiles(directory=WEB), name="assets")

    @app.api_route("/api/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    def disabled(path: str):
        raise HTTPException(403, "This action is disabled in the public preview")

    return app
