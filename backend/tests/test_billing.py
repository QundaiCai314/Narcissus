"""Offline billing tests; no real Alipay orders, refunds, credentials or business data."""
import base64
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace, dataclass, field
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app import billing, billing_service as service
from app.alipay_gateway import AlipayGateway, PaymentConfig, ProviderUnavailable, PaymentUnavailable
from app.billing_models import BillingAccount, PaymentOrder, BillingLedger, PaymentRefund, PaymentNotification, BILLING_TABLES
from app.config import settings
from app.db import db_session
from app.models import User, Notebook, LearningSet, now, uid
from app.security import current_user

PRODUCTS = [
    dict(id='test_member',title='隔离测试会员',kind='membership',amount_cents=101,member_days=30,credits=5),
    dict(id='test_credits',title='隔离测试额度',kind='credits',amount_cents=203,member_days=0,credits=20),
]


class FakeGateway:
    def __init__(self):
        self.config = PaymentConfig('1234567890123456','2088000000000000','sandbox',
            'https://openapi-sandbox.dl.alipaydev.com/gateway.do','http://localhost:3000/billing/return','',
            'synthetic-private-not-a-key','synthetic-public-not-a-key')
        self.state='WAIT_BUYER_PAY'
        self.reject_signature=False
        self.unavailable=False
        self.refund_calls=[]
        self.refund_confirmed=False

    def query(self,order):
        if self.unavailable: raise ProviderUnavailable('unavailable')
        return self.payment(order,self.state)

    def payment(self,order,state='TRADE_SUCCESS'):
        return dict(code='10000',out_trade_no=order.out_trade_no,trade_no='T'+order.id.replace('-',''),
            total_amount=f'{order.amount_cents/100:.2f}',trade_status=state)

    def verify_notification(self,params):
        return not self.reject_signature

    def close(self,order):
        return dict(code='10000',out_trade_no=order.out_trade_no,trade_no='T'+order.id.replace('-',''))

    def refund(self,order,refund):
        self.refund_calls.append((refund.id,refund.amount_cents))
        return dict(code='10000',out_trade_no=order.out_trade_no,trade_no=order.trade_no,
            refund_fee=f'{refund.amount_cents/100:.2f}',fund_change='Y' if self.refund_confirmed else 'N')

    def refund_query(self,order,refund):
        return dict(code='10000',out_trade_no=order.out_trade_no,trade_no=order.trade_no,out_request_no=refund.id,
            refund_amount=f'{refund.amount_cents/100:.2f}',refund_status='REFUND_SUCCESS' if self.refund_confirmed else 'REFUND_PROCESSING')


@pytest.fixture
def ctx(monkeypatch):
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    for table in (User.__table__,Notebook.__table__,LearningSet.__table__,*BILLING_TABLES):table.create(engine)
    factory=sessionmaker(engine,expire_on_commit=False)
    with factory() as db:
        user=User(email=f'{uid()}@example.com',password_hash='test-only');db.add(user);db.commit()
    gateway=FakeGateway()
    config=settings()
    monkeypatch.setattr(config,'alipay_enabled',True)
    monkeypatch.setattr(config,'billing_profile','custom')
    monkeypatch.setattr(config,'billing_products_json',json.dumps(PRODUCTS,ensure_ascii=False))
    monkeypatch.setattr(config,'billing_enforce_credits',True)
    monkeypatch.setattr(config,'billing_credit_costs_json','{"quiz":2,"mindmap":3,"flashcards":1}')
    monkeypatch.setattr(billing,'AlipayGateway',lambda:gateway)
    monkeypatch.setattr(service,'AlipayGateway',lambda:gateway)
    monkeypatch.setattr(billing,'rate_limit',lambda *args:None)
    app=FastAPI();app.include_router(billing.router,prefix='/api')
    def session():
        with factory() as db:yield db
    app.dependency_overrides[db_session]=session
    app.dependency_overrides[current_user]=lambda:user
    yield SimpleNamespace(engine=engine,session=factory,user=user,gateway=gateway,client=TestClient(app),config=config)
    engine.dispose()


def order(c,product='test_credits',key=None):
    with c.session() as db:return service.create_order(db,c.user,product,key or uid(),c.gateway)


def test_learning_quote_matches_debit_and_member_waiver(ctx):
    response=ctx.client.get('/api/billing/learning-quote')
    assert response.status_code == 200
    assert response.json()['costs'] == {'quiz':2,'mindmap':3,'flashcards':1}
    assert response.json()['credits'] == 0
    paid(ctx,'test_member')
    assert ctx.client.get('/api/billing/learning-quote').json()['costs']['quiz'] == 0


def test_launch_tariff_is_server_owned_and_does_not_enable_payments(ctx, monkeypatch):
    monkeypatch.setattr(ctx.config, 'billing_profile', 'launch')
    monkeypatch.setattr(ctx.config, 'alipay_enabled', False)
    assert [(p.id, p.amount_cents, p.member_days, p.credits) for p in service.catalog()] == [
        ('reading_month', 2990, 30, 0), ('learning_100', 990, 0, 100)]
    assert {kind: service.credit_cost(kind) for kind in ('quiz', 'mindmap', 'flashcards')} == {
        'quiz': 5, 'mindmap': 3, 'flashcards': 2}
    assert service.member_daily_limit() == 20
    assert ctx.client.get('/api/billing/catalog').json()['available'] is False


def test_member_limit_releases_failed_slot_and_never_falls_back_to_credits(ctx, monkeypatch):
    monkeypatch.setattr(ctx.config, 'billing_member_daily_limit', 2)
    paid(ctx, 'test_member')
    first, second, third = uid(), uid(), uid()
    for request_key in (first, second):
        with ctx.session() as db:
            service.consume_credit(db, ctx.user.id, 'quiz', request_key); db.commit()
    assert ctx.client.get('/api/billing/learning-quote').json()['member_daily_remaining'] == 0
    with ctx.session() as db:
        service.consume_credit(db, ctx.user.id, 'quiz', second); db.commit()
        with pytest.raises(HTTPException) as error:
            service.consume_credit(db, ctx.user.id, 'mindmap', third)
        assert error.value.status_code == 429
        db.rollback()
        assert db.get(BillingAccount, ctx.user.id).credits == 5
        service.restore_credit(db, first); db.commit()
        service.restore_credit(db, first); db.commit()
    assert ctx.client.get('/api/billing/learning-quote').json()['member_daily_remaining'] == 1
    with ctx.session() as db:
        service.consume_credit(db, ctx.user.id, 'mindmap', third); db.commit()
        assert db.get(BillingAccount, ctx.user.id).credits == 5
    assert ctx.client.get('/api/billing/learning-quote').json()['member_daily_remaining'] == 0


def test_member_day_resets_at_china_midnight_and_does_not_count_paid_usage(ctx, monkeypatch):
    monkeypatch.setattr(ctx.config, 'billing_member_daily_limit', 2)
    before = datetime(2026, 11, 18, 15, 59, tzinfo=timezone.utc)
    after = datetime(2026, 11, 18, 16, 0, tzinfo=timezone.utc)
    with ctx.session() as db:
        for kind, delta in [('quiz', 0), ('mindmap', -3)]:
            db.add(BillingLedger(event_key='usage:' + uid(), user_id=ctx.user.id,
                                 delta=delta, kind=kind, created_at=before))
        db.commit()
        assert service.member_daily_remaining(db, ctx.user.id, at=before) == 1
        assert service.member_daily_remaining(db, ctx.user.id, at=after) == 2


def test_member_allowance_isolated_by_account(ctx, monkeypatch):
    monkeypatch.setattr(ctx.config, 'billing_member_daily_limit', 1)
    with ctx.session() as db:
        other = User(email=uid() + '@example.test', password_hash='synthetic')
        db.add(other); db.flush()
        db.add(BillingLedger(event_key='usage:' + uid(), user_id=other.id, delta=0, kind='quiz'))
        db.commit()
        assert service.member_daily_remaining(db, other.id) == 0
        assert service.member_daily_remaining(db, ctx.user.id) == 1


def test_nonmember_credit_pack_not_subject_to_member_daily_allowance(ctx, monkeypatch):
    monkeypatch.setattr(ctx.config, 'billing_member_daily_limit', 1)
    paid(ctx)
    with ctx.session() as db:
        for _ in range(3): service.consume_credit(db, ctx.user.id, 'quiz', uid())
        db.commit()
        assert db.get(BillingAccount, ctx.user.id).credits == 14
    quote = ctx.client.get('/api/billing/learning-quote').json()
    assert quote['member_active'] is False and quote['member_daily_remaining'] is None
    assert quote['costs']['quiz'] == 2


def test_disabled_learning_billing_quote_works_without_new_tables(ctx,monkeypatch):
    monkeypatch.setattr(ctx.config,'billing_enforce_credits',False)
    monkeypatch.setattr(ctx.config,'alipay_enabled',False)
    for table in reversed(BILLING_TABLES):table.drop(ctx.engine)
    assert ctx.client.get('/api/billing/learning-quote').json() == {'enforced':False,'costs':{}}


def paid(c,product='test_credits'):
    row=order(c,product)
    with c.session() as db:
        service.apply_payment(db,row.id,c.gateway.payment(row),c.gateway.config);db.commit()
        return db.get(PaymentOrder,row.id)


def notification(c,row,**extra):
    return dict(c.gateway.payment(row),app_id=c.gateway.config.app_id,seller_id=c.gateway.config.seller_id,
        notify_type='trade_status_sync',notify_id='event-1',sign_type='RSA2',sign='test-only',**extra)


def test_order_price_snapshot_and_request_idempotency(ctx):
    key=uid();first=order(ctx,key=key);second=order(ctx,key=key)
    assert first.id==second.id and first.amount_cents==203
    with pytest.raises(HTTPException) as error:order(ctx,'test_member',key)
    assert error.value.status_code==409


def test_api_rejects_client_prices_and_cross_account_orders(ctx):
    row=order(ctx)
    bad=ctx.client.post('/api/billing/orders',json={'product_id':'test_credits','request_key':uid(),'amount_cents':1})
    assert bad.status_code==422
    with ctx.session() as db:
        other=User(email=f'{uid()}@example.com',password_hash='test-only');db.add(other);db.commit();row=db.get(PaymentOrder,row.id);row.user_id=other.id;db.commit()
    assert ctx.client.get('/api/billing/orders/'+row.id).status_code==404
    assert ctx.client.post('/api/billing/orders/'+row.id+'/refresh').status_code==404


@pytest.mark.parametrize('field,value',[('total_amount','0.01'),('out_trade_no','OTHER'),('seller_id','wrong'),('app_id','wrong'),('trade_no','')])
def test_mismatched_signed_payment_never_grants(ctx,field,value):
    row=order(ctx);data=ctx.gateway.payment(row);data[field]=value
    with ctx.session() as db:
        with pytest.raises(ValueError):service.apply_payment(db,row.id,data,ctx.gateway.config)
        db.rollback()
        assert db.scalar(select(func.count()).select_from(BillingLedger))==0


@pytest.mark.parametrize('status',['WAIT_BUYER_PAY','UNKNOWN','TRADE_CLOSED'])
def test_non_paid_states_never_grant(ctx,status):
    row=order(ctx)
    with ctx.session() as db:
        service.apply_payment(db,row.id,ctx.gateway.payment(row,status),ctx.gateway.config);db.commit()
        assert db.scalar(select(func.count()).select_from(BillingLedger))==0


def test_duplicate_success_grants_once(ctx):
    row=paid(ctx)
    with ctx.session() as db:
        for _ in range(3):service.apply_payment(db,row.id,ctx.gateway.payment(row),ctx.gateway.config);db.commit()
        assert db.get(BillingAccount,ctx.user.id).credits==20
        assert db.scalar(select(func.count()).select_from(BillingLedger))==1


def test_provider_trade_number_cannot_fulfill_another_order(ctx):
    first=paid(ctx);second=order(ctx)
    data={**ctx.gateway.payment(second),'trade_no':first.trade_no}
    with ctx.session() as db:
        with pytest.raises(ValueError):service.apply_payment(db,second.id,data,ctx.gateway.config)
        db.rollback()
        assert db.get(BillingAccount,ctx.user.id).credits==20


def test_closed_and_failed_source_jobs_restore_their_credit_reservations(ctx):
    paid(ctx);request=uid()
    with ctx.session() as db:
        notebook=Notebook(user_id=ctx.user.id,name='Synthetic source');db.add(notebook);db.flush()
        job=LearningSet(notebook_id=notebook.id,family_id=uid(),version=1,request_key=request,kind='quiz',
            title='Synthetic job',params={},sources=[],status='cancelled')
        db.add(job);service.consume_credit(db,ctx.user.id,'quiz',request+':'+uid());db.commit()
    service.reconcile(ctx.session)
    service.reconcile(ctx.session)
    with ctx.session() as db:assert db.get(BillingAccount,ctx.user.id).credits==20


def test_notify_retries_and_refund_event_are_distinct(ctx):
    row=order(ctx)
    with ctx.session() as db:
        data=notification(ctx,row)
        assert service.handle_notification(db,data,ctx.gateway)
        assert service.handle_notification(db,data,ctx.gateway)
        refunded={**data,'notify_id':'refund-event','out_biz_no':'refund-key','refund_fee':'2.03'}
        assert service.handle_notification(db,refunded,ctx.gateway)
        assert db.get(BillingAccount,ctx.user.id).credits==20
        assert db.scalar(select(func.count()).select_from(PaymentNotification))==2


def test_bad_notification_signature_or_merchant_fails(ctx):
    row=order(ctx)
    with ctx.session() as db:
        ctx.gateway.reject_signature=True
        assert not service.handle_notification(db,notification(ctx,row),ctx.gateway)
        ctx.gateway.reject_signature=False
        assert not service.handle_notification(db,{**notification(ctx,row),'seller_id':'other'},ctx.gateway)
        assert db.scalar(select(func.count()).select_from(BillingLedger))==0


def test_query_outage_keeps_pending_not_false_failure(ctx):
    row=order(ctx);ctx.gateway.unavailable=True
    with ctx.session() as db:
        updated=service.refresh_order(db,db.get(PaymentOrder,row.id),ctx.gateway)
        assert updated.status=='pending' and updated.check_error=='provider_unavailable'
    response=ctx.client.post('/api/billing/orders/'+row.id+'/refresh')
    assert response.status_code==200 and response.json()['status']=='pending'


def test_member_renewal_stacks_duration(ctx):
    first=paid(ctx,'test_member');second=paid(ctx,'test_member')
    assert service.utc(second.member_start)==service.utc(first.member_end)
    with ctx.session() as db:assert db.get(BillingAccount,ctx.user.id).credits==10


def test_credits_debit_retry_refund_and_insufficient_balance(ctx):
    paid(ctx)
    request=uid()
    with ctx.session() as db:
        service.consume_credit(db,ctx.user.id,'quiz',request+':'+uid());db.commit()
        assert db.get(BillingAccount,ctx.user.id).credits==18
        service.restore_credit(db,request);db.commit()
        service.restore_credit(db,request);db.commit()
        assert db.get(BillingAccount,ctx.user.id).credits==20
        service.consume_credit(db,ctx.user.id,'quiz',request+':'+uid());db.commit()
        assert db.get(BillingAccount,ctx.user.id).credits==18
    with ctx.session() as db:
        db.get(BillingAccount,ctx.user.id).credits=0;db.commit()
        with pytest.raises(HTTPException) as failure:service.consume_credit(db,ctx.user.id,'quiz',uid())
        assert failure.value.status_code==402


def test_active_member_does_not_spend_learning_credits(ctx):
    paid(ctx,'test_member')
    with ctx.session() as db:
        service.consume_credit(db,ctx.user.id,'mindmap',uid());db.commit()
        assert db.get(BillingAccount,ctx.user.id).credits==5


def test_refund_unknown_reserves_once_and_reuses_request(ctx):
    row=paid(ctx)
    with ctx.session() as db:
        refund=service.reserve_refund(db,db.get(PaymentOrder,row.id),ctx.gateway)
        service.send_or_query_refund(db,refund,ctx.gateway,send=True)
        assert refund.status=='pending' and db.get(BillingAccount,ctx.user.id).credits==0
        same=service.reserve_refund(db,db.get(PaymentOrder,row.id),ctx.gateway)
        assert same.id==refund.id
        refund.last_attempt_at=now()-timedelta(seconds=65);db.commit()
        service.send_or_query_refund(db,refund,ctx.gateway,send=True)
        assert len(set(ctx.gateway.refund_calls))==1
        assert db.get(BillingAccount,ctx.user.id).credits==0
        ctx.gateway.refund_confirmed=True
        refund.last_attempt_at=now()-timedelta(seconds=11);db.commit()
        service.send_or_query_refund(db,refund,ctx.gateway)
        assert refund.status=='succeeded' and db.get(PaymentOrder,row.id).status=='refunded'


def test_spent_credits_require_manual_refund_review(ctx):
    row=paid(ctx)
    with ctx.session() as db:
        service.consume_credit(db,ctx.user.id,'quiz',uid());db.commit()
        with pytest.raises(HTTPException) as error:service.reserve_refund(db,db.get(PaymentOrder,row.id),ctx.gateway)
        assert error.value.status_code==409 and not ctx.gateway.refund_calls


def test_refund_endpoint_requires_operator_and_explicit_full_refund(ctx,monkeypatch):
    row=paid(ctx)
    endpoint='/api/billing/orders/'+row.id+'/refund'
    assert ctx.client.post(endpoint,json={'confirm_full_refund':True}).status_code==403
    monkeypatch.setattr(ctx.config,'billing_operator_emails',ctx.user.email)
    assert ctx.client.post(endpoint,json={'amount':1}).status_code==422
    assert ctx.client.post(endpoint,json={'confirm_full_refund':True}).status_code==202


def test_notify_requires_form_and_unique_fields(ctx):
    row=order(ctx)
    assert ctx.client.post('/api/billing/alipay/notify',json=notification(ctx,row)).text=='fail'
    assert ctx.client.post('/api/billing/alipay/notify',content='app_id=1&app_id=2',headers={'Content-Type':'application/x-www-form-urlencoded'}).text=='fail'
    assert ctx.client.post('/api/billing/alipay/notify',data=notification(ctx,row)).text=='success'


def test_disabled_payments_do_not_require_new_tables_or_sdk_config(ctx,monkeypatch):
    monkeypatch.setattr(ctx.config,'alipay_enabled',False)
    assert ctx.client.get('/api/billing/catalog').json()['available'] is False
    assert ctx.client.post('/api/billing/orders',json={'product_id':'test_credits','request_key':uid()}).status_code==503


def test_server_recovers_pending_order_without_browser(ctx):
    row=order(ctx);ctx.gateway.state='TRADE_SUCCESS'
    service.reconcile(ctx.session)
    with ctx.session() as db:
        assert db.get(PaymentOrder,row.id).status=='paid'
        assert db.get(BillingAccount,ctx.user.id).credits==20


@pytest.fixture(scope='module')
def signed_config():
    # Synthetic in-memory TEST keys only, never registered as an Alipay application.
    import rsa
    from cryptography.hazmat.primitives import serialization
    public,private=rsa.newkeys(2048)
    raw_private=base64.b64encode(private.save_pkcs1(format='DER')).decode()
    crypto_public=serialization.load_pem_public_key(public.save_pkcs1())
    raw_public=base64.b64encode(crypto_public.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
    @dataclass
    class TestKeys:
        config: PaymentConfig
        private: object = field(repr=False)
        def __iter__(self):
            yield self.config
            yield self.private
    return TestKeys(PaymentConfig('1234567890123456','2088000000000000','sandbox',
        'https://openapi-sandbox.dl.alipaydev.com/gateway.do','http://localhost:3000/billing/return','',raw_private,raw_public),private)


def test_official_sdk_verifies_notification_and_rejects_tampering(signed_config):
    import rsa
    from alipay.aop.api.util.SignatureUtils import get_sign_content
    config,private=signed_config;gateway=AlipayGateway(config)
    params={'app_id':config.app_id,'out_trade_no':'Ntest','total_amount':'2.03','seller_id':config.seller_id,'trade_status':'TRADE_SUCCESS'}
    signature=base64.b64encode(rsa.sign(get_sign_content(params).encode(),private,'SHA-256')).decode()
    params.update(sign_type='RSA2',sign=signature)
    assert gateway.verify_notification(params)
    assert not gateway.verify_notification({**params,'total_amount':'0.01'})
    assert not gateway.verify_notification({**params,'app_id':'other'})


def test_official_sdk_requires_signed_query_and_returns_inner_payload(signed_config,monkeypatch):
    import rsa
    import importlib
    config,private=signed_config;gateway=AlipayGateway(config)
    module=importlib.import_module('alipay.aop.api.DefaultAlipayClient')
    payload={'code':'10000','out_trade_no':'Ntest','total_amount':'2.03','trade_no':'Ttest','trade_status':'TRADE_SUCCESS'}
    inner=json.dumps(payload,separators=(',',':'))
    signature=base64.b64encode(rsa.sign(inner.encode(),private,'SHA-256')).decode()
    response=(' {"alipay_trade_query_response":'+inner+',"sign":"'+signature+'"}').strip().encode()
    monkeypatch.setattr(module,'do_post',lambda *args:response)
    order=SimpleNamespace(out_trade_no='Ntest')
    assert gateway.query(order)==payload
    monkeypatch.setattr(module,'do_post',lambda *args:json.dumps({'alipay_trade_query_response':payload}).encode())
    with pytest.raises(ProviderUnavailable):gateway.query(order)


def test_payment_uses_post_form_with_optional_notify_and_exact_return_url(signed_config):
    from html.parser import HTMLParser
    from urllib.parse import urlsplit, parse_qs
    config,_=signed_config;gateway=AlipayGateway(config)
    row=SimpleNamespace(id=uid(),out_trade_no='Ntest',title='测试会员',amount_cents=101)
    form=gateway.payment_form(row)
    assert '<form ' in form and 'method="post"' in form and 'alipay.trade.page.pay' in form
    class Parser(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag == 'form':self.action=dict(attrs)['action']
    parser=Parser();parser.feed(form)
    query=parse_qs(urlsplit(parser.action).query)
    assert 'notify_url' not in query
    assert query['return_url']==[config.return_url+'?order='+row.id]
    assert config.app_private_key not in form and 'FAST_INSTANT_TRADE_PAY' in form


def test_real_postgres_serializes_duplicate_payments():
    url=os.environ.get('BILLING_TEST_DATABASE_URL')
    if not url:pytest.skip('Dedicated BILLING_TEST_DATABASE_URL required for concurrent PostgreSQL test')
    if 'narcissus_billing_test' not in url:raise RuntimeError('Dedicated billing test database required')
    schema='payment_'+uuid.uuid4().hex
    root=create_engine(url)
    with root.begin() as connection:connection.execute(text('CREATE SCHEMA '+schema))
    engine=root.execution_options(schema_translate_map={None:schema})
    factory=sessionmaker(engine,expire_on_commit=False)
    try:
        for table in (User.__table__,*BILLING_TABLES):table.create(engine)
        gateway=FakeGateway()
        with factory() as db:
            user=User(email=f'{uid()}@example.com',password_hash='test-only');db.add(user);db.flush()
            user_id=user.id
            row=PaymentOrder(id=uid(),user_id=user.id,request_key=uid(),out_trade_no='N'+uuid.uuid4().hex,
                app_id=gateway.config.app_id,seller_id=gateway.config.seller_id,environment='sandbox',product_id='test',
                title='concurrency test',kind='credits',amount_cents=203,credits=20,member_days=0,status='pending')
            db.add(row);db.commit();row_id=row.id;result=gateway.payment(row)
        def deliver(_):
            with factory() as db:service.apply_payment(db,row_id,result,gateway.config);db.commit()
        with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(deliver,range(16)))
        with factory() as db:
            assert db.get(BillingAccount,user_id).credits==20
            assert db.scalar(select(func.count()).select_from(BillingLedger))==1
    finally:
        with root.begin() as connection:connection.execute(text('DROP SCHEMA '+schema+' CASCADE'))
        root.dispose()


def test_real_postgres_serializes_member_daily_allowance(monkeypatch):
    url = os.environ.get('BILLING_TEST_DATABASE_URL')
    if not url: pytest.skip('Dedicated BILLING_TEST_DATABASE_URL required')
    from sqlalchemy.engine import make_url
    if make_url(url).database != 'narcissus_billing_test':
        raise RuntimeError('Refusing allowance test outside the dedicated disposable database')
    config = settings()
    monkeypatch.setattr(config, 'billing_profile', 'custom')
    monkeypatch.setattr(config, 'alipay_enabled', True)
    monkeypatch.setattr(config, 'billing_enforce_credits', True)
    monkeypatch.setattr(config, 'billing_member_daily_limit', 2)
    monkeypatch.setattr(config, 'billing_credit_costs_json', '{"quiz":5}')
    schema = 'allowance_' + uuid.uuid4().hex
    root = create_engine(url)
    with root.begin() as connection: connection.execute(text('CREATE SCHEMA ' + schema))
    engine = root.execution_options(schema_translate_map={None:schema})
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        for table in (User.__table__, *BILLING_TABLES): table.create(engine)
        with factory() as db:
            user = User(email=uid() + '@example.test', password_hash='synthetic')
            db.add(user); db.flush(); user_id = user.id
            db.add(BillingAccount(user_id=user.id, credits=100, member_until=now() + timedelta(days=1)))
            db.commit()
        def reserve(_):
            with factory() as db:
                try:
                    service.consume_credit(db, user_id, 'quiz', uid()); db.commit()
                    return True
                except HTTPException as error:
                    db.rollback()
                    assert error.status_code == 429
                    return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(reserve, range(16)))
        assert sum(results) == 2
        with factory() as db:
            assert db.get(BillingAccount, user_id).credits == 100
            assert db.scalar(select(func.count()).select_from(BillingLedger)) == 2
            assert service.member_daily_remaining(db, user_id) == 0
    finally:
        with root.begin() as connection: connection.execute(text('DROP SCHEMA ' + schema + ' CASCADE'))
        root.dispose()
