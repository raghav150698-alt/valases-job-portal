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

## Background processing on Vercel

Set `JOBS_BACKGROUND_MODE=scheduled` and an independently generated
`JOBS_CRON_SECRET` with at least 32 random characters. Configure a scheduler to
call these GET routes with `Authorization: Bearer <JOBS_CRON_SECRET>`:

| Route | Pilot schedule | Work per invocation |
| --- | --- | --- |
| `/api/internal/tasks/mail` | Every minute | One queued email, with retry/lease handling |
| `/api/internal/tasks/catalog` | Every 2 minutes | One complete atomic vacancy snapshot |
| `/api/internal/tasks/digest` | Every minute | One eligible candidate's daily digest |
| `/api/internal/tasks/payments` | Every minute | One recent pending order, rotated across at most 100 |
| `/api/internal/tasks/cleanup` | Daily | Expired sessions/tokens and old email outbox cleanup |

The daily digest schedule remains per candidate; triggering this task every
minute does not send each candidate an email every minute. Mail delivery is one
item per run, intended for a small pilot. Monitor backlog and delivery latency;
increase capacity or use a persistent worker before increasing volume. Signed
payment webhooks and checkout verification remain the primary payment paths.

cron-job.org supports these calls with a custom Authorization header. With
Vercel's built-in Cron, add the routes/schedules to `vercel.json` and set
`CRON_SECRET` to the same value as `JOBS_CRON_SECRET` so Vercel sends the header.
Frequent built-in schedules require Pro; Hobby permits only daily schedules and
is for personal, non-commercial use. No schedules are enabled automatically.

Each task returns counts only, without candidate information. Tasks use separate
PostgreSQL advisory locks to skip overlapping runs of the same task, short
provider timeouts and database statement/lock timeouts. Use the **Supabase
Session pooler (port 5432)** or a direct PostgreSQL connection: session advisory
locks are not compatible with transaction pooling. Catalog pagination has a
25-second fetch budget and never publishes a partial snapshot. Large feeds may
need the persistent worker; individual database statements are limited to 25
seconds, which is not a guarantee that the whole task finishes within 60 seconds.

Configure failure alerts in the scheduler. First run catalog sync, then check
`/ready`. Check mail queue age and failed delivery counts, not just HTTP success:
an SMTP failure is retained for retry and the batch can still return 200.
Disable the external schedules before switching to a persistent worker.

## Persistent worker alternative

Vercel serves the web app; it does not start the Docker/systemd worker process.
Run `python -m valases_jobs.worker` on a persistent Python service using the same
Jobs environment/database. It refreshes vacancies every minute, delivers queued
verification and recovery email, reconciles payments and creates daily alerts.
The supplied systemd units are in this directory. Without that worker, mail stays
queued and the indexed job catalog becomes stale unless scheduled tasks above
are configured. Use `JOBS_BACKGROUND_MODE=persistent` for this alternative;
do not run the infinite worker inside a function.

## Verify and troubleshoot

1. `/` and `/assets/app.js` load successfully.
2. `/health` returns 200 with database connectivity.
3. `/ready` returns 200 after migrations, worker sync and required services are ready.
4. Test registration, verification email, resume parsing and the application handoff
   in staging before public launch. Test payment delivery only in the intended environment.
5. Confirm scheduled task authentication, successful catalog refresh, queue
   drain, retries and failure alerts; PostgreSQL overlap behavior needs live validation.

- Unmatched `main.py` function pattern: confirm the deployed `vercel.json` contains
  `"framework": "fastapi"`; remove any project setting override that selects a
  static framework or Other.
- 404: check repository, deployed commit, Root Directory and framework overrides.
- Build failure: copy the Python dependency error from Vercel build logs.
- FUNCTION_INVOCATION_FAILED: inspect runtime logs for missing environment settings,
  invalid encryption key, inaccessible database or missing schema.
- 403 on form submissions: `JOBS_PUBLIC_ORIGIN` must match the browser origin.
- 503 on jobs/readiness: verify initial catalog sync and the configured scheduler or worker.

References: https://vercel.com/docs/frameworks/backend/fastapi and
https://vercel.com/docs/functions/runtimes/python.

### Runtime failure after a successful build

A successful build does not verify application startup, service credentials or
connectivity. For `FUNCTION_INVOCATION_FAILED`, use the project's request/runtime
Logs, refresh the failed page and find its Python exception. Build Logs do not
contain this traceback. Missing `JOBS_DATABASE_URL` / `JOBS_PUBLIC_ORIGIN` or
incomplete launch settings intentionally prevent public startup. Do not replace
these checks with demo mode, local SQLite or placeholder secrets.

Startup configuration errors now return a controlled 503 instead of crashing the
function import. Visit `/ready` for a credential-free list of missing setup
requirements. All account, matching and payment actions remain unavailable until
normal startup passes validation. Runtime logs contain a `Job Portal startup
blocked` message with controlled labels; setting values are never included.

### Public preview before service setup

Set `JOBS_PUBLIC_PREVIEW=true` in the Vercel environment being deployed and
redeploy. This explicitly selects a separate preview app, with no database,
Redis, SMTP, bridge, worker or Cashfree clients. Existing service settings are
unused in this mode. It serves synthetic vacancies, search and bounded sample
text matching; accounts, uploads, saved profiles, applications, payments,
webhooks and emails are blocked by the server. A visible banner labels the
preview. `/ready` reports `mode: public_preview` and `production_ready: false`.

When ready for the operational portal, set `JOBS_PUBLIC_PREVIEW=false`, configure
all required services, migrate the Jobs database and configure scheduled tasks
or run the worker. The normal
production checks remain enforced. Never use preview readiness as a production
launch signal.

### Email before purchasing a domain

The existing SMTP integration supports STARTTLS on port 587. Use the actual
Zoho ZeptoMail SMTP host and credentials displayed in the chosen regional
account; the sender must be verified. Zoho Mail is the team's mailbox service,
not the transactional sender. Configure `JOBS_SMTP_*` on Vercel only. A domain
is not required to build or test the application with mocked email delivery,
but real delivery needs provider sender verification. Do not claim production
email works until controlled live verification/reset tests pass.

References: https://www.zoho.com/mail/help/usage-policy.html,
https://vercel.com/docs/cron-jobs/usage-and-pricing,
https://vercel.com/docs/plans/hobby, https://cron-job.org/en/faq/.
