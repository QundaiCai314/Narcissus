from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
from .models import uid, now


class BillingAccount(Base):
    __tablename__ = 'billing_accounts'
    __table_args__ = (CheckConstraint('credits >= 0', name='ck_billing_credits_nonnegative'),)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    credits: Mapped[int] = mapped_column(Integer, default=0)
    member_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaymentOrder(Base):
    __tablename__ = 'payment_orders'
    __table_args__ = (UniqueConstraint('user_id', 'request_key', name='uq_payment_request'),
                     CheckConstraint('amount_cents > 0 AND credits >= 0 AND member_days >= 0', name='ck_payment_values'))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    request_key: Mapped[str] = mapped_column(String(36))
    out_trade_no: Mapped[str] = mapped_column(String(64), unique=True)
    app_id: Mapped[str] = mapped_column(String(32))
    seller_id: Mapped[str] = mapped_column(String(32))
    environment: Mapped[str] = mapped_column(String(16))
    product_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16))
    amount_cents: Mapped[int] = mapped_column(Integer)
    credits: Mapped[int] = mapped_column(Integer, default=0)
    member_days: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default='pending', index=True)
    trade_no: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    member_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    member_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    check_attempts: Mapped[int] = mapped_column(Integer, default=0)
    check_error: Mapped[str | None] = mapped_column(String(40))


class BillingLedger(Base):
    __tablename__ = 'billing_ledger'
    event_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    order_id: Mapped[str | None] = mapped_column(ForeignKey('payment_orders.id'))
    delta: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PaymentRefund(Base):
    __tablename__ = 'payment_refunds'
    __table_args__ = (CheckConstraint('amount_cents > 0', name='ck_refund_positive'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    order_id: Mapped[str] = mapped_column(ForeignKey('payment_orders.id'), unique=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default='pending')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaymentNotification(Base):
    __tablename__ = 'payment_notifications'
    event_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey('payment_orders.id'), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


BILLING_TABLES = (BillingAccount.__table__, PaymentOrder.__table__, BillingLedger.__table__,
                  PaymentRefund.__table__, PaymentNotification.__table__)
