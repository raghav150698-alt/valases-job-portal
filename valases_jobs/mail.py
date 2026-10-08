"""Durable encrypted email outbox. Web requests never send email directly."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import secrets
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select, update, or_, and_
from valases_jobs.models import ActionToken, MailOutbox, Account, Profile


class MailService:
    def __init__(self, settings):
        self.settings = settings
        self.cipher = Fernet(settings.encryption_key.encode()) if settings.encryption_key else None

    def enqueue(self, db, user, subject, body, key):
        if not self.cipher:
            if self.settings.demo:
                return  # Local demo links are returned explicitly; no email is sent.
            raise RuntimeError("Email encryption is not configured")
        db.add(MailOutbox(id=str(uuid4()), account_id=user.id, dedupe_key=key,
            encrypted_payload=self.cipher.encrypt(json.dumps({"to":user.email,"subject":subject,"body":body}).encode()).decode(),
            available_at=datetime.now(timezone.utc)))

    def action(self, db, user, purpose):
        token = secrets.token_urlsafe(32)
        db.add(ActionToken(token_hash=sha256(token.encode()).hexdigest(), account_id=user.id, purpose=purpose,
                           expires_at=datetime.now(timezone.utc)+timedelta(minutes=30 if purpose == "reset" else 1440)))
        link = self.settings.public_origin.rstrip("/") + "/#" + purpose + "_token=" + token
        subject = "Verify your Valases Jobs email" if purpose == "verify" else "Reset your Valases Jobs password"
        self.enqueue(db,user,subject,f"{subject}\n\nOpen this link:\n{link}\n\nIf you did not request this, ignore this email.","action:"+sha256(token.encode()).hexdigest())
        return link

    def deliver_one(self, db, *, timeout=20):
        if self.settings.demo or not self.cipher or not self.settings.smtp_host:
            return False
        now = datetime.now(timezone.utc)
        row = db.scalar(select(MailOutbox).where(or_(MailOutbox.status == 'pending',and_(MailOutbox.status == 'sending',MailOutbox.lease_until <= now)), MailOutbox.available_at <= now)
            .order_by(MailOutbox.available_at).with_for_update(skip_locked=True))
        if not row:
            return False
        if row.status == "sending" and row.lease_until and row.lease_until.replace(tzinfo=timezone.utc) > now:
            db.rollback()
            return False
        row.status="sending"; row.lease_until=now+timedelta(minutes=2); row.attempts += 1
        db.commit()
        try:
            if row.dedupe_key.startswith('digest:'):
                profile=db.get(Profile,row.account_id);user=db.get(Account,row.account_id)
                if not profile or not profile.alerts_enabled or not user or not user.email_verified or not user.paid_until or user.paid_until.replace(tzinfo=timezone.utc)<=now:
                    row.status='cancelled';row.encrypted_payload='';row.lease_until=None;db.commit();return True
            payload=json.loads(self.cipher.decrypt(row.encrypted_payload.encode()))
            message=EmailMessage(); message["To"]=payload["to"]; message["From"]=self.settings.smtp_sender
            sender_domain=parseaddr(self.settings.smtp_sender)[1].rsplit('@',1)[-1]
            message["Subject"]=payload["subject"]; message["Message-ID"]=f"<{row.id}@{sender_domain}>"
            message.set_content(payload["body"])
            with smtplib.SMTP(self.settings.smtp_host,self.settings.smtp_port,timeout=timeout) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                if self.settings.smtp_username:
                    smtp.login(self.settings.smtp_username,self.settings.smtp_password)
                smtp.send_message(message)
            row.status="sent"; row.encrypted_payload=""; row.lease_until=None
        except (OSError,smtplib.SMTPException):
            row.status="failed" if row.attempts >= 6 else "pending"
            row.available_at=now+timedelta(minutes=min(60,2**row.attempts)); row.lease_until=None
        except (InvalidToken,ValueError,KeyError):
            row.status='failed';row.lease_until=None
        db.commit()
        return True
