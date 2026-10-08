import time
from threading import Lock
from urllib.parse import urlencode
import httpx
from fastapi import HTTPException
from valases_jobs.demo import JOBS


class ValasesBridge:
    def __init__(self, settings):
        self.settings = settings
        self.cache = None
        self.cached_at = 0
        self.lock = Lock()

    def jobs(self, *, deadline=None):
        if self.settings.demo:
            return [{**job, "demo": True, "apply_url": None} for job in JOBS]
        if not self.settings.valases_api_url or len(self.settings.bridge_key) < 32:
            raise HTTPException(503, "Valases connection is not configured. No live jobs are available yet.")
        with self.lock:
            if self.cache is not None and time.monotonic() - self.cached_at < 30:
                return self.cache
            try:
                jobs, cursor = [], 0
                with httpx.Client(timeout=10, follow_redirects=False) as client:
                    for _ in range(self.settings.catalog_page_limit):
                        remaining = deadline - time.monotonic() if deadline is not None else None
                        if remaining is not None and remaining <= 1:
                            raise HTTPException(503, 'Catalog synchronization exceeded its batch budget')
                        response = client.get(self.settings.valases_api_url.rstrip("/") + "/job-marketplace/jobs",
                                              params={"after": cursor, "limit": 200},
                                              headers={"Authorization": "Bearer " + self.settings.bridge_key},
                                              timeout=min(5, remaining / 4) if remaining is not None else 10)
                        response.raise_for_status()
                        data = response.json()
                        for job in data["items"]:
                            query = urlencode({"apply_org": job["organization_slug"], "apply_job": job["job_code"]})
                            job["apply_url"] = self.settings.candidate_portal_url.rstrip("/") + "/?" + query if self.settings.candidate_portal_url else None
                            jobs.append(job)
                        next_cursor = data.get("next_cursor")
                        if next_cursor is None:
                            break
                        if next_cursor <= cursor:
                            raise ValueError("Invalid feed cursor")
                        cursor = next_cursor
                    else:
                        raise HTTPException(503, "Catalog synchronization limit exceeded")
                self.cache, self.cached_at = jobs, time.monotonic()
                return jobs
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                raise HTTPException(503, "Valases connection is temporarily unavailable") from None
