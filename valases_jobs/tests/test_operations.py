from datetime import datetime,timedelta,timezone
import smtplib
import unittest
from unittest.mock import patch
from cryptography.fernet import Fernet
from sqlalchemy import create_engine,select,text,inspect
from sqlalchemy.orm import Session
from valases_jobs.models import Base,Account,Profile,MailOutbox
from valases_jobs.mail import MailService
from valases_jobs.settings import Settings
from valases_jobs.migrate import migrate
from valases_jobs.matching import match_jobs,evidence

class OperationsTests(unittest.TestCase):
    def test_additive_migration_preserves_pilot_account(self):
        engine=create_engine('sqlite://')
        with engine.begin() as conn:
            conn.execute(text('CREATE TABLE jobs_accounts (id VARCHAR PRIMARY KEY, email VARCHAR, password_hash TEXT, name VARCHAR, paid_until TIMESTAMP)'))
            conn.execute(text("INSERT INTO jobs_accounts (id,email,password_hash,name) VALUES ('1','candidate@example.com','hash','Candidate')"))
            conn.execute(text('CREATE TABLE jobs_profiles (account_id VARCHAR PRIMARY KEY,resume_text TEXT,preferences JSON)'))
        migrate(engine);migrate(engine)
        with Session(engine) as db:
            self.assertEqual(db.get(Account,'1').email,'candidate@example.com')
            self.assertFalse(db.get(Account,'1').email_verified)
        self.assertIn('jobs_payment_orders',inspect(engine).get_table_names())

    def test_email_failure_retries_without_leaking_plaintext(self):
        engine=create_engine('sqlite://');Base.metadata.create_all(engine)
        config=Settings(encryption_key=Fernet.generate_key().decode(),smtp_host='test.invalid',smtp_sender='jobs@example.com')
        service=MailService(config)
        with Session(engine) as db:
            user=Account(id='1',email='candidate@example.com',password_hash='hash',name='Candidate');db.add(user);db.commit()
            service.enqueue(db,user,'Verify','private link','action:one');db.commit()
            with patch('valases_jobs.mail.smtplib.SMTP',side_effect=smtplib.SMTPException('mock delivery failure')):
                self.assertTrue(service.deliver_one(db))
            row=db.scalar(select(MailOutbox));self.assertEqual(row.status,'pending');self.assertEqual(row.attempts,1)
            self.assertNotIn('private link',row.encrypted_payload)
            self.assertFalse(service.deliver_one(db))
            row.available_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
            with patch('valases_jobs.mail.smtplib.SMTP') as smtp:
                self.assertTrue(service.deliver_one(db))
                smtp.return_value.__enter__.return_value.send_message.assert_called_once()
            self.assertEqual(row.status,'sent');self.assertEqual(row.encrypted_payload,'')

    def test_opt_out_cancels_queued_digest_and_leased_mail_does_not_block(self):
        engine=create_engine('sqlite://');Base.metadata.create_all(engine)
        config=Settings(encryption_key=Fernet.generate_key().decode(),smtp_host='test.invalid',smtp_sender='jobs@example.com')
        service=MailService(config)
        with Session(engine) as db:
            user=Account(id='1',email='candidate@example.com',password_hash='hash',name='Candidate',email_verified=True,paid_until=datetime.now(timezone.utc)+timedelta(days=1));db.add(user);db.flush()
            db.add(Profile(account_id='1',alerts_enabled=False))
            service.enqueue(db,user,'Old digest','matching roles','digest:one');service.enqueue(db,user,'Verify','link','action:two');db.commit()
            rows=list(db.scalars(select(MailOutbox).order_by(MailOutbox.available_at)))
            rows[0].status='sending';rows[0].lease_until=datetime.now(timezone.utc)+timedelta(minutes=1);db.commit()
            with patch('valases_jobs.mail.smtplib.SMTP') as smtp:
                service.deliver_one(db);self.assertEqual(rows[1].status,'sent')
                rows[0].lease_until=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
                service.deliver_one(db);self.assertEqual(rows[0].status,'cancelled')
                smtp.return_value.__enter__.return_value.send_message.assert_called_once()

    def test_general_skills_cannot_create_a_strong_role_match(self):
        result=match_jobs('Strong communication and teamwork experience',{},[{'id':'1','skills':['Communication','Teamwork']}])
        self.assertEqual(result[0]['band'],'Stretch role')
        self.assertIsNotNone(evidence('Not only Python but SQL projects','python'))
        self.assertIsNone(evidence('No Python experience','python'))

    def test_non_technical_skill_aliases_and_different_fields(self):
        jobs=[{'id':'1','skills':['Recruitment','Payroll']},{'id':'2','skills':['GST','Tally']},{'id':'3','skills':['CRM','Lead generation']}]
        matches=match_jobs('Talent acquisition and payroll experience',{},jobs)
        self.assertEqual([row['job']['id'] for row in matches],['1'])
        matches=match_jobs('TallyPrime and goods and services tax work',{},jobs)
        self.assertEqual([row['job']['id'] for row in matches],['2'])
