"""Vercel ASGI entry point; all portal routes remain in the standalone package."""
import os
from valases_jobs.settings import Settings

if os.environ.get("VERCEL") == "1":
    config = Settings()
    if not config.database_url.startswith("postgresql"):
        raise RuntimeError("Vercel requires JOBS_DATABASE_URL pointing to a dedicated PostgreSQL database")
    if config.public_origin.startswith(("http://127.0.0.1", "http://localhost")):
        raise RuntimeError("Set JOBS_PUBLIC_ORIGIN to this deployment's HTTPS origin")

from valases_jobs.main import app
