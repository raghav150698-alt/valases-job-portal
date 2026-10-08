"""Small authenticated tasks for serverless hosts; never start an infinite worker."""
from datetime import datetime, timedelta, timezone
import hmac
import logging
import time
from typing import Literal

from fastapi import HTTPException, Request
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from valases_jobs import catalog
from valases_jobs.bridge import ValasesBridge
from valases_jobs.mail import MailService
from valases_jobs.models import PaymentOrder
from valases_jobs.payments import Payments
from valases_jobs.worker import cleanup, digest_one

Task = Literal['mail', 'catalog', 'digest', 'payments', 'cleanup']
LOCKS = {'mail': 794081, 'catalog': 794082, 'digest': 794083,
         'payments': 794084, 'cleanup': 794085}
log = logging.getLogger(__name__)


class BoundedBridge(ValasesBridge):
    def jobs(self):
        return super().jobs(deadline=time.monotonic() + 25)


def run_task(task, db, config):
    """One unit per request, except the atomic catalog snapshot and cleanup."""
    if task == 'mail':
        return int(MailService(config).deliver_one(db, timeout=5))
    if task == 'catalog':
        if not config.indexed_catalog:
            return 0
        return int(catalog.refresh(db, BoundedBridge(config)))
    if task == 'digest':
        if config.demo or not config.indexed_catalog:
            return 0
        return int(digest_one(db, config, ValasesBridge(config), MailService(config)))
    if task == 'payments':
        if not config.checkout_ready:
            return 0
        ids = list(db.scalars(select(PaymentOrder.id).where(
            PaymentOrder.status.in_(['created', 'active', 'pending']),
            PaymentOrder.created_at > datetime.now(timezone.utc) - timedelta(days=2)
        ).order_by(PaymentOrder.created_at, PaymentOrder.id).limit(100)))
        if not ids:
            return 0
        # Rotate through the bounded pending set rather than repeatedly checking
        # the oldest unpaid order. Signed webhooks remain the primary path.
        order_id = ids[int(time.time() // 60) % len(ids)]
        Payments(config).verify(db, order_id, timeout=5)
        return 1
    cleanup(db)
    return 1


def execute_task(task, config, engine):
    with engine.connect() as connection:
        postgres = connection.dialect.name == 'postgresql'
        locked = False
        try:
            if postgres:
                locked = bool(connection.scalar(text('SELECT pg_try_advisory_lock(:key)'),
                                                {'key': LOCKS[task]}))
                connection.commit()
                if not locked:
                    return {'ok': True, 'task': task, 'processed': 0, 'busy': True}
            with Session(bind=connection) as db:
                if postgres:
                    # Persistent for this checked-out session across task commits.
                    connection.execute(text("SET statement_timeout = '25000'"))
                    connection.execute(text("SET lock_timeout = '2000'"))
                    connection.commit()
                processed = run_task(task, db, config)
            return {'ok': True, 'task': task, 'processed': processed, 'busy': False}
        finally:
            if postgres:
                connection.rollback()
                if locked:
                    connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': LOCKS[task]})
                connection.execute(text('RESET statement_timeout'))
                connection.execute(text('RESET lock_timeout'))
                connection.commit()


def install_scheduled_tasks(app, config, engine):
    @app.get('/api/internal/tasks/{task}')
    def scheduled_task(task: Task, request: Request):
        if config.background_mode != 'scheduled' or len(config.cron_secret) < 32:
            raise HTTPException(404, 'Scheduled processing is disabled')
        expected = ('Bearer ' + config.cron_secret).encode()
        supplied = request.headers.get('authorization', '').encode()
        if not hmac.compare_digest(supplied, expected):
            raise HTTPException(401, 'Scheduler authentication required')
        try:
            return execute_task(task, config, engine)
        except Exception:
            # Neither provider errors nor candidate data belong in scheduler logs.
            log.error('Scheduled %s task failed', task)
            raise HTTPException(503, 'Scheduled task failed; retry on the next run') from None
