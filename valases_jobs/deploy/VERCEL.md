# Job Portal on Vercel

Deploy the standalone `valases-job-portal` repository, not the Hiring Tool or Website.
The root `main.py` exports the FastAPI app; `pyproject.toml` declares `main:app`.
`vercel.json` explicitly selects the `fastapi` framework so the build does not
fall back to generic `/api` function discovery. Dependencies are listed directly
in `pyproject.toml` as well as `requirements.txt` for framework detection.
The app serves both `/` and `/assets/*`, plus the `/api/*` routes.

## Project settings

- Git repository: `raghav150698-alt/valases-job-portal`; production branch: `main`.
- Root Directory: repository root (leave empty), not `valases_jobs/web`.
- Framework: FastAPI. Remove any previous Vite/static build and output overrides.
- Build Command, Install Command and Output Directory: use framework defaults.
- Python: 3.12, as pinned in `.python-version`.
- Confirm the deployed Git commit contains `main.py`, `vercel.json` and `valases_jobs/`.
  The initial README-only commit `fd5b766` does not contain the application.

## External services and configuration

Copy the variable names from root `.env.example` into Vercel Project Settings.
Use actual service values, not the template's placeholders or localhost URLs.
Never commit configured secrets. Set variables for the deployment environment,
then redeploy; changing environment variables alone does not update an existing deployment.

- `JOBS_PUBLIC_ORIGIN`: exact HTTPS origin used in the browser, without a path.
  Preview deployments need their own matching origin; do not point a preview at
  production configuration or production candidate data.
- `JOBS_DATABASE_URL`: dedicated PostgreSQL database for candidates. Use a pooled
  PostgreSQL URL (`postgres://...`, `postgresql://...` and explicit
  `postgresql+psycopg://...` are supported) and provider-required
  TLS settings. Never use SQLite or the Hiring Tool database on Vercel.
- `JOBS_REDIS_URL`: reachable Redis endpoint with TLS if required (`rediss://...`).
  A Redis HTTP REST URL is not compatible with this client.
- `JOBS_ENCRYPTION_KEY`: stable generated Fernet key, backed up separately.
- `JOBS_VALASES_API_URL`, `JOBS_CANDIDATE_PORTAL_URL`, `JOBS_BRIDGE_KEY`: HTTPS
  Hiring Tool connections and shared bridge secret.
- SMTP, support contact, Cashfree and remaining launch settings: configure as
  documented in `.env.example`. Production validates them on startup.
- Keep `JOBS_CREATE_SCHEMA=false`, `JOBS_DEMO=false`, secure cookies, verified
  email and indexed catalog enabled. This configuration does not turn off launch checks.

Apply migrations once from a trusted environment using the same Jobs database:
`python -m valases_jobs.migrate`. Do not migrate during a Vercel build or request.

## Required worker

Vercel serves the web app; it does not start the Docker/systemd worker process.
Run `python -m valases_jobs.worker` on a persistent Python service using the same
Jobs environment/database. It refreshes vacancies every minute, delivers queued
verification and recovery email, reconciles payments and creates daily alerts.
The supplied systemd units are in this directory. Without that worker, mail stays
queued and the indexed job catalog becomes stale. Vercel Cron integration is not
implemented in this release; do not run the infinite worker inside a function.

## Verify and troubleshoot

1. `/` and `/assets/app.js` load successfully.
2. `/health` returns 200 with database connectivity.
3. `/ready` returns 200 after migrations, worker sync and required services are ready.
4. Test registration, verification email, resume parsing and the application handoff
   in staging before public launch. Test payment delivery only in the intended environment.

- Unmatched `main.py` function pattern: confirm the deployed `vercel.json` contains
  `"framework": "fastapi"`; remove any project setting override that selects a
  static framework or Other.
- 404: check repository, deployed commit, Root Directory and framework overrides.
- Build failure: copy the Python dependency error from Vercel build logs.
- FUNCTION_INVOCATION_FAILED: inspect runtime logs for missing environment settings,
  invalid encryption key, inaccessible database or missing schema.
- 403 on form submissions: `JOBS_PUBLIC_ORIGIN` must match the browser origin.
- 503 on jobs/readiness: verify initial catalog sync and the persistent worker.

References: https://vercel.com/docs/frameworks/backend/fastapi and
https://vercel.com/docs/functions/runtimes/python.

### Runtime failure after a successful build

A successful build does not verify application startup, service credentials or
connectivity. For `FUNCTION_INVOCATION_FAILED`, use the project's request/runtime
Logs, refresh the failed page and find its Python exception. Build Logs do not
contain this traceback. Missing `JOBS_DATABASE_URL` / `JOBS_PUBLIC_ORIGIN` or
incomplete launch settings intentionally prevent public startup. Do not replace
these checks with demo mode, local SQLite or placeholder secrets.
