"""Opt-in migration test; can only target the disposable billing test database."""
import os
import uuid
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from app.config import settings


def test_billing_upgrade_preserves_existing_users_and_notebooks():
    url = os.environ.get('BILLING_MIGRATION_TEST_URL', '')
    if not url:
        pytest.skip('Dedicated migration database not requested')
    if 'narcissus_billing_test' not in url:
        raise RuntimeError('Refusing migration outside dedicated disposable database')
    previous = settings().database_url
    settings().database_url = url
    engine = create_engine(url)
    try:
        if inspect(engine).get_table_names():
            pytest.skip('Migration probe requires a fresh disposable database; never resets existing tables')
        config = Config('alembic.ini')
        command.upgrade(config, '010')
        user_id, notebook_id = str(uuid.uuid4()), str(uuid.uuid4())
        with engine.begin() as db:
            db.execute(text("INSERT INTO users(id,email,password_hash,created_at) VALUES (:id,'migration-fixture@example.com','synthetic',now())"), {'id':user_id})
            db.execute(text("INSERT INTO notebooks(id,user_id,name,created_at,updated_at) VALUES (:id,:user_id,'Existing test notebook',now(),now())"), {'id':notebook_id,'user_id':user_id})
        command.upgrade(config, '011')
        with engine.connect() as db:
            assert db.scalar(text('SELECT name FROM notebooks WHERE id=:id'),{'id':notebook_id}) == 'Existing test notebook'
            assert db.scalar(text('SELECT email FROM users WHERE id=:id'),{'id':user_id}) == 'migration-fixture@example.com'
            assert db.scalar(text('SELECT version_num FROM alembic_version')) == '011'
        assert {'billing_accounts','billing_ledger','payment_orders','payment_refunds','payment_notifications'} <= set(inspect(engine).get_table_names())
    finally:
        settings().database_url = previous
        engine.dispose()
