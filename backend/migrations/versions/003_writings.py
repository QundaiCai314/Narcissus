"""Add notes, guides, summary documents, immutable citation snapshots and generation outbox."""

from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE writings (
      id varchar(36) PRIMARY KEY, notebook_id varchar(36) NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
      kind varchar(16) NOT NULL, title varchar(120) NOT NULL, content text NOT NULL,
      version integer NOT NULL, edited boolean NOT NULL,
      document_id varchar(36) UNIQUE REFERENCES documents(id) ON DELETE SET NULL,
      source_message_id varchar(36) UNIQUE REFERENCES messages(id) ON DELETE SET NULL,
      details json NOT NULL, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL);
    CREATE INDEX ix_writings_notebook_id ON writings(notebook_id);
    CREATE INDEX ix_writings_updated_at ON writings(updated_at);
    CREATE TABLE writing_citations (
      id varchar(36) PRIMARY KEY, writing_id varchar(36) NOT NULL REFERENCES writings(id) ON DELETE CASCADE,
      label integer NOT NULL, snapshot json NOT NULL, UNIQUE(writing_id, label));
    CREATE INDEX ix_writing_citations_writing_id ON writing_citations(writing_id);
    CREATE TABLE generation_jobs (
      id varchar(36) PRIMARY KEY, writing_id varchar(36) NOT NULL REFERENCES writings(id) ON DELETE CASCADE,
      generation integer NOT NULL, status varchar(20) NOT NULL, request json NOT NULL,
      attempts integer NOT NULL, claim varchar(36), error text, usage json,
      available_at timestamptz NOT NULL, started_at timestamptz, dispatched_at timestamptz,
      created_at timestamptz NOT NULL, UNIQUE(writing_id, generation));
    CREATE INDEX ix_generation_jobs_writing_id ON generation_jobs(writing_id);
    CREATE INDEX ix_generation_jobs_status ON generation_jobs(status);
    CREATE INDEX ix_generation_jobs_available_at ON generation_jobs(available_at);
    CREATE UNIQUE INDEX one_active_writing_job ON generation_jobs(writing_id) WHERE status IN ('queued','running');
    """)


def downgrade():
    op.execute(
        "DROP TABLE generation_jobs; DROP TABLE writing_citations; DROP TABLE writings;"
    )
