"""Add billing tables. Existing users, documents and vectors are not modified."""
from alembic import op
import sqlalchemy as sa

revision = '011'
down_revision = '010'
branch_labels = depends_on = None


def upgrade():
    op.create_table('billing_accounts',
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('credits', sa.Integer(), nullable=False),
        sa.Column('member_until', sa.DateTime(timezone=True)),
        sa.CheckConstraint('credits >= 0', name='ck_billing_credits_nonnegative'))
    op.create_table('payment_orders',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('request_key', sa.String(36), nullable=False),
        sa.Column('out_trade_no', sa.String(64), unique=True, nullable=False),
        sa.Column('app_id', sa.String(32), nullable=False),
        sa.Column('seller_id', sa.String(32), nullable=False),
        sa.Column('environment', sa.String(16), nullable=False),
        sa.Column('product_id', sa.String(64), nullable=False),
        sa.Column('title', sa.String(120), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('amount_cents', sa.Integer(), nullable=False),
        sa.Column('credits', sa.Integer(), nullable=False),
        sa.Column('member_days', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('trade_no', sa.String(64), unique=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('paid_at', sa.DateTime(timezone=True)),
        sa.Column('member_start', sa.DateTime(timezone=True)),
        sa.Column('member_end', sa.DateTime(timezone=True)),
        sa.Column('next_check_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('check_attempts', sa.Integer(), nullable=False),
        sa.Column('check_error', sa.String(40)),
        sa.UniqueConstraint('user_id', 'request_key', name='uq_payment_request'),
        sa.CheckConstraint('amount_cents > 0 AND credits >= 0 AND member_days >= 0', name='ck_payment_values'))
    for column in ('user_id', 'status', 'next_check_at'):
        op.create_index('ix_payment_orders_' + column, 'payment_orders', [column])
    op.create_table('billing_ledger',
        sa.Column('event_key', sa.String(128), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('order_id', sa.String(36), sa.ForeignKey('payment_orders.id')),
        sa.Column('delta', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(24), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_billing_ledger_user_id', 'billing_ledger', ['user_id'])
    op.create_table('payment_refunds',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('order_id', sa.String(36), sa.ForeignKey('payment_orders.id'), unique=True, nullable=False),
        sa.Column('amount_cents', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_attempt_at', sa.DateTime(timezone=True)),
        sa.Column('confirmed_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint('amount_cents > 0', name='ck_refund_positive'))
    op.create_table('payment_notifications',
        sa.Column('event_key', sa.String(64), primary_key=True),
        sa.Column('order_id', sa.String(36), sa.ForeignKey('payment_orders.id'), nullable=False),
        sa.Column('event_type', sa.String(40), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_payment_notifications_order_id', 'payment_notifications', ['order_id'])


def downgrade():
    for table in ('payment_notifications', 'payment_refunds', 'billing_ledger', 'payment_orders', 'billing_accounts'):
        op.drop_table(table)
