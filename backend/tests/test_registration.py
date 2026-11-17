"""Synthetic accounts, SQLite and a dedicated Redis. Never sends real mail.

Run with AUTH_TEST_REDIS_URL pointing to a NEW isolated Redis. No FLUSHDB.
"""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app import auth, registration_email as mail, security
from app.db import db_session
from app.models import User, LoginSession
from app.registration_security import password_problem
REAL_SEND_MESSAGE = mail.send_message

@pytest.fixture
def context(monkeypatch):
    url = os.environ.get('AUTH_TEST_REDIS_URL')
    if not url:
        pytest.skip('Dedicated AUTH_TEST_REDIS_URL required')
    redis = Redis.from_url(url, decode_responses=True)
    redis.ping()
    monkeypatch.setattr(mail, 'redis', redis)
    monkeypatch.setattr(security, 'redis', redis)
    config = SimpleNamespace(smtp_host='smtp.example.com', smtp_port=587, smtp_security='starttls',
        smtp_username='sender@example.com', smtp_password='synthetic-smtp-password', smtp_from='sender@example.com', smtp_timeout_seconds=10)
    monkeypatch.setattr(mail, 'settings', lambda: config)
    sent = []
    monkeypatch.setattr(mail, 'send_message', lambda email, code: sent.append((email, code)))
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    User.__table__.create(engine)
    LoginSession.__table__.create(engine)
    def db():
        with Session(engine) as session:
            yield session
    app = FastAPI()
    app.include_router(auth.router)
    app.dependency_overrides[db_session] = db
    email = f'auth-{uuid.uuid4().hex}@example.com'
    ip = 'test-' + uuid.uuid4().hex
    # Unique IP for each test without modifying production throttle rules.
    monkeypatch.setattr(auth, 'throttle', lambda request, address: security.rate_limit('fixture-' + ip + address, 100, 60))
    yield SimpleNamespace(redis=redis, config=config, sent=sent, client=TestClient(app), email=email, ip=ip, engine=engine)
    for address, _ in sent:
        redis.delete(*mail.keys(address))
    redis.delete(*mail.keys(email))
    engine.dispose()

def issue(c):
    return mail.issue(c.email, c.ip)

def payload(c, result=None):
    result = result or issue(c)
    return dict(email=c.email, password='quiet-river-maple-2026', confirm_password='quiet-river-maple-2026',
        challenge_id=result['challenge_id'], verification_code=c.sent[-1][1])

def denied(call, status=422):
    with pytest.raises(HTTPException) as failure:
        call()
    assert failure.value.status_code == status

def test_registration_creates_hashed_account_and_login_cookie(context):
    c = context
    body = payload(c)
    response = c.client.post('/auth/register', json=body)
    assert response.status_code == 201
    assert 'narcissus_session=' in response.headers['set-cookie']
    assert 'HttpOnly' in response.headers['set-cookie']
    with Session(c.engine) as db:
        user = db.scalar(select(User))
        assert user.email == c.email and user.password_hash.startswith('$argon2id$')
        assert body['password'] not in user.password_hash
    assert c.client.post('/auth/register', json=body).status_code == 422
    assert c.client.post('/auth/login', json={k: body[k] for k in ('email','password')}).status_code == 200

def test_missing_verification_rejected_without_account(context):
    c = context
    response = c.client.post('/auth/register', json=dict(email=c.email, password='quiet-river-maple-2026'))
    assert response.status_code == 422
    with Session(c.engine) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 0

@pytest.mark.parametrize('field,value', [('confirm_password','different-long-passphrase'),('password','Password123!')])
def test_password_errors_do_not_consume_code(context, field, value):
    c = context
    body = payload(c)
    bad = {**body, field:value}
    if field == 'password': bad['confirm_password'] = value
    assert c.client.post('/auth/register', json=bad).status_code == 422
    assert c.client.post('/auth/register', json=body).status_code == 201

def test_duplicate_account_rejected(context):
    c=context
    assert c.client.post('/auth/register', json=payload(c)).status_code == 201
    c.redis.delete(mail.keys(c.email)[1])
    assert c.client.post('/auth/register', json=payload(c)).status_code == 409
    with Session(c.engine) as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1

def test_unconfigured_delivery_fails_closed_existing_login_works(context):
    c = context
    body=payload(c)
    assert c.client.post('/auth/register',json=body).status_code == 201
    c.config.smtp_password = ''
    assert c.client.get('/auth/registration-options').json()['email_delivery_available'] is False
    assert c.client.post('/auth/email-code',json={'email': c.email}).status_code == 503
    assert c.client.post('/auth/login',json={k:body[k] for k in ('email','password')}).status_code == 200

def test_only_hmac_stored_not_plaintext(context):
    c=context; result=issue(c)
    row=c.redis.hgetall(mail.keys(c.email)[0])
    assert row['state']=='active' and row['id']==result['challenge_id']
    assert len(row['digest']) == 64 and c.sent[-1][1] not in row.values()
    assert 'code' not in result and 'verification_code' not in result
    assert 590 <= c.redis.ttl(mail.keys(c.email)[0]) <= 600

def test_email_and_challenge_binding(context):
    c=context; result=issue(c); code=c.sent[-1][1]
    denied(lambda:mail.consume('other@example.com',result['challenge_id'],code))
    denied(lambda:mail.consume(c.email,'0'*32,code))
    mail.consume(c.email,result['challenge_id'],code)
    denied(lambda:mail.consume(c.email,result['challenge_id'],code))

def test_five_wrong_codes_lock_challenge(context):
    c=context; result=issue(c); code=c.sent[-1][1]; wrong='000000' if code!='000000' else '111111'
    for _ in range(5): denied(lambda:mail.consume(c.email,result['challenge_id'],wrong))
    denied(lambda:mail.consume(c.email,result['challenge_id'],code))

def test_expiration(context):
    c=context; result=issue(c)
    c.redis.expire(mail.keys(c.email)[0],0)
    denied(lambda:mail.consume(c.email,result['challenge_id'],c.sent[-1][1]))

def test_cooldown_and_resend_invalidates_old_code(context):
    c=context; old=issue(c); code=c.sent[-1][1]
    denied(lambda:issue(c),429)
    c.redis.delete(mail.keys(c.email)[1]); new=issue(c)
    denied(lambda:mail.consume(c.email,old['challenge_id'],code))
    mail.consume(c.email,new['challenge_id'],c.sent[-1][1])

def test_concurrent_consumption_only_one_success(context):
    c=context; result=issue(c); code=c.sent[-1][1]
    def consume(_):
        try: mail.consume(c.email,result['challenge_id'],code); return True
        except HTTPException: return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(consume, range(8))) == 1

def test_pending_challenge_not_usable(context,monkeypatch):
    c=context
    def deliver(email,code):
        row=c.redis.hgetall(mail.keys(email)[0])
        assert row['state']=='pending'
        denied(lambda:mail.consume(email,row['id'],code))
    monkeypatch.setattr(mail,'send_message',deliver)
    result=issue(c)
    assert c.redis.hget(mail.keys(c.email)[0],'state')=='active'

def test_delivery_failure_removes_pending_record(context,monkeypatch):
    c=context
    monkeypatch.setattr(mail,'send_message',Mock(side_effect=RuntimeError('private SMTP details')))
    denied(lambda:issue(c),503)
    assert not c.redis.exists(*mail.keys(c.email))

def test_redis_failure_rejects_code(context,monkeypatch):
    c=context
    monkeypatch.setattr(mail,'redis',SimpleNamespace(eval=Mock(side_effect=ConnectionError('private address'))))
    denied(lambda:mail.consume(c.email,'0'*32,'123456'),503)

def test_email_and_ip_rate_limits(context):
    c=context
    for _ in range(5):
        issue(c);c.redis.delete(mail.keys(c.email)[1])
    denied(lambda:issue(c),429)
    c.ip='limit-ip-'+uuid.uuid4().hex
    for _ in range(12):
        c.email=f'limit-{uuid.uuid4().hex}@example.com';issue(c)
    c.email=f'limit-{uuid.uuid4().hex}@example.com'
    denied(lambda:issue(c),429)

@pytest.mark.parametrize('password', ['1234567890','12345678901234567890','abcdefghijklmnop','Password123!','abcabcabcabc','quiet-maple-quiet-maple-','aaaaaaaaaaaa','too-short','a'*129])
def test_weak_passwords(password):
    assert password_problem(password)

@pytest.mark.parametrize('password', ['quiet-river-maple-meadow','山川海洋星辰书本灯火晚风', '两个无关短语组合，避免常见句子123'])
def test_long_passwords_without_composition_rules(password):
    assert password_problem(password) is None

@pytest.mark.parametrize('mode', ['starttls','ssl'])
def test_smtp_requires_tls_and_authentication(context,monkeypatch,mode):
    c=context;c.config.smtp_security=mode
    # Actual delivery function with an in-memory SMTP transport contract.
    transport=Mock();transport.__enter__=Mock(return_value=transport);transport.__exit__=Mock(return_value=False)
    transport.send_message.return_value={}
    factory=Mock(return_value=transport)
    monkeypatch.setattr(mail.smtplib,'SMTP_SSL' if mode=='ssl' else 'SMTP',factory)
    REAL_SEND_MESSAGE(c.email,'123456')
    transport.login.assert_called_once_with('sender@example.com','synthetic-smtp-password')
    if mode=='starttls': transport.starttls.assert_called_once()
    else: assert factory.call_args.kwargs['context'].verify_mode != 0
    msg=transport.send_message.call_args.args[0]
    assert msg['To']==c.email and '123456' in msg.get_content()

def test_tls_failure_never_sends_or_downgrades(context,monkeypatch):
    c=context
    transport=Mock();transport.__enter__=Mock(return_value=transport);transport.__exit__=Mock(return_value=False)
    transport.starttls.side_effect=RuntimeError('TLS unavailable')
    monkeypatch.setattr(mail.smtplib,'SMTP',Mock(return_value=transport))
    with pytest.raises(RuntimeError): REAL_SEND_MESSAGE(c.email,'123456')
    transport.login.assert_not_called();transport.send_message.assert_not_called()
