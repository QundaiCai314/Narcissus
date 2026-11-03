"""Audio script revisions, immutable render snapshots, segments and durable blob cleanup ledger."""
from alembic import op
revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("""

CREATE TABLE audio_overviews (
	id VARCHAR(36) NOT NULL, 
	notebook_id VARCHAR(36) NOT NULL, 
	request_key VARCHAR(36) NOT NULL, 
	title VARCHAR(120) NOT NULL, 
	params JSON NOT NULL, 
	sources JSON NOT NULL, 
	citations JSON NOT NULL, 
	script JSON NOT NULL, 
	revision INTEGER NOT NULL, 
	model VARCHAR(200), 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	status VARCHAR(24) NOT NULL, 
	attempts INTEGER NOT NULL, 
	claim VARCHAR(36), 
	error TEXT, 
	available_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE, 
	dispatched_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	usage JSON NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (notebook_id, request_key), 
	FOREIGN KEY(notebook_id) REFERENCES notebooks (id) ON DELETE CASCADE
)

;
CREATE INDEX ix_audio_overviews_notebook_id ON audio_overviews (notebook_id);
CREATE INDEX ix_audio_overviews_status ON audio_overviews (status);

CREATE TABLE audio_renders (
	id VARCHAR(36) NOT NULL, 
	overview_id VARCHAR(36) NOT NULL, 
	request_key VARCHAR(36) NOT NULL, 
	revision INTEGER NOT NULL, 
	snapshot JSON NOT NULL, 
	voices JSON NOT NULL, 
	model VARCHAR(200) NOT NULL, 
	provider VARCHAR(500) NOT NULL, 
	duration_ms INTEGER, 
	timeline JSON NOT NULL, 
	object_key VARCHAR(500) NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	attempts INTEGER NOT NULL, 
	claim VARCHAR(36), 
	error TEXT, 
	available_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE, 
	dispatched_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	usage JSON NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (overview_id, request_key), 
	FOREIGN KEY(overview_id) REFERENCES audio_overviews (id) ON DELETE CASCADE
)

;
CREATE INDEX ix_audio_renders_overview_id ON audio_renders (overview_id);
CREATE INDEX ix_audio_renders_status ON audio_renders (status);

CREATE TABLE audio_segments (
	id VARCHAR(36) NOT NULL, 
	render_id VARCHAR(36) NOT NULL, 
	ordinal INTEGER NOT NULL, 
	paragraph_id VARCHAR(40) NOT NULL, 
	text TEXT NOT NULL, 
	voice VARCHAR(100) NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	attempts INTEGER NOT NULL, 
	duration_ms INTEGER, 
	object_key VARCHAR(500) NOT NULL, 
	usage JSON NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (render_id, ordinal), 
	FOREIGN KEY(render_id) REFERENCES audio_renders (id) ON DELETE CASCADE
)

;
CREATE INDEX ix_audio_segments_render_id ON audio_segments (render_id);

CREATE TABLE audio_blobs (
	object_key VARCHAR(500) NOT NULL, 
	notebook_id VARCHAR(36) NOT NULL, 
	overview_id VARCHAR(36) NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	attempts INTEGER NOT NULL, 
	error TEXT, 
	available_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (object_key)
)

;
CREATE INDEX ix_audio_blobs_notebook_id ON audio_blobs (notebook_id);
CREATE INDEX ix_audio_blobs_overview_id ON audio_blobs (overview_id);
CREATE INDEX ix_audio_blobs_status ON audio_blobs (status);
    """)

def downgrade():
    op.execute("DROP TABLE audio_segments; DROP TABLE audio_renders; DROP TABLE audio_overviews; DROP TABLE audio_blobs")
