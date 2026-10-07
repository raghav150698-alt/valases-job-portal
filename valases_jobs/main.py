from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from hashlib import pbkdf2_hmac, sha256
import hmac
from pathlib import Path
import secrets
import time
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, Response, UploadFile, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import create_engine, delete, select, update, text as sql_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from valases_jobs.bridge import ValasesBridge
from valases_jobs.matching import match_jobs
from valases_jobs.models import Account, Base, LoginSession, Profile, SavedJob, ActionToken, MailOutbox, PaymentOrder, AlertDelivery, MatchFeedback
from valases_jobs.mail import MailService
from valases_jobs.features import install
from valases_jobs.vault import Vault
from valases_jobs.body_limit import BodyLimit
from valases_jobs import catalog
from valases_jobs.pages import install_pages
from valases_jobs.settings import Settings

WEB = Path(__file__).parent / "web"


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=200)
    name: str = Field(default="Candidate", min_length=1, max_length=160)
    accepted_terms: bool = False


class Preferences(BaseModel):
    location: str = Field(default="", max_length=180)
    work_arrangement: str = Field(default="any", pattern="^(any|remote|hybrid|on_site)$")
    experience_years: float | None = Field(default=None, ge=0, le=80)


class ProfileInput(BaseModel):
    resume_text: str = Field(default="", max_length=120000)
    preferences: Preferences = Field(default_factory=Preferences)


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt + ":" + pbkdf2_hmac("sha256", password.encode(), salt.encode(), 600000).hex()


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def create_app(settings=None, engine=None):
    config = settings or Settings()
    config.validate_deployment()
    engine = engine or create_engine(config.database_url, pool_pre_ping=True,
        connect_args={"check_same_thread": False} if config.database_url.startswith("sqlite") else {})
    sessions = sessionmaker(bind=engine)
    bridge = ValasesBridge(config)
    mail = MailService(config)
    vault = Vault(config)
    shared_limiter = None
    if config.redis_url:
        import redis
        shared_limiter = redis.Redis.from_url(config.redis_url, socket_timeout=2, socket_connect_timeout=2)

    @asynccontextmanager
    async def lifespan(application):
        if config.create_schema:
            Base.metadata.create_all(engine)
        yield

    app = FastAPI(title="Valases Jobs", lifespan=lifespan)
    app.add_middleware(BodyLimit)
    app.state.bridge = bridge
    attempts = defaultdict(deque)
    dummy_hash = password_hash("unused-local-comparison-secret")

    @app.middleware("http")
    async def protections(request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if (origin and origin.rstrip("/") != config.public_origin.rstrip("/")) or request.headers.get('sec-fetch-site') == 'cross-site':
                return JSONResponse({"detail": "Cross-origin writes are not allowed"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' https://sdk.cashfree.com; style-src 'self'; img-src 'self' data:; frame-src https://*.cashfree.com; connect-src 'self' https://*.cashfree.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self' https://*.cashfree.com"
        if config.secure_cookies: response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def db_session():
        with sessions() as db:
            yield db

    def account(request: Request, db: Session = Depends(db_session)):
        token = request.cookies.get("jobs_session", "")
        login = db.get(LoginSession, sha256(token.encode()).hexdigest()) if token else None
        if not login or aware(login.expires_at) <= datetime.now(timezone.utc):
            raise HTTPException(401, "Sign in to continue")
        user = db.get(Account, login.account_id)
        if not user:
            raise HTTPException(401, "Sign in to continue")
        return user

    def limit(request, bucket, maximum):
        key = (request.client.host if request.client else "unknown", bucket)
        if shared_limiter:
            try:
                redis_key = 'jobs:limit:' + sha256(str(key).encode()).hexdigest() + ':' + str(int(time.time())//60)
                count = shared_limiter.eval("local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],120) end; return n", 1, redis_key)
            except Exception:
                raise HTTPException(503, 'Please retry shortly') from None
            if count > maximum: raise HTTPException(429,'Too many requests; retry in a minute')
            return
        now = time.monotonic()
        # Bounded pilot-only limiter. Use a shared gateway/Redis limiter at deployment.
        if len(attempts) > 10000:
            for old_key in list(attempts):
                if not attempts[old_key] or attempts[old_key][-1] < now - 60:
                    attempts.pop(old_key, None)
            if len(attempts) > 10000:
                raise HTTPException(429, "Service is busy; retry shortly")
        queue = attempts[key]
        while queue and queue[0] < now - 60:
            queue.popleft()
        if len(queue) >= maximum:
            raise HTTPException(429, "Too many requests; retry in a minute")
        queue.append(now)

    def issue_session(db, user, response):
        token = secrets.token_urlsafe(32)
        db.add(LoginSession(token_hash=sha256(token.encode()).hexdigest(), account_id=user.id,
                            expires_at=datetime.now(timezone.utc) + timedelta(days=7)))
        db.commit()
        response.set_cookie("jobs_session", token, httponly=True, secure=config.secure_cookies,
                            samesite="lax", max_age=7 * 86400)
        return {"name": user.name, "email": user.email, 'email_verified':user.email_verified}

    @app.get("/api/config")
    def public_config():
        return {"name": "Valases Jobs", "domain": "jobs.valases.com", "demo": config.demo,
                "monthly_price_inr": 79, "checkout_enabled": config.checkout_ready, 'support_email':config.support_email,
                "connected": bool(config.valases_api_url and config.bridge_key),
                "matching_version": "skills-evidence-v2"}

    @app.post("/api/auth/register", status_code=201)
    def register(body: Credentials, request: Request, response: Response, db: Session = Depends(db_session)):
        limit(request, "auth", 10)
        if not body.accepted_terms: raise HTTPException(422,'Accept the terms and privacy notice to create an account')
        user = Account(id=str(uuid4()), email=str(body.email).lower(), name=body.name.strip(),
                       password_hash=password_hash(body.password),terms_version='2026-10-07',terms_accepted_at=datetime.now(timezone.utc))
        db.add(user)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Account could not be created; try signing in") from None
        link = mail.action(db,user,'verify')
        result = issue_session(db, user, response)
        if config.demo: result['demo_link'] = link
        return result

    @app.post("/api/auth/login")
    def login(body: Credentials, request: Request, response: Response, db: Session = Depends(db_session)):
        limit(request, "auth", 10)
        user = db.scalar(select(Account).where(Account.email == str(body.email).lower()))
        saved_hash = user.password_hash if user else dummy_hash
        valid = hmac.compare_digest(password_hash(body.password, saved_hash.split(":")[0]), saved_hash)
        if not user or not valid:
            raise HTTPException(401, "Invalid email or password")
        return issue_session(db, user, response)

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response, db: Session = Depends(db_session)):
        token = request.cookies.get("jobs_session", "")
        db.execute(delete(LoginSession).where(LoginSession.token_hash == sha256(token.encode()).hexdigest()))
        db.commit()
        response.delete_cookie("jobs_session", secure=config.secure_cookies, httponly=True, samesite="lax")
        return {"ok": True}

    @app.get("/api/me")
    def me(user: Account = Depends(account), db: Session = Depends(db_session)):
        profile = db.get(Profile, user.id)
        return {"name": user.name, "email": user.email, 'email_verified':user.email_verified,
            'paid_until':user.paid_until, 'plan_active':bool(user.paid_until and aware(user.paid_until)>datetime.now(timezone.utc)), "profile": {
            "resume_text": vault.read(profile.resume_text) if profile else "",
            "preferences": profile.preferences if profile else {}, 'alerts_enabled':bool(profile and profile.alerts_enabled)},
            "saved_jobs": list(db.scalars(select(SavedJob.job_id).where(SavedJob.account_id == user.id)))}

    @app.put("/api/me/profile")
    def update_profile(body: ProfileInput, request: Request, user: Account = Depends(account), db: Session = Depends(db_session)):
        limit(request,'profile',20)
        profile = db.get(Profile, user.id)
        if not profile:
            profile = Profile(account_id=user.id)
            db.add(profile)
        profile.resume_text = vault.store(body.resume_text)
        profile.preferences = body.preferences.model_dump()
        db.commit()
        return {"ok": True}

    @app.delete("/api/me")
    def delete_account(response: Response, user: Account = Depends(account), db: Session = Depends(db_session)):
        db.execute(update(PaymentOrder).where(PaymentOrder.account_id == user.id).values(account_id=None,session_id=None))
        for model in (SavedJob, Profile, LoginSession, ActionToken, MailOutbox, AlertDelivery, MatchFeedback):
            db.execute(delete(model).where(model.account_id == user.id))
        db.delete(user)
        db.commit()
        response.delete_cookie("jobs_session")
        return {"ok": True, "message": "Jobs account deleted. Applications previously sent to employers remain with those employers."}

    @app.get("/api/jobs")
    def jobs(q: str = Query('',max_length=200), location: str = Query('',max_length=180),
             offset: int = Query(0,ge=0), limit: int = Query(50,ge=1,le=100),
             arrangement: str = '', employment_type: str = '', db: Session = Depends(db_session)):
        if config.indexed_catalog:
            return {**catalog.search(db,q,location,arrangement,employment_type,offset,limit),'demo':False,'paginated':True}
        items = [job for job in bridge.jobs() if q.lower() in (job["title"] + " " + job["company"]).lower()
                 and location.lower() in job.get("location", "").lower()]
        return {"items": items, "demo": config.demo}

    @app.post("/api/matches/preview")
    def preview(body: ProfileInput, request: Request, db: Session = Depends(db_session)):
        limit(request, "matches", 20)
        if len(body.resume_text.strip()) < 20:
            raise HTTPException(422, "Add at least 20 characters of resume or experience text")
        inventory = catalog.candidates(db,body.resume_text) if config.indexed_catalog else bridge.jobs()
        results = match_jobs(body.resume_text, body.preferences.model_dump(), inventory)
        return {"items": results[:3], "total": len(results), "preview": True, "demo": config.demo}

    @app.get("/api/me/matches")
    def full_matches(request: Request, offset: int = Query(0,ge=0), page_size: int = Query(50,ge=1,le=100,alias='limit'), user: Account = Depends(account), db: Session = Depends(db_session)):
        limit(request,'matches',20)
        if not user.paid_until or aware(user.paid_until) <= datetime.now(timezone.utc):
            raise HTTPException(402, "Full matching requires an active 30-day plan.")
        profile = db.get(Profile, user.id)
        if not profile:
            raise HTTPException(409, "Save your profile first")
        hidden = set(db.scalars(select(MatchFeedback.job_id).where(MatchFeedback.account_id == user.id)))
        resume = vault.read(profile.resume_text)
        inventory = catalog.candidates(db,resume) if config.indexed_catalog else bridge.jobs()
        results = match_jobs(resume, profile.preferences, [job for job in inventory if job['id'] not in hidden])
        return {"items": results[offset:offset+page_size], 'total':len(results), 'offset':offset,'limit':page_size, "preview": False}

    @app.get('/api/me/saved')
    def saved(user: Account = Depends(account), db: Session = Depends(db_session)):
        ids=set(db.scalars(select(SavedJob.job_id).where(SavedJob.account_id == user.id)))
        if config.indexed_catalog:
            from valases_jobs.models import CatalogJob
            catalog.require_fresh(db)
            return {'items':[row.payload for row in db.scalars(select(CatalogJob).where(CatalogJob.id.in_(ids)))]}
        return {'items':[job for job in bridge.jobs() if job['id'] in ids]}

    @app.put("/api/me/saved/{job_id}")
    def save_job(job_id: str, user: Account = Depends(account), db: Session = Depends(db_session)):
        from valases_jobs.models import CatalogJob
        if config.indexed_catalog: catalog.require_fresh(db)
        exists = db.get(CatalogJob,job_id) is not None if config.indexed_catalog else job_id in {job['id'] for job in bridge.jobs()}
        if not exists:
            raise HTTPException(404, "This job is no longer available")
        existing = db.scalar(select(SavedJob).where(SavedJob.account_id == user.id, SavedJob.job_id == job_id))
        if not existing:
            db.add(SavedJob(id=str(uuid4()), account_id=user.id, job_id=job_id))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()  # Concurrent saves are idempotent.
        return {"ok": True}

    @app.delete("/api/me/saved/{job_id}")
    def unsave_job(job_id: str, user: Account = Depends(account), db: Session = Depends(db_session)):
        db.execute(delete(SavedJob).where(SavedJob.account_id == user.id, SavedJob.job_id == job_id))
        db.commit()
        return {"ok": True}

    @app.post("/api/resume/extract")
    def extract(request: Request, file: UploadFile):
        limit(request, "uploads", 10)
        content = file.file.read(2 * 1024 * 1024 + 1)
        if len(content) > 2 * 1024 * 1024:
            raise HTTPException(413, "Resume must be under 2 MB")
        suffix = Path(file.filename or "").suffix.lower()
        from valases_jobs.resume import extract_text
        text = extract_text(content, suffix, config.extraction_timeout_seconds)
        return {"resume_text": text, "message": "Review the extracted text before matching. The file is not stored."}

    @app.get("/health")
    def health():
        with engine.connect() as connection: connection.execute(sql_text('SELECT 1'))
        return {"status": "ok", "product": "Valases Jobs", "demo": config.demo}

    @app.get('/ready')
    def ready():
        issues = config.launch_issues()
        try:
            with engine.connect() as connection: connection.execute(select(Account.id).limit(1))
            if shared_limiter: shared_limiter.ping()
            if config.indexed_catalog:
                with sessions() as db: catalog.require_fresh(db)
        except Exception: issues.append('Database schema or shared limiter unavailable')
        return JSONResponse({'ready':not issues},status_code=503 if issues else 200)

    install(app, config, account, db_session, limit, mail, password_hash, vault)
    install_pages(app,config)

    app.mount("/assets", StaticFiles(directory=WEB), name="assets")

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    return app


app = create_app()
