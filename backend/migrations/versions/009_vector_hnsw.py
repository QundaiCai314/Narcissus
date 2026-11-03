"""Add HNSW index on chunks.embedding for fast approximate nearest neighbor search."""
from alembic import op

revision = "009"
down_revision = "008"
branch_labels = depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1024);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw "
        "ON chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64);"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw;")
    op.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE vector;")
