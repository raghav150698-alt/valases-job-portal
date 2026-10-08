# Valases Jobs

A standalone candidate product connected to the existing Valases hiring tool.
Intended domain: **jobs.valases.com**, to be purchased/configured later.
The package imports no recruiter application code and uses a separate database.
It can run beside Valases on the same hosting account. Docker is optional.

## Implemented

- Official Valases logo, self-hosted Manrope, responsive job portal with search,
  work/type filters, detailed vacancies, saved jobs and free application handoff.
- Candidate accounts with hashed passwords, expiring HTTP-only sessions, email
  verification, single-use recovery links, session revocation, export and deletion.
- PDF/DOCX/TXT extraction in bounded disposable subprocesses. Uploads are never
  retained. Saved production resume text and email payloads are encrypted.
- Free three-result preview. INR 79 buys 30 days of full matching and optional
  daily alerts; renewal is manual. Server-verified Cashfree payments, signed
  webhook handling, duplicate-grant protection and pending-order reconciliation.
- Durable email outbox, retries/leases, opt-in digests, unsubscribe links and
  checks that cancel queued digests after opt-out or plan expiry.
- Recruiter publication controls with organization permission checks. Only
  explicitly published open jobs from active employers enter the public feed.
- Transactional catalog synchronization, PostgreSQL full-text search index,
  indexed skill retrieval and paginated search/matching. Freshness gates prevent
  serving indefinitely stale vacancies.
- Shared Redis rate limits for auth, extraction, matching and checkout; bounded
  request bodies, origin checks, CSP, HTTPS cookies and deployment validation.
- Privacy, terms and support pages; migration, worker, readiness checks and
  native-service deployment configuration.

## Matching boundaries

`skills-evidence-v2` normalizes common technical and nontechnical skill aliases,
weights general skills lower, applies location/work preferences and experience
checks, and explains supporting resume claims and missing skill evidence.
It does not infer sensitive attributes or make hiring decisions. Feedback hides
unwanted roles from matching and digests; it is not a trained learning system.
Semantic embeddings, calibrated reranking, OCR and application-status sync are
not implemented. Recruiter-reviewed relevance evaluation and realistic concurrent
load testing remain necessary before a large rollout.

A local synthetic run over 100,000 jobs took roughly 0.27 seconds for matching
only. This excludes database, network, parsing and concurrency; it is not a
lakh-user capacity claim. Reproduce with `python -m valases_jobs.benchmark`.

## Local preview

Run `./scripts/start_valases_jobs.ps1` from the repository root. It explicitly
migrates the dedicated local Jobs SQLite database and starts a hidden demo server
at http://127.0.0.1:8010. Demo vacancies cannot receive applications or payments.
Demo verification/recovery links are exposed only in local demo API responses;
public deployments reject demo mode. No actual email is sent from the demo.

## Public preview

Set `JOBS_PUBLIC_PREVIEW=true` in Vercel and redeploy to explore sample jobs and
matching without configuring other services. This mode has no accounts, uploads,
applications, payments or email delivery. `/ready` identifies it as a preview,
not a production-ready portal.

## Vercel deployment

See [the Vercel setup guide](valases_jobs/deploy/VERCEL.md). The web app has a
root FastAPI entry point. It requires external PostgreSQL/Redis and either
authenticated scheduled tasks or a separately hosted persistent worker.

## Connect and deploy

See `valases_jobs/deploy/README.md` for the existing-hosting deployment procedure, separate
PostgreSQL database, bridge setup, SMTP, Cashfree, worker and HTTPS routing.
Configuration template: `.env.example`. Do not commit configured secrets.
Readiness command: `python -m valases_jobs.check_launch`.

The recruiter migration is `app/db/migrations/20261007_job_marketplace.sql` in the separate [Hiring Tool repository](https://github.com/raghav150698-alt/valases).
The bridge secret must be configured server-side on both applications. Recruiters
manage publication from their requisition cards. Applications open the existing
Valases form; candidates review and submit there. Profiles are not silently
transferred and candidate/recruiter login sessions are separate.

## Validation and remaining launch work

Portal tests cover the scheduled tasks as well as accounts, catalog, matching,
payments and preview behavior. Recruiter bridge tests remain in the Hiring Tool repository.
Run `python -m unittest discover -s valases_jobs/tests` and
`node --check valases_jobs/web/app.js`. The recruiter React publication component
passes the existing TypeScript project check.

The local build does not configure real hosting, DNS, databases, SMTP senders,
payment credentials or a production vacancy connection. Those require actual
provider configuration. Complete staging delivery/checkout/application tests,
backup restore, notice review (operator identity, support and refunds), PostgreSQL
concurrency testing and relevance review before public charging. Tests use mocks
for email/payment providers and SQLite; they do not validate a live provider or
PostgreSQL locking under concurrent traffic.

The existing recruiter workspace suite has two independently reproduced failures
for Greenhouse integration, outside the Jobs changes.
