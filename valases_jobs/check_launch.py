"""Readiness check that never prints configured secrets or candidate data."""
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import Session
from valases_jobs.settings import Settings
from valases_jobs.models import Account,MailOutbox
from valases_jobs import catalog

def main():
    config=Settings();issues=config.launch_issues()
    try:config.validate_deployment()
    except ValueError:issues.append('Deployment settings failed validation')
    try:
        import redis
        if config.redis_url:redis.Redis.from_url(config.redis_url,socket_timeout=3).ping()
    except Exception:issues.append('Redis unavailable')
    try:
        with Session(create_engine(config.database_url,pool_pre_ping=True)) as db:
            db.execute(select(Account.id).limit(1))
            if config.indexed_catalog:catalog.require_fresh(db)
            if db.scalar(select(func.count()).select_from(MailOutbox).where(MailOutbox.status=='failed')):
                issues.append('Email delivery failures require attention')
    except Exception:issues.append('Database/schema or fresh job catalog unavailable')
    for issue in dict.fromkeys(issues):print('BLOCKED: '+issue)
    if issues:return 1
    print(config.deployment_stage.title()+' configuration and dependencies ready. Complete checkout, email and application smoke tests before launch.')
    return 0

if __name__=='__main__':raise SystemExit(main())
