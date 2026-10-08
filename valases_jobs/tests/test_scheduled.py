import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from valases_jobs.main import create_app
from valases_jobs.models import Account, Base, CatalogJob, MailOutbox, PaymentOrder
from valases_jobs.scheduled import execute_task
from valases_jobs.settings import Settings


class ScheduledTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', poolclass=StaticPool,
                                    connect_args={'check_same_thread': False})
        Base.metadata.create_all(self.engine)
        self.config = Settings(background_mode='scheduled', cron_secret='s' * 40,
                               encryption_key=Fernet.generate_key().decode(),
                               smtp_host='smtp.invalid', smtp_sender='jobs@example.com',
                               indexed_catalog=True, demo=True)
        self.client = TestClient(create_app(self.config, self.engine))
        self.auth = {'Authorization': 'Bearer ' + self.config.cron_secret}

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_secret_required_and_no_work_for_unauthorized_calls(self):
        with patch('valases_jobs.scheduled.execute_task') as execute:
            for headers in ({}, {'Authorization': 'Bearer wrong'},
                            {'Authorization': 'Bearer wrong', 'Cookie': 'jobs_session=anything'}):
                self.assertEqual(self.client.get('/api/internal/tasks/mail', headers=headers).status_code, 401)
            execute.assert_not_called()
        disabled = TestClient(create_app(Settings(), self.engine))
        self.assertEqual(disabled.get('/api/internal/tasks/mail', headers=self.auth).status_code, 404)
        disabled.close()

    def test_scheduler_never_exposes_provider_exception_or_secret(self):
        with patch('valases_jobs.scheduled.execute_task', side_effect=RuntimeError('private-provider-secret')):
            response = self.client.get('/api/internal/tasks/mail', headers=self.auth)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private-provider-secret', response.text)
        self.assertNotIn(self.config.cron_secret, response.text)
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_catalog_snapshot_and_failed_refresh_keeps_previous_jobs(self):
        response = self.client.get('/api/internal/tasks/catalog', headers=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/api/jobs').json()['total'], 4)
        with patch('valases_jobs.scheduled.BoundedBridge.jobs', side_effect=HTTPException(503, 'unavailable')):
            response = self.client.get('/api/internal/tasks/catalog', headers=self.auth)
        self.assertEqual(response.status_code, 503)
        with Session(self.engine) as db:
            self.assertEqual(len(list(db.scalars(select(CatalogJob)))), 4)

    def test_one_mail_per_call_and_repeated_call_does_not_resend(self):
        from valases_jobs.mail import MailService
        config = self.config.model_copy(update={'demo': False})
        with Session(self.engine) as db:
            user = Account(id='1', email='candidate@example.com', name='Candidate', password_hash='hash')
            db.add(user); db.commit()
            MailService(config).enqueue(db, user, 'Verify', 'private link', 'one')
            MailService(config).enqueue(db, user, 'Reset', 'private link', 'two')
            db.commit()
        with patch('valases_jobs.mail.smtplib.SMTP') as smtp:
            self.assertEqual(execute_task('mail', config, self.engine)['processed'], 1)
            self.assertEqual(execute_task('mail', config, self.engine)['processed'], 1)
            self.assertEqual(execute_task('mail', config, self.engine)['processed'], 0)
            self.assertEqual(smtp.return_value.__enter__.return_value.send_message.call_count, 2)
            self.assertEqual(smtp.call_args.kwargs['timeout'], 5)
        with Session(self.engine) as db:
            self.assertTrue(all(row.status == 'sent' and row.encrypted_payload == ''
                                for row in db.scalars(select(MailOutbox))))

    def test_payment_batch_checks_only_one_order(self):
        config = self.config.model_copy(update={'demo': False, 'billing_enabled': True,
            'cashfree_app_id': 'placeholder', 'cashfree_secret_key': 'placeholder'})
        with Session(self.engine) as db:
            for i in range(3):
                db.add(PaymentOrder(id=str(i), idempotency_key=str(i),
                    created_at=datetime.now(timezone.utc) - timedelta(minutes=i)))
            db.commit()
        with patch('valases_jobs.scheduled.Payments.verify') as verify:
            self.assertEqual(execute_task('payments', config, self.engine)['processed'], 1)
            verify.assert_called_once()
            self.assertEqual(verify.call_args.kwargs['timeout'], 5)

    def test_public_scheduled_settings_need_strong_secret(self):
        issues = Settings(background_mode='scheduled', cron_secret='short').launch_issues()
        self.assertIn('Scheduled processing secret must contain at least 32 characters', issues)


if __name__ == '__main__':
    unittest.main()
