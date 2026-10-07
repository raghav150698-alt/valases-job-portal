from datetime import datetime
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "jobs_accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(String(160))
    paid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    terms_version: Mapped[str | None] = mapped_column(String(30),nullable=True)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),nullable=True)


class LoginSession(Base):
    __tablename__ = "jobs_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("jobs_accounts.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Profile(Base):
    __tablename__ = "jobs_profiles"
    account_id: Mapped[str] = mapped_column(ForeignKey("jobs_accounts.id"), primary_key=True)
    resume_text: Mapped[str] = mapped_column(Text, default="")
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    alerts_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    next_digest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class SavedJob(Base):
    __tablename__ = "jobs_saved_jobs"
    __table_args__ = (UniqueConstraint("account_id", "job_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("jobs_accounts.id"), index=True)
    job_id: Mapped[str] = mapped_column(String(100))


class ActionToken(Base):
    __tablename__ = "jobs_action_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("jobs_accounts.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(24))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MailOutbox(Base):
    __tablename__ = "jobs_mail_outbox"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("jobs_accounts.id"), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(180), unique=True)
    encrypted_payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PaymentOrder(Base):
    __tablename__ = "jobs_payment_orders"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("jobs_accounts.id"), nullable=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    amount_minor: Mapped[int] = mapped_column(Integer, default=7900)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[str] = mapped_column(String(24), default="created")
    session_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AlertDelivery(Base):
    __tablename__ = "jobs_alert_deliveries"
    __table_args__ = (UniqueConstraint("account_id", "job_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("jobs_accounts.id"), index=True)
    job_id: Mapped[str] = mapped_column(String(100))


class MatchFeedback(Base):
    __tablename__ = "jobs_match_feedback"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("jobs_accounts.id"), index=True)
    job_id: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class CatalogJob(Base):
    __tablename__ = 'jobs_catalog'
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
    search_text: Mapped[str] = mapped_column(Text)
    location: Mapped[str] = mapped_column(String(200))
    arrangement: Mapped[str] = mapped_column(String(30),index=True)
    employment_type: Mapped[str] = mapped_column(String(30),index=True)

class CatalogSkill(Base):
    __tablename__ = 'jobs_catalog_skills'
    job_id: Mapped[str] = mapped_column(ForeignKey('jobs_catalog.id'),primary_key=True)
    skill: Mapped[str] = mapped_column(String(200),primary_key=True,index=True)

class CatalogState(Base):
    __tablename__ = 'jobs_catalog_state'
    id: Mapped[int] = mapped_column(Integer,primary_key=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
