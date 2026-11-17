"""Add opt-in, authenticated note collaboration. No existing rows are changed."""
from alembic import op
import sqlalchemy as sa
revision='010'
down_revision='009'
branch_labels=depends_on=None
def upgrade():
    op.create_table('notebook_members',sa.Column('notebook_id',sa.String(36),sa.ForeignKey('notebooks.id',ondelete='CASCADE'),primary_key=True),sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id',ondelete='CASCADE'),primary_key=True),sa.Column('role',sa.String(16),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.CheckConstraint("role IN ('viewer','editor')",name='ck_notebook_member_role'))
def downgrade():
    op.drop_table('notebook_members')
