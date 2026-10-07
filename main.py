"""Vercel entry point with fail-closed startup diagnostics."""
import logging
import os
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from valases_jobs.settings import Settings

def local_origin(value):
    try:
        return urlsplit(value).hostname in {"localhost", "127.0.0.1", "::1"}
    except ValueError:
        return False


config = None
try:
    config = Settings()
    if os.environ.get("VERCEL") == "1":
        if not config.database_url.startswith("postgresql"):
            raise RuntimeError("Vercel requires JOBS_DATABASE_URL pointing to a dedicated PostgreSQL database")
        if local_origin(config.public_origin):
            raise RuntimeError("Set JOBS_PUBLIC_ORIGIN to this deployment's HTTPS origin")
    from valases_jobs.main import app
except Exception as startup_error:
    if os.environ.get("VERCEL") != "1":
        raise
    # Only controlled labels are reported. Exception text and settings values
    # can contain passwords, database URLs and tokens and must never be returned.
    issues = config.launch_issues() if config else ["Environment settings could not be parsed"]
    if config and local_origin(config.public_origin):
        issues.append("JOBS_PUBLIC_ORIGIN must be the deployed HTTPS origin")
    if not issues:
        issues = ["Application initialization failed; check deployment settings and runtime logs"]
    issues = list(dict.fromkeys(issues))
    error_type = type(startup_error).__name__
    logging.getLogger("valases_jobs.startup").error(
        "Job Portal startup blocked (%s): %s", error_type, "; ".join(issues))
    app = FastAPI(title="Valases Jobs unavailable", docs_url=None, redoc_url=None, openapi_url=None)

    @app.api_route("/ready", methods=["GET", "HEAD"])
    def startup_readiness():
        return JSONResponse({"ready": False, "code": "startup_configuration_required",
                             "issues": issues, "error_type": error_type}, status_code=503,
                            headers={"Cache-Control": "no-store"})

    @app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    def unavailable(request: Request, path: str):
        if request.method not in {"GET", "HEAD"} or path.startswith("api/"):
            return JSONResponse({"detail": "Job Portal setup is incomplete", "ready": False},
                                status_code=503, headers={"Cache-Control": "no-store"})
        return HTMLResponse("""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Valases Jobs unavailable</title><body>
<h1>Valases Jobs is temporarily unavailable</h1>
<p>The service is being configured. Please try again later.</p>
</body></html>""", status_code=503,
                            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
