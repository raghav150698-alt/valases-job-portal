# Deploy alongside existing Valases hosting

Docker is optional. Keep this app in a separate process with its own PostgreSQL
database/role. Reuse the current hosting account, reverse proxy and mail provider
when appropriate. Do not run candidate migrations against the recruiter database.

## A server that supports Python background services

1. Copy the `valases_jobs` package to `/srv/valases-jobs/valases_jobs`. Create a
   dedicated `valases-jobs` OS user and virtual environment in `/srv/valases-jobs/.venv`.
2. Install `valases_jobs/requirements.txt` with that environment's pip.
3. Create a dedicated PostgreSQL database and restricted database user. Reuse
   existing Redis with a separate key namespace and credentials. Do not expose
   PostgreSQL or Redis publicly.
4. Copy `.env.example` to `/etc/valases-jobs.env`, fill real values and restrict
   permissions to the operator/service user. No secrets belong in Git or UI config.
   Preserve the Fernet key separately from database backups. It encrypts resumes
   and queued email; key rotation requires a data re-encryption migration.
5. Set production origin to the purchased domain. Set Valases API root and
   candidate portal URL to the actual deployed application form (include its
   path prefix, such as `/assessment`, if applicable).
6. On the recruiter backend, apply the reviewed
   `app/db/migrations/20261007_job_marketplace.sql` and deploy its bridge routes
   and publication component. Set the same dedicated `JOBS_BRIDGE_KEY` there.
7. Load the Jobs environment into a restricted shell and run:
   `python -m valases_jobs.migrate`. This creates the Jobs tables and upgrades
   existing pilot columns, preserving accounts and encrypting existing resume
   text when the encryption key is configured. Back up first.
8. Install the two supplied systemd units, adjusting paths/users for the host.
   Start the worker first; it synchronizes explicitly published jobs. Start the
   web service after a successful initial synchronization.
9. Merge the supplied Caddy host block into the existing proxy (or equivalent
   nginx configuration). Point DNS at the host and obtain HTTPS. Restrict the
   backend listener to loopback; trust only the actual proxy IP for forwarded IPs.
10. Configure a verified SMTP sender with SPF/DKIM/DMARC. Configure the Cashfree
    production account, approved domain, credentials and payment webhook. This
    release uses hosted checkout, INR 79 fixed-price orders and manual renewal.
11. Run `python -m valases_jobs.check_launch`; monitor `/health` and `/ready`.
    Readiness returns 503 for missing configuration, schema, Redis or stale catalog.

## If current hosting is serverless

The web app is ASGI, but the supplied worker expects a persistent process.
Do not put the worker loop inside a serverless request. Use an existing worker
host, or adapt synchronization/outbox delivery into bounded scheduled jobs with
the provider's supported scheduler. PDF extraction also requires subprocess
support. The provider must be confirmed before that deployment is configured.

## Release checks

- Register a disposable staging candidate, verify delivery and reset password.
  Confirm old sessions cannot access the account after reset.
- Publish and unpublish a real authorized vacancy; verify it reaches/disappears
  from the portal. Catalog refresh is every minute; snapshots become unavailable
  after ten minutes without a successful sync. Application submission remains
  under the existing employer application form and checks vacancy availability.
- Complete an authorized test payment in the chosen payment environment. Replay
  its webhook; access must be added only once. Confirm invalid amounts/signatures
  never grant access. Verify pending/cancelled orders and successful return flow.
- Enable daily alerts, verify actual inbox delivery, disable them, and check no
  further queued digest is sent. Outbox delivery is at least once: rare duplicates
  can occur if SMTP succeeds immediately before a worker crash.
- Confirm account export/deletion, mobile layout, published service notices and
  support contact. Operator identity, refund handling and backup-retention details
  in the notices must reflect the actual business before charging candidates.
- Run realistic concurrent PostgreSQL/Redis load tests and recruiter-reviewed
  matching evaluation before a large rollout. The synthetic matching benchmark
  excludes networking, database retrieval, extraction and concurrent traffic.

## Operations and recovery

Schedule encrypted PostgreSQL backups using the hosting provider or `pg_dump`;
retain according to the published backup policy. Test restoration into an isolated
database plus restoration of the encryption key. A backup that has never been
restored is unverified. Monitor readiness, synchronization freshness, failed mail,
pending payments and process restarts. The worker retries mail with backoff,
reconciles recent pending orders every five minutes and cleans expired sessions,
action tokens and old completed email records hourly.

Rollback by switching the application release and restarting the two services.
These schema changes are additive; avoid destructive rollback migrations.
Keep the previous release and backup until the new one passes live smoke tests.
No domain, production database, payment credentials or hosting has been modified
by the local build.
