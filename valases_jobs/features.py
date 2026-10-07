"""Account recovery, consent and server-verified 30-day access."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from uuid import uuid4

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session
from valases_jobs.models import Account, ActionToken, LoginSession, Profile, PaymentOrder, MatchFeedback
from valases_jobs.payments import Payments

class EmailInput(BaseModel):
    email: EmailStr
class TokenInput(BaseModel):
    token: str = Field(min_length=20, max_length=200)
class ResetInput(TokenInput):
    password: str = Field(min_length=12, max_length=200)
class CheckoutInput(BaseModel):
    phone: str = Field(pattern=r"^[6-9][0-9]{9}$")
    idempotency_key: str = Field(min_length=16, max_length=80)
class AlertInput(BaseModel):
    enabled: bool
class FeedbackInput(BaseModel):
    job_id: str = Field(min_length=1, max_length=100)
    reason: str = Field(pattern="^(irrelevant|wrong_location|too_senior|not_interested)$")

def install(app, config, account, db_session, limit, mail, hash_password, vault):
    payments = Payments(config)
    def consume(db, token, purpose):
        now = datetime.now(timezone.utc)
        key = sha256(token.encode()).hexdigest()
        row = db.get(ActionToken, key)
        if not row or row.purpose != purpose:
            raise HTTPException(400, "Link is invalid or expired")
        result = db.execute(update(ActionToken).where(ActionToken.token_hash == key,
            ActionToken.used_at.is_(None), ActionToken.expires_at > now).values(used_at=now).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            raise HTTPException(400, "Link is invalid or expired")
        return db.get(Account, row.account_id)

    @app.post('/api/auth/verify')
    def verify(body: TokenInput, db: Session = Depends(db_session)):
        user = consume(db, body.token, 'verify')
        user.email_verified = True
        db.commit()
        return {'ok': True}

    @app.post('/api/auth/verification')
    def verification(request: Request, user: Account = Depends(account), db: Session = Depends(db_session)):
        limit(request, 'mail', 3)
        if user.email_verified: return {'ok': True}
        link = mail.action(db, user, 'verify'); db.commit()
        return {'ok': True, **({'demo_link': link} if config.demo else {})}

    @app.post('/api/auth/forgot-password')
    def forgot(body: EmailInput, request: Request, db: Session = Depends(db_session)):
        limit(request, 'mail', 3)
        user = db.scalar(select(Account).where(Account.email == str(body.email).lower()))
        link = mail.action(db, user, 'reset') if user else None
        db.commit()
        return {'message': 'If that account exists, a reset link will be emailed.',
                **({'demo_link': link} if config.demo and link else {})}

    @app.post('/api/auth/reset-password')
    def reset(body: ResetInput, request: Request, db: Session = Depends(db_session)):
        limit(request, 'auth', 10)
        user = consume(db, body.token, 'reset')
        user.password_hash = hash_password(body.password)
        db.execute(delete(LoginSession).where(LoginSession.account_id == user.id))
        db.execute(update(ActionToken).where(ActionToken.account_id == user.id,
            ActionToken.purpose == 'reset', ActionToken.used_at.is_(None)).values(used_at=datetime.now(timezone.utc)))
        db.commit()
        return {'ok': True}

    @app.put('/api/me/alerts')
    def alerts(body: AlertInput, user: Account = Depends(account), db: Session = Depends(db_session)):
        profile = db.get(Profile, user.id)
        if not profile or len(vault.read(profile.resume_text).strip()) < 20:
            raise HTTPException(409, 'Save your resume profile first')
        if body.enabled:
            if not user.email_verified: raise HTTPException(403, 'Verify your email first')
            now = datetime.now(timezone.utc)
            paid = user.paid_until
            if not paid or paid.replace(tzinfo=timezone.utc) <= now: raise HTTPException(402, 'An active plan is required')
        profile.alerts_enabled = body.enabled
        profile.next_digest_at = datetime.now(timezone.utc) if body.enabled else None
        db.commit()
        return {'enabled': profile.alerts_enabled}

    @app.post('/api/alerts/unsubscribe')
    def unsubscribe(body: TokenInput, db: Session = Depends(db_session)):
        # Signed random link stays valid for repeated opt-out requests until expiry.
        row = db.get(ActionToken, sha256(body.token.encode()).hexdigest())
        if not row or row.purpose != 'unsubscribe' or row.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
            raise HTTPException(400, 'Unsubscribe link expired; sign in to disable alerts')
        profile = db.get(Profile, row.account_id)
        if profile: profile.alerts_enabled = False; profile.next_digest_at = None
        db.commit(); return {'ok': True}

    @app.post('/api/me/feedback')
    def feedback(body: FeedbackInput, request: Request, user: Account = Depends(account), db: Session = Depends(db_session)):
        limit(request,'feedback',30)
        db.add(MatchFeedback(id=str(uuid4()), account_id=user.id, job_id=body.job_id,
            reason=body.reason, created_at=datetime.now(timezone.utc)))
        db.commit(); return {'ok': True}

    @app.delete('/api/me/feedback/{job_id}')
    def undo_feedback(job_id: str, user: Account = Depends(account), db: Session = Depends(db_session)):
        db.execute(delete(MatchFeedback).where(MatchFeedback.account_id==user.id,MatchFeedback.job_id==job_id))
        db.commit(); return {'ok':True}

    @app.get('/api/me/export')
    def export(user: Account = Depends(account), db: Session = Depends(db_session)):
        from fastapi.responses import JSONResponse
        from valases_jobs.models import SavedJob, AlertDelivery
        profile = db.get(Profile, user.id)
        orders = db.scalars(select(PaymentOrder).where(PaymentOrder.account_id == user.id))
        return JSONResponse({'account': {'name':user.name,'email':user.email,'verified':user.email_verified,
                'paid_until':user.paid_until.isoformat() if user.paid_until else None,
                'terms_version':user.terms_version,'terms_accepted_at':user.terms_accepted_at.isoformat() if user.terms_accepted_at else None},
            'profile': {'resume_text': vault.read(profile.resume_text), 'preferences':profile.preferences,
                'alerts_enabled':profile.alerts_enabled} if profile else None,
            'saved_jobs':list(db.scalars(select(SavedJob.job_id).where(SavedJob.account_id == user.id))),
            'alerted_job_ids':list(db.scalars(select(AlertDelivery.job_id).where(AlertDelivery.account_id == user.id))),
            'feedback':[{'job_id':row.job_id,'reason':row.reason,'created_at':row.created_at.isoformat()} for row in db.scalars(select(MatchFeedback).where(MatchFeedback.account_id==user.id))],
            'payments':[{'id':row.id,'amount_minor':row.amount_minor,'currency':row.currency,'status':row.status} for row in orders]},
            headers={'Content-Disposition':'attachment; filename="valases-jobs-data.json"'})

    @app.post('/api/billing/orders')
    def checkout(body: CheckoutInput, request: Request, user: Account = Depends(account), db: Session = Depends(db_session)):
        limit(request, 'checkout', 5)
        if config.require_verified_email and not user.email_verified: raise HTTPException(403,'Verify your email first')
        row = payments.create(db, user, body.phone, body.idempotency_key)
        return {'order_id': row.id, 'payment_session_id':row.session_id, 'mode':config.cashfree_environment}

    @app.post('/api/billing/orders/{order_id}/verify')
    def verify_order(order_id: str, user: Account = Depends(account), db: Session = Depends(db_session)):
        row = db.get(PaymentOrder, order_id)
        if not row or row.account_id != user.id: raise HTTPException(404,'Order not found')
        row = payments.verify(db, order_id)
        return {'status':row.status, 'granted':bool(row.granted_at)}

    @app.post('/api/billing/webhook')
    async def webhook(request: Request, db: Session = Depends(db_session)):
        raw = await request.body()
        if not payments.verify_signature(raw,request.headers.get('x-webhook-timestamp',''),request.headers.get('x-webhook-signature','')):
            raise HTTPException(401,'Invalid webhook signature')
        try: order_id = json.loads(raw)['data']['order']['order_id']
        except (ValueError, KeyError, TypeError): raise HTTPException(400,'Malformed webhook') from None
        if not isinstance(order_id,str) or len(order_id)>64: raise HTTPException(400,'Malformed order')
        from starlette.concurrency import run_in_threadpool
        await run_in_threadpool(payments.verify,db,order_id)
        return {'ok':True}
