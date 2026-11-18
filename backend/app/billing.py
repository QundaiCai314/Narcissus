import asyncio
import base64
import hashlib
import logging
from datetime import timedelta
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID
from typing import Literal
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import inspect, select
from .db import db_session, SessionLocal
from .config import settings
from .models import now
from .security import current_user, rate_limit
from .errors import fail
from .alipay_gateway import AlipayGateway, PaymentUnavailable, ProviderUnavailable
from .billing_models import BillingAccount, PaymentOrder, PaymentRefund
from . import billing_service as service

router = APIRouter(prefix='/billing', tags=['订单与收款'])
log = logging.getLogger('narcissus.billing')


def gateway_ready(db):
    if not settings().alipay_enabled:
        fail(503, 'billing_unavailable', '收款尚未开通')
    try:
        gateway = AlipayGateway()
        if not all(inspect(db.get_bind()).has_table(name) for name in
                   ('billing_accounts', 'payment_orders', 'billing_ledger', 'payment_refunds', 'payment_notifications')):
            raise PaymentUnavailable('计费数据库尚未初始化，请联系管理员')
        return gateway
    except PaymentUnavailable as error:
        fail(503, 'billing_unavailable', str(error))


def operator(user):
    allowed = {item.strip().lower() for item in settings().billing_operator_emails.split(',') if item.strip()}
    if user.email.lower() not in allowed:
        fail(403, 'forbidden', '此操作仅限指定的收款管理账号')


class NewOrder(BaseModel):
    model_config = ConfigDict(extra='forbid')
    product_id: str = Field(pattern=r'^[a-z0-9_]{1,64}$')
    request_key: UUID


class FullRefund(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirm_full_refund: Literal[True]


@router.get('/catalog')
def catalog(db=Depends(db_session)):
    if not settings().alipay_enabled:
        return dict(available=False, products=[], environment=None, message='收款尚未开通')
    try:
        gateway = gateway_ready(db)
        return dict(available=True, products=[p.model_dump() for p in service.catalog()],
                    environment=gateway.config.environment, member_daily_limit=service.member_daily_limit(),
                    credit_costs={kind: service.credit_cost(kind) for kind in ('quiz', 'mindmap', 'flashcards')})
    except Exception:
        return dict(available=False, products=[], environment=None, message='收款暂不可用，请稍后再试')


@router.get('/wallet')
def wallet(user=Depends(current_user), db=Depends(db_session)):
    gateway_ready(db)
    account = db.get(BillingAccount, user.id)
    member = bool(account and account.member_until and service.utc(account.member_until) > now())
    return dict(credits=account.credits if account else 0, member_until=account.member_until if account else None,
                member_active=member, member_daily_limit=service.member_daily_limit(),
                member_daily_remaining=service.member_daily_remaining(db, user.id) if member else None)


@router.get('/learning-quote')
def learning_quote(user=Depends(current_user), db=Depends(db_session)):
    if settings().billing_enforce_credits:
        gateway_ready(db)
    return service.learning_quote(db, user.id)


@router.get('/orders')
def orders(user=Depends(current_user), db=Depends(db_session)):
    gateway_ready(db)
    rows = db.scalars(select(PaymentOrder).where(PaymentOrder.user_id == user.id)
                      .order_by(PaymentOrder.created_at.desc()).limit(30)).all()
    return {'items': [service.order_view(row) for row in rows]}


@router.post('/orders', status_code=201)
def create(data: NewOrder, user=Depends(current_user), db=Depends(db_session)):
    gateway = gateway_ready(db)
    rate_limit('billing-order:' + user.id, 15, 3600)
    return service.order_view(service.create_order(db, user, data.product_id, str(data.request_key), gateway))


@router.get('/orders/{order_id}')
def get_order(order_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    gateway_ready(db)
    return service.order_view(service.owned_order(db, str(order_id), user.id))


@router.get('/orders/{order_id}/pay', response_class=HTMLResponse)
def pay(order_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    gateway = gateway_ready(db)
    order = service.owned_order(db, str(order_id), user.id)
    if order.status != 'pending' or not service.merchant_matches(order, gateway.config):
        fail(409, 'order_not_payable', '当前订单不能继续付款，请刷新订单状态')
    if now() - service.utc(order.created_at) > timedelta(minutes=15):
        fail(409, 'payment_entry_expired', '付款入口已过期，请刷新订单状态后重新下单')
    try:
        form = gateway.payment_form(order).replace('<form name=', '<form id="alipay-checkout" name=', 1)
    except ProviderUnavailable as error:
        fail(503, 'payment_unavailable', str(error))
    script_hash = base64.b64encode(hashlib.sha256(b'document.forms[0].submit();').digest()).decode()
    origin = urlsplit(gateway.config.gateway)
    csp = (f"default-src 'none'; form-action {origin.scheme}://{origin.netloc}; "
           f"script-src 'sha256-{script_hash}'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'")
    page = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>前往支付宝 · Narcissus</title>'
            '<body><p>正在前往支付宝，请在支付宝页面核对金额后付款。</p>' + form +
            '<noscript><button type="submit" form="alipay-checkout">继续付款</button></noscript></body></html>')
    return HTMLResponse(page, headers={'Content-Security-Policy': csp, 'Cache-Control': 'no-store',
                                      'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY'})


@router.post('/orders/{order_id}/refresh')
def refresh(order_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    gateway = gateway_ready(db)
    order = service.owned_order(db, str(order_id), user.id)
    rate_limit('billing-refresh:' + user.id, 20, 60)
    if order.status == 'pending':
        order = service.refresh_order(db, order, gateway)
    return service.order_view(order)


@router.post('/orders/{order_id}/close')
def close(order_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    gateway = gateway_ready(db)
    order = service.owned_order(db, str(order_id), user.id)
    rate_limit('billing-close:' + user.id, 10, 60)
    return service.order_view(service.close_order(db, order, gateway))


@router.post('/orders/{order_id}/refund', status_code=202)
def refund(order_id: UUID, data: FullRefund, user=Depends(current_user), db=Depends(db_session)):
    operator(user)
    gateway = gateway_ready(db)
    order = db.get(PaymentOrder, str(order_id))
    if not order:
        fail(404, 'not_found', '订单不存在')
    rate_limit('billing-refund:' + user.id, 10, 60)
    refund = service.reserve_refund(db, order, gateway)
    refund = service.send_or_query_refund(db, refund, gateway, send=True)
    return dict(id=refund.id, order_id=refund.order_id, amount_cents=refund.amount_cents, status=refund.status)


@router.get('/refunds/{refund_id}')
def refund_query(refund_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    gateway = gateway_ready(db)
    refund = db.get(PaymentRefund, str(refund_id))
    if not refund:
        fail(404, 'not_found', '退款记录不存在')
    order = db.get(PaymentOrder, refund.order_id)
    if order.user_id != user.id:
        operator(user)
    refund = service.send_or_query_refund(db, refund, gateway)
    return dict(id=refund.id, order_id=refund.order_id, amount_cents=refund.amount_cents, status=refund.status)


@router.post('/alipay/notify', response_class=PlainTextResponse)
async def notify(request: Request, db=Depends(db_session)):
    try:
        if not settings().alipay_enabled:
            return PlainTextResponse('fail', status_code=503)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 65536:
                return PlainTextResponse('fail', status_code=413)
        if request.headers.get('content-type', '').split(';')[0].lower() != 'application/x-www-form-urlencoded':
            return PlainTextResponse('fail')
        pairs = parse_qsl(body.decode('utf-8'), keep_blank_values=True, max_num_fields=64)
        params = dict(pairs)
        if len(params) != len(pairs):
            return PlainTextResponse('fail')
        # Blocking SDK/DB operations run off the event loop, like ordinary synchronous routes.
        result = await asyncio.to_thread(service.handle_notification, db, params)
        return PlainTextResponse('success' if result else 'fail')
    except Exception:
        db.rollback()
        return PlainTextResponse('fail')


async def reconcile_loop():
    while True:
        try:
            await asyncio.to_thread(service.reconcile, SessionLocal)
        except asyncio.CancelledError:
            raise
        except Exception:
            # No provider responses, signatures, keys or account details in logs.
            log.warning('billing_reconciliation_pending')
        await asyncio.sleep(30)
