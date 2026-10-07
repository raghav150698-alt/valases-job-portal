import base64
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import hmac
import json
import time
from unittest.mock import patch,Mock
from urllib.parse import urlsplit,parse_qs

from cryptography.fernet import Fernet
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
import unittest
from valases_jobs.tests import test_platform
from valases_jobs.models import Account,ActionToken,PaymentOrder,Profile,MailOutbox,AlertDelivery,CatalogState
from valases_jobs.payments import Payments
from valases_jobs.mail import MailService
from valases_jobs.worker import digest_one
from valases_jobs import catalog
from valases_jobs.vault import Vault

class LaunchTests(unittest.TestCase):
    setUp = test_platform.JobsPlatformTests.setUp
    tearDown = test_platform.JobsPlatformTests.tearDown
    register = test_platform.JobsPlatformTests.register
    def verify(self):
        link=self.client.post('/api/auth/verification').json()['demo_link']
        token=parse_qs(urlsplit(link).fragment)['verify_token'][0]
        result=self.client.post('/api/auth/verify',json={'token':token})
        self.assertEqual(result.status_code,200)
        return token

    def test_verification_single_use_and_reset_revokes_sessions(self):
        self.register();token=self.verify()
        self.assertTrue(self.client.get('/api/me').json()['email_verified'])
        self.assertEqual(self.client.post('/api/auth/verify',json={'token':token}).status_code,400)
        response=self.client.post('/api/auth/forgot-password',json={'email':'candidate@example.com'})
        token=parse_qs(urlsplit(response.json()['demo_link']).fragment)['reset_token'][0]
        body={'token':token,'password':'new-secure-password-123'}
        self.assertEqual(self.client.post('/api/auth/reset-password',json=body).status_code,200)
        self.assertEqual(self.client.get('/api/me').status_code,401)
        self.assertEqual(self.client.post('/api/auth/reset-password',json=body).status_code,400)
        self.assertEqual(self.client.post('/api/auth/login',json={'email':'candidate@example.com','password':body['password']}).status_code,200)

    def test_expired_recovery_links_and_unverified_alerts(self):
        self.register()
        self.client.put('/api/me/profile',json={'resume_text':'Python SQL and testing experience'})
        self.assertEqual(self.client.put('/api/me/alerts',json={'enabled':True}).status_code,403)
        token=self.client.post('/api/auth/verification').json()['demo_link'].split('=')[1]
        with Session(self.engine) as db:
            row=db.get(ActionToken,sha256(token.encode()).hexdigest());row.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
        self.assertEqual(self.client.post('/api/auth/verify',json={'token':token}).status_code,400)

    def payment_config(self):
        config=self.app.state.bridge.settings
        config.demo=False;config.billing_enabled=True;config.cashfree_app_id='mock';config.cashfree_secret_key='mock-secret'
        return config

    def test_payment_amount_tampering_and_duplicate_grant(self):
        self.register();self.verify();config=self.payment_config();payments=Payments(config)
        with Session(self.engine) as db:
            user=db.scalar(select(Account))
            row=PaymentOrder(id='jobs_123',account_id=user.id,idempotency_key='key',created_at=datetime.now(timezone.utc));db.add(row);db.commit()
            data={'order_id':row.id,'order_currency':'INR','order_amount':1,'order_status':'PAID'}
            response=httpx.Response(200,json=data,request=httpx.Request('GET','https://provider.example'))
            with patch('valases_jobs.payments.httpx.get',return_value=response):
                from fastapi import HTTPException
                with self.assertRaises(HTTPException):payments.verify(db,row.id)
            self.assertIsNone(user.paid_until)
            data['order_amount']=79
            response=httpx.Response(200,json=data,request=httpx.Request('GET','https://provider.example'))
            with patch('valases_jobs.payments.httpx.get',return_value=response):
                payments.verify(db,row.id);until=user.paid_until;payments.verify(db,row.id)
                self.assertEqual(user.paid_until,until)
                raw=json.dumps({'data':{'order':{'order_id':row.id}}}).encode()
                timestamp=str(int(time.time()*1000))
                signature=base64.b64encode(hmac.new(b'mock-secret',timestamp.encode()+raw,sha256).digest()).decode()
                result=self.client.post('/api/billing/webhook',content=raw,headers={'x-webhook-timestamp':timestamp,'x-webhook-signature':signature})
                self.assertEqual(result.status_code,200,result.text)
                db.refresh(user);self.assertEqual(user.paid_until,until)

    def test_checkout_idempotency_and_order_ownership(self):
        self.register();self.verify();config=self.payment_config()
        def provider(url,**kwargs):
            return httpx.Response(200,request=httpx.Request('POST',url),json={'order_id':kwargs['json']['order_id'],'payment_session_id':'test-session'})
        body={'phone':'9876543210','idempotency_key':'test-idempotency-123'}
        with patch('valases_jobs.payments.httpx.post',side_effect=provider) as create:
            first=self.client.post('/api/billing/orders',json=body);second=self.client.post('/api/billing/orders',json=body)
            self.assertEqual(first.status_code,200,first.text);self.assertEqual(first.json(),second.json());self.assertEqual(create.call_count,1)
        order=first.json()['order_id'];config.demo=True
        self.client.post('/api/auth/logout');self.register('other@example.com')
        self.assertEqual(self.client.post('/api/billing/orders/'+order+'/verify').status_code,404)

    def test_webhook_signature_rejects_tampering_and_old_timestamp(self):
        payments=Payments(self.payment_config());raw=b'{"event":"paid"}';timestamp=str(int(time.time()*1000))
        signature=base64.b64encode(hmac.new(b'mock-secret',timestamp.encode()+raw,sha256).digest()).decode()
        self.assertTrue(payments.verify_signature(raw,timestamp,signature))
        self.assertFalse(payments.verify_signature(raw+b' ',timestamp,signature))
        self.assertFalse(payments.verify_signature(raw,'1000',signature))
        self.assertEqual(self.client.post('/api/billing/webhook',content=raw).status_code,401)

    def test_digest_opt_in_dedupe_unsubscribe_and_encryption(self):
        self.register();self.verify();config=self.app.state.bridge.settings
        config.encryption_key=Fernet.generate_key().decode();mail=MailService(config)
        with Session(self.engine) as db:
            user=db.scalar(select(Account));user.paid_until=datetime.now(timezone.utc)+timedelta(days=30)
            profile=Profile(account_id=user.id,resume_text=Vault(config).store('Python SQL Git projects and testing experience'),preferences={},alerts_enabled=True)
            db.add(profile);db.commit()
            self.assertNotIn('Python',profile.resume_text)
            self.assertTrue(digest_one(db,config,self.app.state.bridge,mail))
            outbox=db.scalar(select(MailOutbox));self.assertIsNotNone(outbox)
            self.assertNotIn(user.email,outbox.encrypted_payload)
            payload=json.loads(mail.cipher.decrypt(outbox.encrypted_payload.encode()))
            self.assertNotIn('projects and testing experience',payload['body'])
            self.assertGreater(len(list(db.scalars(select(AlertDelivery)))),0)
            profile.next_digest_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
            digest_one(db,config,self.app.state.bridge,mail)
            self.assertEqual(len(list(db.scalars(select(MailOutbox)))),1)
            token=payload['body'].split('unsubscribe_token=')[1]
        self.assertEqual(self.client.post('/api/alerts/unsubscribe',json={'token':token}).status_code,200)
        with Session(self.engine) as db:self.assertFalse(db.scalar(select(Profile)).alerts_enabled)

    def test_indexed_retrieval_search_pagination_and_stale_catalog(self):
        with Session(self.engine) as db:
            catalog.refresh(db,self.app.state.bridge)
            self.assertEqual(len(catalog.search(db,limit=2)['items']),2)
            roles=catalog.candidates(db,'Python SQL experience')
            self.assertTrue(roles)
            self.assertTrue(all(any(skill.lower() in {'python','sql'} for skill in job['skills']) for job in roles))
            state=db.get(CatalogState,1);state.synced_at=datetime.now(timezone.utc)-timedelta(hours=1);db.commit()
            from fastapi import HTTPException
            with self.assertRaises(HTTPException):catalog.search(db)

    def test_fetch_metadata_and_stream_limits(self):
        self.assertEqual(self.client.post('/api/auth/login',headers={'Sec-Fetch-Site':'cross-site'},json={}).status_code,403)
        self.assertEqual(self.client.post('/api/matches/preview',content=b'x'*(3*1024*1024+1)).status_code,413)

    def test_export_and_delete_all_candidate_records(self):
        self.register();self.verify()
        self.assertEqual(self.client.get('/api/me/export').json()['account']['email'],'candidate@example.com')
        self.assertEqual(self.client.delete('/api/me').status_code,200)
        with Session(self.engine) as db:
            self.assertIsNone(db.scalar(select(ActionToken)))

    def test_paid_matching_feedback_and_pagination(self):
        self.register();self.verify()
        self.client.put('/api/me/profile',json={'resume_text':'Python SQL Git testing Selenium Excel Power BI and React projects'})
        with Session(self.engine) as db:
            user=db.scalar(select(Account));user.paid_until=datetime.now(timezone.utc)+timedelta(days=30);db.commit()
        first=self.client.get('/api/me/matches?limit=1').json()
        self.assertEqual(len(first['items']),1);self.assertGreater(first['total'],1)
        hidden=first['items'][0]['job']['id']
        self.assertEqual(self.client.post('/api/me/feedback',json={'job_id':hidden,'reason':'not_interested'}).status_code,200)
        result=self.client.get('/api/me/matches').json()
        self.assertNotIn(hidden,[row['job']['id'] for row in result['items']])
        self.assertEqual(self.client.delete('/api/me/feedback/'+hidden).status_code,200)
        self.assertEqual(self.client.get('/api/me/matches').json()['total'],first['total'])

    def test_encrypted_profile_api_round_trip(self):
        from fastapi.testclient import TestClient
        from valases_jobs.main import create_app
        from valases_jobs.settings import Settings
        config=Settings(demo=True,secure_cookies=False,create_schema=True,encryption_key=Fernet.generate_key().decode())
        with TestClient(create_app(config,self.engine)) as client:
            self.assertEqual(client.post('/api/auth/register',json={'email':'encrypted@example.com','password':'secure-password-123','accepted_terms':True}).status_code,201)
            text='Python and SQL private project details'
            client.put('/api/me/profile',json={'resume_text':text})
            self.assertEqual(client.get('/api/me').json()['profile']['resume_text'],text)
            self.assertEqual(client.get('/api/me/export').json()['profile']['resume_text'],text)
            with Session(self.engine) as db:
                stored=db.scalar(select(Profile)).resume_text
                self.assertTrue(stored.startswith('enc:v1:'));self.assertNotIn(text,stored)
