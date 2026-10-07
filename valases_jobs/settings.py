from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal
from pydantic import field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JOBS_", extra="ignore")
    database_url: str = "sqlite:///./valases_jobs.db"
    public_origin: str = "http://127.0.0.1:8010"
    valases_api_url: str = ""
    candidate_portal_url: str = ""
    bridge_key: str = ""
    demo: bool = False
    public_preview: bool = False
    secure_cookies: bool = True
    create_schema: bool = False
    redis_url: str = ""
    encryption_key: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_sender: str = ""
    support_email: str = ""
    company_name: str = "Valases"
    billing_enabled: bool = False
    cashfree_app_id: str = ""
    cashfree_secret_key: str = ""
    cashfree_environment: str = "sandbox"
    cashfree_api_version: str = "2025-01-01"
    require_verified_email: bool = True
    catalog_page_limit: int = 1000
    extraction_timeout_seconds: int = 15
    indexed_catalog: bool = False
    deployment_stage: Literal['staging','production'] = 'production'

    @field_validator("database_url", mode="before")
    @classmethod
    def use_installed_postgresql_driver(cls, value):
        # Providers often return the bare PostgreSQL scheme. Our installed
        # driver is psycopg 3, while SQLAlchemy's bare scheme selects psycopg2.
        if isinstance(value, str):
            for prefix in ("postgres://", "postgresql://"):
                if value.startswith(prefix):
                    return "postgresql+psycopg://" + value[len(prefix):]
        return value

    @property
    def checkout_ready(self):
        return self.billing_enabled and bool(self.cashfree_app_id and self.cashfree_secret_key) and not self.demo

    def launch_issues(self):
        issues = []
        if self.public_preview: issues.append("Public preview is enabled; operational launch is disabled")
        if self.demo: issues.append("Demo inventory is enabled")
        if not self.database_url.startswith("postgresql"): issues.append("Dedicated PostgreSQL database is required")
        if not self.redis_url: issues.append("Shared Redis rate limiting is not configured")
        if not self.encryption_key: issues.append("Data encryption key is missing")
        if not self.smtp_host or not self.smtp_sender: issues.append("Verification and alert email delivery is not configured")
        if not self.support_email: issues.append("Support contact is missing")
        if not self.valases_api_url or len(self.bridge_key) < 32: issues.append("Valases vacancy bridge is not configured")
        if not self.candidate_portal_url: issues.append("Candidate application portal is not configured")
        if not self.checkout_ready or (self.deployment_stage == 'production' and self.cashfree_environment != "production"): issues.append("Cashfree checkout is not configured for this deployment stage")
        if not self.require_verified_email: issues.append("Email verification must be enforced")
        if not self.indexed_catalog: issues.append('Indexed job catalog must be enabled')
        return issues

    def validate_deployment(self):
        from urllib.parse import urlsplit
        origin = urlsplit(self.public_origin)
        if not origin.hostname or origin.scheme not in {"http", "https"} or origin.path not in {"", "/"} or origin.query or origin.fragment or origin.username:
            raise ValueError("Public origin must be a plain HTTP(S) origin")
        local = origin.hostname in {"localhost", "127.0.0.1", "::1"}
        if not local and (self.demo or self.create_schema or not self.secure_cookies or origin.scheme != "https"):
            raise ValueError("Public deployments require HTTPS, secure cookies, migrations and demo mode off")
        if self.cashfree_environment not in {"sandbox", "production"}:
            raise ValueError("Unknown payment environment")
        if not local and self.launch_issues():
            raise ValueError("Launch configuration incomplete: " + "; ".join(self.launch_issues()))
        for value in (self.valases_api_url, self.candidate_portal_url):
            if value and (urlsplit(value).query or urlsplit(value).fragment or urlsplit(value).username):
                raise ValueError('Connection URLs must not contain credentials, queries or fragments')
            if value and (urlsplit(value).scheme not in {"http", "https"} or not urlsplit(value).hostname):
                raise ValueError("Invalid Valases connection URL")
            if value and not local and urlsplit(value).scheme != "https":
                raise ValueError("Public deployments require HTTPS Valases connections")
