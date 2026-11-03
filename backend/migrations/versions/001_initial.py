"""Initial schema snapshot, independent from future ORM changes."""

from pathlib import Path
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    sql = (Path(__file__).parents[1] / "001_initial.sql").read_text(encoding="utf-8")
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade():
    for table in (
        "citations",
        "messages",
        "conversations",
        "chunks",
        "jobs",
        "documents",
        "notebooks",
        "login_sessions",
        "users",
    ):
        op.drop_table(table)
