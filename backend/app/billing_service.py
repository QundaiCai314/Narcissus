"""Persistent, merchant-authoritative billing. No client-supplied prices or success flags."""
import hashlib
import json
import re
from datetime import timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from sqlalchemy import select, or_, inspect, func, literal
from sqlalchemy.orm import aliased
from .config import settings
from .errors import fail
from .models import User, now, uid
from .billing_models import BillingAccount, PaymentOrder, BillingLedger, PaymentRefund, PaymentNotification
from .alipay_gateway import AlipayGateway, PaymentUnavailable, ProviderUnavailable


class Product(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[a-z0-9_]{1,64}$')
    title: str = Field(min_length=1, max_length=80)
    kind: str = Field(pattern=r'^(membership|credits)$')
    amount_cents: StrictInt = Field(ge=1, le=10000000)
    credits: StrictInt = Field(default=0, ge=0, le=10000000)
    member_days: StrictInt = Field(default=0, ge=0, le=3660)

    @model_validator(mode='after')
    def valid_entitlements(self):
        if self.kind == 'membership' and self.member_days < 1:
            raise ValueError('Membership duration required')
        if self.kind == 'credits' and (self.credits < 1 or self.member_days):
            raise ValueError('Credit pack must grant credits only')
        if any(char in self.title for char in '<>&\r\n'):
            raise ValueError('Plain-text title required')
        return self


def catalog():
    try:
        raw = json.loads(settings().billing_products_json)
        if not isinstance(raw, list) or len(raw) > 20:
            raise ValueError()
        products = [Product.model_validate(item) for item in raw]
        if len({p.id for p in products}) != len(products):
            raise ValueError()
        return products
    except Exception:
        raise PaymentUnavailable('商品目录配置无效，请联系管理员') from None


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def amount_matches(value, cents):
    if not isinstance(value, (str, int)) or not re.fullmatch(r'\d{1,10}(?:\.\d{1,2})?', str(value)):
        return False
    return Decimal(str(value)) == Decimal(cents) / 100


def lock_account(db, user_id):
    # A stable existing user row serializes first-account creation as well as every money operation.
    if not db.scalar(select(User.id).where(User.id == user_id).with_for_update()):
        fail(404, 'not_found', '账号不存在')
    account = db.scalar(select(BillingAccount).where(BillingAccount.user_id == user_id)
                        .with_for_update().execution_options(populate_existing=True))
    if not account:
        account = BillingAccount(user_id=user_id, credits=0)
        db.add(account)
        db.flush()
    return account


def owned_order(db, order_id, user_id):
    row = db.scalar(select(PaymentOrder).where(PaymentOrder.id == order_id, PaymentOrder.user_id == user_id))
    if not row:
        fail(404, 'not_found', '订单不存在')
    return row


def locked_order(db, order_id):
    return db.scalar(select(PaymentOrder).where(PaymentOrder.id == order_id).with_for_update()
                     .execution_options(populate_existing=True))


def merchant_matches(order, config):
    return order.app_id == config.app_id and order.seller_id == config.seller_id and order.environment == config.environment


def create_order(db, user, product_id, request_key, gateway=None):
    gateway = gateway or AlipayGateway()
    config = gateway.config
    account = lock_account(db, user.id)
    existing = db.scalar(select(PaymentOrder).where(PaymentOrder.user_id == user.id, PaymentOrder.request_key == request_key))
    if existing:
        if existing.product_id != product_id:
            fail(409, 'idempotency_conflict', '本次请求对应另一个商品，请重新选择')
        return existing
    product = next((p for p in catalog() if p.id == product_id), None)
    if not product:
        fail(404, 'product_unavailable', '商品尚未上架')
    if product.member_days and db.scalar(select(PaymentOrder.id).where(PaymentOrder.user_id == user.id,
            PaymentOrder.status == 'refund_pending', PaymentOrder.member_days > 0)):
        fail(409, 'refund_pending', '会员退款尚在确认，请稍后再购买会员')
    order_id = uid()
    order = PaymentOrder(id=order_id, out_trade_no='N' + order_id.replace('-', ''), user_id=user.id,
        request_key=request_key, app_id=config.app_id, seller_id=config.seller_id, environment=config.environment,
        product_id=product.id, title=product.title, kind=product.kind, amount_cents=product.amount_cents,
        credits=product.credits, member_days=product.member_days, status='pending', next_check_at=now())
    db.add(order)
    db.commit()
    return order


def apply_payment(db, order_id, result, config, notification=False):
    original = db.get(PaymentOrder, order_id)
    if not original:
        raise ValueError('Order missing')
    account = lock_account(db, original.user_id)
    order = locked_order(db, order_id)
    if not merchant_matches(order, config) or result.get('out_trade_no') != order.out_trade_no or not amount_matches(result.get('total_amount'), order.amount_cents):
        raise ValueError('Order identity or amount mismatch')
    if notification and (result.get('app_id') != config.app_id or result.get('seller_id') != config.seller_id):
        raise ValueError('Merchant mismatch')
    if result.get('seller_id') and result['seller_id'] != config.seller_id:
        raise ValueError('Merchant mismatch')
    if result.get('app_id') and result['app_id'] != config.app_id:
        raise ValueError('App mismatch')
    trade_no = result.get('trade_no')
    if not isinstance(trade_no, str) or not re.fullmatch(r'[A-Za-z0-9]{1,64}', trade_no):
        raise ValueError('Trade identifier required')
    if order.trade_no and order.trade_no != trade_no:
        raise ValueError('Trade identifier changed')
    if db.scalar(select(PaymentOrder.id).where(PaymentOrder.trade_no == trade_no, PaymentOrder.id != order.id)):
        raise ValueError('Trade identifier belongs to a different order')
    event_is_payment = not any(result.get(k) for k in ('out_biz_no', 'gmt_refund', 'refund_fee'))
    status = result.get('trade_status')
    if status in ('TRADE_SUCCESS', 'TRADE_FINISHED') and event_is_payment:
        if order.status in ('refund_pending', 'refunded', 'review_required'):
            return order
        if not db.get(BillingLedger, 'grant:' + order.id):
            order.trade_no, order.paid_at, order.status = trade_no, now(), 'paid'
            account.credits += order.credits
            if order.member_days:
                order.member_start = max(now(), utc(account.member_until) or now())
                order.member_end = order.member_start + timedelta(days=order.member_days)
                account.member_until = order.member_end
            db.add(BillingLedger(event_key='grant:' + order.id, user_id=order.user_id,
                                 order_id=order.id, delta=order.credits, kind='purchase'))
    elif status == 'TRADE_CLOSED' and order.status == 'pending':
        order.status = 'closed'
    return order


def refresh_order(db, order, gateway=None):
    gateway = gateway or AlipayGateway()
    if not merchant_matches(order, gateway.config):
        raise PaymentUnavailable('订单属于不同支付配置，请联系管理员核对')
    try:
        result = gateway.query(order)
        if result.get('code') == '10000':
            order = apply_payment(db, order.id, result, gateway.config)
            order.check_error = None
        else:
            order.check_error = 'provider_pending'
    except ProviderUnavailable:
        order.check_error = 'provider_unavailable'
    except ValueError:
        db.rollback()
        order = db.get(PaymentOrder, order.id)
        order.check_error = 'response_mismatch'
    order.check_attempts += 1
    order.next_check_at = now() + timedelta(seconds=min(3600, 15 * 2 ** min(order.check_attempts, 8)))
    db.commit()
    return order


def handle_notification(db, params, gateway=None):
    gateway = gateway or AlipayGateway()
    if not gateway.verify_notification(params):
        return False
    if params.get('notify_type') != 'trade_status_sync' or not params.get('notify_id'):
        return False
    order = db.scalar(select(PaymentOrder).where(PaymentOrder.out_trade_no == params.get('out_trade_no')))
    if not order:
        return False
    event_type = 'refund' if any(params.get(k) for k in ('out_biz_no', 'gmt_refund', 'refund_fee')) else params.get('trade_status', 'unknown')
    key = hashlib.sha256('|'.join((gateway.config.app_id, params['notify_id'], order.out_trade_no,
                                  params.get('trade_no', ''), event_type)).encode()).hexdigest()
    lock_account(db, order.user_id)
    if db.get(PaymentNotification, key):
        return True
    try:
        apply_payment(db, order.id, params, gateway.config, notification=True)
        db.add(PaymentNotification(event_key=key, order_id=order.id, event_type=event_type[:40]))
        db.commit()
        return True
    except Exception:
        db.rollback()
        return False


def close_order(db, order, gateway=None):
    gateway = gateway or AlipayGateway()
    order = refresh_order(db, order, gateway)
    if order.status != 'pending':
        return order
    try:
        result = gateway.close(order)
        if result.get('code') == '10000' and result.get('out_trade_no') == order.out_trade_no:
            lock_account(db, order.user_id)
            current = locked_order(db, order.id)
            if current.status == 'pending':
                current.status = 'closed'
            db.commit()
            return current
    except ProviderUnavailable:
        pass
    return order


def reserve_refund(db, order, gateway=None):
    gateway = gateway or AlipayGateway()
    account = lock_account(db, order.user_id)
    order = locked_order(db, order.id)
    if not merchant_matches(order, gateway.config):
        raise PaymentUnavailable('支付配置与订单不一致')
    existing = db.scalar(select(PaymentRefund).where(PaymentRefund.order_id == order.id))
    if existing:
        return existing
    if order.status != 'paid' or account.credits < order.credits:
        fail(409, 'refund_requires_review', '订单未支付或对应额度已使用，需人工核对退款方案')
    if order.member_days:
        if utc(account.member_until) != utc(order.member_end):
            fail(409, 'refund_requires_review', '会员已与后续订单叠加，请先核对后续订单')
        account.member_until = max(now(), utc(order.member_start))
    account.credits -= order.credits
    order.status = 'refund_pending'
    refund = PaymentRefund(id=uid(), order_id=order.id, amount_cents=order.amount_cents, status='pending')
    db.add(refund)
    db.add(BillingLedger(event_key='refund-reserve:' + order.id, user_id=order.user_id,
                         order_id=order.id, delta=-order.credits, kind='refund_reservation'))
    db.commit()
    return refund


def refund_result_matches(order, refund, data, query=False):
    amount_key = 'refund_amount' if query else 'refund_fee'
    return (data.get('code') == '10000' and data.get('out_trade_no') == order.out_trade_no
        and data.get('trade_no') == order.trade_no and amount_matches(data.get(amount_key), refund.amount_cents)
        and (data.get('out_request_no') == refund.id if query else True)
        and (data.get('refund_status') == 'REFUND_SUCCESS' if query else data.get('fund_change') == 'Y'))


def send_or_query_refund(db, refund, gateway=None, send=False):
    gateway = gateway or AlipayGateway()
    order = db.get(PaymentOrder, refund.order_id)
    if refund.status == 'succeeded':
        return refund
    if not merchant_matches(order, gateway.config):
        raise PaymentUnavailable('支付配置与订单不一致')
    last = utc(refund.last_attempt_at)
    if last and now() - last < timedelta(seconds=10):
        return refund
    refund.last_attempt_at = now()
    db.commit()
    try:
        data = gateway.refund(order, refund) if send else gateway.refund_query(order, refund)
        if refund_result_matches(order, refund, data, query=not send):
            lock_account(db, order.user_id)
            order = locked_order(db, order.id)
            refund.status, refund.confirmed_at, order.status = 'succeeded', now(), 'refunded'
            db.commit()
        elif not send and (not last or now() - last >= timedelta(seconds=60)):
            # Same immutable refund ID and amount are reused after an unknown result.
            data = gateway.refund(order, refund)
            if refund_result_matches(order, refund, data):
                lock_account(db, order.user_id)
                order = locked_order(db, order.id)
                refund.status, refund.confirmed_at, order.status = 'succeeded', now(), 'refunded'
                db.commit()
    except ProviderUnavailable:
        pass
    return refund


def credit_cost(kind):
    try:
        costs = json.loads(settings().billing_credit_costs_json)
        if not isinstance(costs, dict):
            raise ValueError()
        cost = costs.get(kind, 0)
        if type(cost) is not int or not 0 <= cost <= 100000:
            raise ValueError()
        return cost
    except Exception:
        fail(503, 'billing_unavailable', '额度配置需要管理员核对')


def learning_quote(db, user_id):
    if not settings().billing_enforce_credits:
        return dict(enforced=False, costs={})
    if not settings().alipay_enabled:
        fail(503, 'billing_unavailable', '计费服务暂不可用')
    account = db.get(BillingAccount, user_id)
    member = bool(account and account.member_until and utc(account.member_until) > now())
    return dict(enforced=True, credits=account.credits if account else 0, member_active=member,
                costs={kind: 0 if member else credit_cost(kind) for kind in ('quiz', 'mindmap', 'flashcards')})


def consume_credit(db, user_id, kind, request_key):
    """Join the caller's job-creation transaction. Existing limits stay in force."""
    if not settings().billing_enforce_credits:
        return
    if not settings().alipay_enabled:
        fail(503, 'billing_unavailable', '计费服务暂不可用')
    cost = credit_cost(kind)
    if not cost:
        return
    account = lock_account(db, user_id)
    key = 'usage:' + str(request_key)
    existing = db.get(BillingLedger, key)
    if existing:
        if existing.user_id != user_id:
            fail(409, 'idempotency_conflict', '请求标识已被使用')
        return
    if account.member_until and utc(account.member_until) > now():
        cost = 0
    if account.credits < cost:
        fail(402, 'insufficient_credits', '使用额度不足，可前往会员与额度页面购买')
    account.credits -= cost
    db.add(BillingLedger(event_key=key, user_id=user_id, delta=-cost, kind=kind))


def restore_credit(db, request_key):
    if not inspect(db.get_bind()).has_table('billing_ledger'):
        return
    prefix = 'usage:' + str(request_key)
    originals = db.scalars(select(BillingLedger).where(or_(BillingLedger.event_key == prefix,
        BillingLedger.event_key.like(prefix + ':%')))).all()
    for original in originals:
        account = lock_account(db, original.user_id)
        key = 'restored:' + original.event_key
        if not db.get(BillingLedger, key):
            account.credits -= original.delta
            db.add(BillingLedger(event_key=key, user_id=original.user_id, delta=-original.delta, kind='failed_job_restored'))


def order_view(order):
    return dict(id=order.id, product_id=order.product_id, title=order.title, kind=order.kind,
        amount_cents=order.amount_cents, credits=order.credits, member_days=order.member_days,
        status=order.status, environment=order.environment, created_at=order.created_at,
        paid_at=order.paid_at, confirmation_pending=bool(order.check_error))


def reconcile(session_factory, limit=20):
    """Server-side recovery survives a closed browser and a restarted API process."""
    gateway = AlipayGateway()
    with session_factory() as db:
        rows = db.scalars(select(PaymentOrder).where(PaymentOrder.status == 'pending',
            PaymentOrder.next_check_at <= now(), PaymentOrder.environment == gateway.config.environment,
            PaymentOrder.app_id == gateway.config.app_id).order_by(PaymentOrder.next_check_at)
            .with_for_update(skip_locked=True).limit(limit)).all()
        ids = [row.id for row in rows]
        for row in rows:
            row.next_check_at = now() + timedelta(minutes=2)
        db.commit()
    for order_id in ids:
        with session_factory() as db:
            refresh_order(db, db.get(PaymentOrder, order_id), gateway)
    with session_factory() as db:
        refunds = db.scalars(select(PaymentRefund).join(PaymentOrder).where(PaymentRefund.status == 'pending',
            PaymentOrder.environment == gateway.config.environment, PaymentOrder.app_id == gateway.config.app_id)
            .limit(limit)).all()
        for refund in refunds:
            send_or_query_refund(db, refund, gateway)
    # Covers cancellations caused by changed/deleted sources and interrupted workers as well.
    from .models import LearningSet
    with session_factory() as db:
        restored = aliased(BillingLedger)
        failed = db.scalars(select(LearningSet.request_key)
            .join(BillingLedger, func.substr(BillingLedger.event_key, 7, 36) == LearningSet.request_key)
            .outerjoin(restored, restored.event_key == literal('restored:') + BillingLedger.event_key)
            .where(LearningSet.status.in_(('failed', 'cancelled')), BillingLedger.event_key.like('usage:%'),
                   restored.event_key.is_(None)).limit(100)).all()
        for request_key in failed:
            restore_credit(db, request_key)
        db.commit()
