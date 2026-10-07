"""Run independently from the web service; encrypted durable delivery and daily digests."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import logging
import secrets
import time
from uuid import uuid4

from sqlalchemy import create_engine, select, or_, delete
from sqlalchemy.orm import Session
from valases_jobs.bridge import ValasesBridge
from valases_jobs.mail import MailService
from valases_jobs.matching import match_jobs
from valases_jobs.models import Account, Profile, AlertDelivery, ActionToken, LoginSession, MatchFeedback, MailOutbox, PaymentOrder
from valases_jobs.payments import Payments
from valases_jobs.settings import Settings
from valases_jobs.vault import Vault
from valases_jobs import catalog

log = logging.getLogger('valases_jobs.worker')

def digest_one(db, config, bridge, mail):
    now = datetime.now(timezone.utc)
    profile = db.scalar(select(Profile).join(Account,Account.id == Profile.account_id).where(
        Profile.alerts_enabled.is_(True),Account.email_verified.is_(True),Account.paid_until > now,
        or_(Profile.next_digest_at.is_(None),Profile.next_digest_at <= now))
        .with_for_update(skip_locked=True).limit(1))
    if not profile: return False
    user = db.get(Account,profile.account_id)
    seen = set(db.scalars(select(AlertDelivery.job_id).where(AlertDelivery.account_id == user.id)))
    hidden = set(db.scalars(select(MatchFeedback.job_id).where(MatchFeedback.account_id == user.id)))
    resume = Vault(config).read(profile.resume_text)
    inventory = catalog.candidates(db,resume) if config.indexed_catalog else bridge.jobs()
    matches = match_jobs(resume,profile.preferences,[job for job in inventory if job['id'] not in seen|hidden])
    matches = [match for match in matches if match['band'] in {'Strong match','Related role'}][:10]
    profile.next_digest_at = now+timedelta(days=1)
    if matches:
        token = secrets.token_urlsafe(32)
        db.add(ActionToken(token_hash=sha256(token.encode()).hexdigest(),account_id=user.id,purpose='unsubscribe',expires_at=now+timedelta(days=365)))
        lines = ['New roles matching skills in your saved profile. Review employer requirements before applying.','']
        for match in matches:
            job = match['job']
            lines.extend([job['title']+' — '+job['company'],job.get('location',''),
                'Skill evidence: '+', '.join(match['matched_skills']),job.get('apply_url') or config.public_origin,''])
            db.add(AlertDelivery(id=str(uuid4()),account_id=user.id,job_id=job['id']))
        lines.extend(['Manage alerts: '+config.public_origin,
                      'Unsubscribe: '+config.public_origin+'/#unsubscribe_token='+token])
        mail.enqueue(db,user,'Your new Valases Jobs matches','\n'.join(lines),'digest:'+user.id+':'+str(uuid4()))
    db.commit(); return True

def cleanup(db):
    now = datetime.now(timezone.utc)
    db.execute(delete(LoginSession).where(LoginSession.expires_at < now))
    db.execute(delete(ActionToken).where(ActionToken.expires_at < now))
    db.execute(delete(MailOutbox).where(MailOutbox.status.in_(['sent','failed','cancelled']),MailOutbox.available_at < now-timedelta(days=30)))
    db.commit()

def main():
    config=Settings(); config.validate_deployment()
    engine=create_engine(config.database_url,pool_pre_ping=True)
    mail=MailService(config); bridge=ValasesBridge(config)
    logging.basicConfig(level=logging.INFO)
    last_cleanup=0
    last_sync=-60
    last_reconcile=0
    while True:
        try:
            with Session(engine) as db:
                if config.indexed_catalog and time.monotonic()-last_sync > 60:
                    catalog.refresh(db,bridge);last_sync=time.monotonic()
                if config.checkout_ready and time.monotonic()-last_reconcile>300:
                    ids=list(db.scalars(select(PaymentOrder.id).where(PaymentOrder.status.in_(['created','active','pending']),PaymentOrder.created_at>datetime.now(timezone.utc)-timedelta(days=2)).order_by(PaymentOrder.created_at).limit(100)))
                    for order_id in ids: Payments(config).verify(db,order_id)
                    last_reconcile=time.monotonic()
                delivered=mail.deliver_one(db)
                digested=digest_one(db,config,bridge,mail) if not config.demo else False
                if time.monotonic()-last_cleanup > 3600:
                    cleanup(db); last_cleanup=time.monotonic()
            if not delivered and not digested: time.sleep(10)
        except Exception:
            # Never log resumes, tokens, recipient addresses or provider credentials.
            log.error('Worker operation failed; retrying in 30 seconds')
            time.sleep(30)

if __name__ == '__main__': main()
