"""Bounded research tasks and private preview snapshots; existing data is unchanged."""

from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = depends_on = None


def task_fields():
    return [
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("claim", sa.String(36)),
        sa.Column("error", sa.Text()),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=False),
    ]


def upgrade():
    op.alter_column("jobs", "status", type_=sa.String(24), existing_type=sa.String(20))
    op.create_table(
        "research_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "notebook_id",
            sa.String(36),
            sa.ForeignKey("notebooks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_key", sa.String(36), nullable=False),
        sa.Column("question", sa.String(1000), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("queries", sa.JSON(), nullable=False),
        sa.Column("reports", sa.JSON(), nullable=False),
        *task_fields(),
        sa.UniqueConstraint("notebook_id", "request_key"),
    )
    op.create_table(
        "research_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "research_id",
            sa.String(36),
            sa.ForeignKey("research_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("url_hash", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("units", sa.JSON(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("raw_snapshot", sa.LargeBinary()),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
        ),
        *task_fields(),
        sa.UniqueConstraint("research_id", "url_hash"),
    )
    for table, columns in (
        ("research_tasks", ["notebook_id", "status"]),
        ("research_candidates", ["research_id", "document_id", "status"]),
    ):
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade():
    op.drop_table("research_candidates")
    op.drop_table("research_tasks")
