"""Cashfree hosted checkout. Grant access only after server-side verification."""
import base64
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import time
from uuid import uuid4

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from valases_jobs.models import Account, PaymentOrder


class Payments:
    def __init__(self,settings):
        self.settings=settings

    @property
    def base_url(self):
        return "https://api.cashfree.com/pg" if self.settings.cashfree_environment == "production" else "https://sandbox.cashfree.com/pg"

    def headers(self):
        return {"x-client-id":self.settings.cashfree_app_id,"x-client-secret":self.settings.cashfree_secret_key,
                "x-api-version":self.settings.cashfree_api_version}

    def create(self, db, user, phone, key):
        if not self.settings.checkout_ready:
            raise HTTPException(503,"Checkout is not configured yet")
        scoped_key = hashlib.sha256((user.id + ":" + key).encode()).hexdigest()
        row=db.scalar(select(PaymentOrder).where(PaymentOrder.idempotency_key==scoped_key))
        if row and row.session_id:
            return row
        if not row:
            row=PaymentOrder(id="jobs_"+uuid4().hex,account_id=user.id,idempotency_key=scoped_key,created_at=datetime.now(timezone.utc))
            db.add(row)
            try: db.commit()
            except IntegrityError:
                db.rollback()
                row=db.scalar(select(PaymentOrder).where(PaymentOrder.idempotency_key==scoped_key))
                if row.session_id: return row
        try:
            result=httpx.post(self.base_url+"/orders",headers={**self.headers(),"x-idempotency-key":str(__import__('uuid').UUID(row.id[5:]))},timeout=20,
                json={"order_id":row.id,"order_amount":79,"order_currency":"INR",
                      "customer_details":{"customer_id":user.id,"customer_name":user.name,"customer_email":user.email,"customer_phone":phone},
                      "order_meta":{"return_url":self.settings.public_origin+"/?order_id="+row.id,
                                    "notify_url":self.settings.public_origin+"/api/billing/webhook"}})
            result.raise_for_status(); data=result.json()
            if data.get("order_id") != row.id or not data.get("payment_session_id"):
                raise ValueError()
            row.session_id=data["payment_session_id"]; db.commit(); return row
        except (httpx.HTTPError,ValueError):
            raise HTTPException(502,"Payment provider is unavailable. Retry this checkout.") from None

    def verify(self, db, order_id, *, timeout=20):
        if not self.settings.checkout_ready:
            raise HTTPException(503,"Checkout is not configured")
        try:
            response=httpx.get(self.base_url+"/orders/"+order_id,headers=self.headers(),timeout=timeout)
            response.raise_for_status(); data=response.json()
        except (httpx.HTTPError,ValueError):
            raise HTTPException(502,"Payment verification is temporarily unavailable") from None
        row=db.scalar(select(PaymentOrder).where(PaymentOrder.id==order_id).with_for_update())
        if not row:
            raise HTTPException(404,"Order not found")
        try:
            valid=data.get("order_id")==row.id and data.get("order_currency")=="INR" and Decimal(str(data.get("order_amount")))==Decimal(row.amount_minor)/100
        except InvalidOperation:
            valid=False
        if not valid:
            raise HTTPException(409,"Payment amount or order does not match")
        if data.get("order_status") != "PAID":
            row.status=str(data.get('order_status','pending')).lower()[:24];db.commit()
            return row
        if row.granted_at is None and row.account_id:
            user=db.scalar(select(Account).where(Account.id==row.account_id).with_for_update())
            if user:
                now=datetime.now(timezone.utc)
                previous=user.paid_until
                if previous and previous.tzinfo is None: previous=previous.replace(tzinfo=timezone.utc)
                user.paid_until=max(previous or now,now)+timedelta(days=30)
            row.granted_at=datetime.now(timezone.utc)
        row.status="paid"; db.commit(); return row

    def verify_signature(self, raw, timestamp, signature):
        if not self.settings.cashfree_secret_key:
            return False
        try:
            if abs(time.time()*1000-int(timestamp)) > 300000: return False
        except (ValueError,TypeError):
            return False
        expected=base64.b64encode(hmac.new(self.settings.cashfree_secret_key.encode(),timestamp.encode()+raw,hashlib.sha256).digest()).decode()
        return hmac.compare_digest(expected,signature or "")
