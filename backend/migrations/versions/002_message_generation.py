"""Fence stopped/retried answer streams so an old stream cannot overwrite a new one."""

from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "messages",
        sa.Column("generation", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade():
    op.drop_column("messages", "generation")
