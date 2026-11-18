"""Opt-in, isolated sandbox harness. Never imported by production startup."""
import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import select
from app import auth, billing
from app.config import settings
from app.db import SessionLocal
from app.models import User
from app.security import passwords
from app.main import RequestGuard, http_error, validation_error
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError

if os.environ.get('BILLING_SANDBOX_HARNESS') != '1' or 'narcissus_billing_test' not in settings().database_url or settings().alipay_environment != 'sandbox':
    raise RuntimeError('Dedicated sandbox harness environment required')


@asynccontextmanager
async def lifespan(app):
    # Synthetic fixture account, exclusively in the dedicated test database.
    with SessionLocal() as db:
        if not db.scalar(select(User).where(User.email == 'sandbox-reader@example.com')):
            db.add(User(email='sandbox-reader@example.com', password_hash=passwords.hash('local-sandbox-reader-2026')))
            db.commit()
    task=asyncio.create_task(billing.reconcile_loop())
    try:yield
    finally:
        task.cancel()
        try:await task
        except asyncio.CancelledError:pass


app=FastAPI(lifespan=lifespan)
app.add_middleware(RequestGuard)
app.add_exception_handler(HTTPException,http_error)
app.add_exception_handler(RequestValidationError,validation_error)
app.include_router(auth.router,prefix='/api')
app.include_router(billing.router,prefix='/api')
