"""Immutable multi-source snapshots; preserve current PDF indexes and identifiers."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

revision = "006"
down_revision = "005"
branch_labels = depends_on = None


def upgrade():
    op.add_column("documents", sa.Column("active_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("documents", sa.Column("source_type", sa.String(16), nullable=False, server_default="pdf"))
    op.execute("UPDATE documents SET active_version=generation WHERE status='ready'")
    op.create_table("source_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("object_key", sa.String(255), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("file_hash", sa.String(64)), sa.Column("content_hash", sa.String(64)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("units", JSON(), nullable=False), sa.Column("details", JSON(), nullable=False),
        sa.Column("error", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id", "version"))
    for column in ("document_id", "file_hash", "content_hash", "status"):
        op.create_index("ix_source_versions_"+column, "source_versions", [column])
    # Deterministic ID avoids requiring an extra PostgreSQL UUID extension.
    op.execute("""INSERT INTO source_versions (id,document_id,version,title,object_key,status,units,details,error,created_at)
        SELECT id,id,generation,filename,object_key,status,'[]'::json,json_build_object('legacy',true),error,created_at FROM documents""")
    op.add_column("chunks", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("chunks", sa.Column("location", JSON(), nullable=False, server_default="{}"))
    op.execute("UPDATE chunks SET version=d.generation FROM documents d WHERE d.id=chunks.document_id")
    op.execute("""UPDATE chunks SET location=json_build_object('block_id','page-'||page,'label','第 '||page||' 页','page',page)""")
    constraints = sa.inspect(op.get_bind()).get_unique_constraints("chunks")
    for constraint in constraints:
        if constraint["column_names"] == ["document_id", "page", "ordinal"]:
            op.drop_constraint(constraint["name"], "chunks", type_="unique")
    op.create_unique_constraint("uq_chunks_version_page_ordinal", "chunks", ["document_id", "version", "page", "ordinal"])
    op.create_index("ix_chunks_document_version", "chunks", ["document_id", "version"])
    op.alter_column("chunks", "page", nullable=True)
    # Hash old private originals asynchronously, without re-OCR or model charges.
    op.execute("""INSERT INTO jobs (id,document_id,kind,generation,object_key,status,attempts,available_at,created_at)
        SELECT md5(id||':fingerprint:'||generation),id,'fingerprint',generation,object_key,'queued',0,now(),now()
        FROM documents WHERE status='ready' AND deleted_at IS NULL""")


def downgrade():
    raise RuntimeError("V5 包含历史来源快照。回滚请恢复升级前的数据库及对象存储备份。")
