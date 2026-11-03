CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE users (
	id VARCHAR(36) NOT NULL, 
	email VARCHAR(254) NOT NULL, 
	password_hash TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (email)
);

CREATE TABLE login_sessions (
	token_hash VARCHAR(64) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (token_hash), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_login_sessions_expires_at ON login_sessions (expires_at);

CREATE INDEX ix_login_sessions_user_id ON login_sessions (user_id);

CREATE TABLE notebooks (
	id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_notebooks_user_id ON notebooks (user_id);

CREATE INDEX ix_notebooks_updated_at ON notebooks (updated_at);

CREATE TABLE documents (
	id VARCHAR(36) NOT NULL, 
	notebook_id VARCHAR(36) NOT NULL, 
	filename VARCHAR(255) NOT NULL, 
	object_key VARCHAR(255) NOT NULL, 
	size INTEGER NOT NULL, 
	pages INTEGER, 
	status VARCHAR(24) NOT NULL, 
	error TEXT, 
	generation INTEGER NOT NULL, 
	embedding_model VARCHAR(200), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(notebook_id) REFERENCES notebooks (id) ON DELETE CASCADE, 
	UNIQUE (object_key)
);

CREATE INDEX ix_documents_notebook_id ON documents (notebook_id);

CREATE INDEX ix_documents_status ON documents (status);

CREATE TABLE conversations (
	id VARCHAR(36) NOT NULL, 
	notebook_id VARCHAR(36) NOT NULL, 
	title VARCHAR(120) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(notebook_id) REFERENCES notebooks (id) ON DELETE CASCADE
);

CREATE INDEX ix_conversations_notebook_id ON conversations (notebook_id);

CREATE TABLE jobs (
	id VARCHAR(36) NOT NULL, 
	document_id VARCHAR(36), 
	kind VARCHAR(20) NOT NULL, 
	generation INTEGER NOT NULL, 
	object_key VARCHAR(255) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	attempts INTEGER NOT NULL, 
	claim VARCHAR(36), 
	error TEXT, 
	usage JSON, 
	available_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE, 
	dispatched_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (document_id, kind, generation), 
	FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE SET NULL
);

CREATE INDEX ix_jobs_document_id ON jobs (document_id);

CREATE INDEX ix_jobs_status ON jobs (status);

CREATE INDEX ix_jobs_available_at ON jobs (available_at);

CREATE TABLE chunks (
	id VARCHAR(36) NOT NULL, 
	document_id VARCHAR(36) NOT NULL, 
	page INTEGER NOT NULL, 
	ordinal INTEGER NOT NULL, 
	text TEXT NOT NULL, 
	embedding VECTOR NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (document_id, page, ordinal), 
	FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE
);

CREATE INDEX ix_chunks_document_id ON chunks (document_id);

CREATE TABLE messages (
	id VARCHAR(36) NOT NULL, 
	conversation_id VARCHAR(36) NOT NULL, 
	role VARCHAR(16) NOT NULL, 
	in_reply_to VARCHAR(36), 
	content TEXT NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	error TEXT, 
	source_ids JSON, 
	usage JSON, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	heartbeat_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE, 
	FOREIGN KEY(in_reply_to) REFERENCES messages (id) ON DELETE SET NULL
);

CREATE INDEX ix_messages_status ON messages (status);

CREATE UNIQUE INDEX one_generation_per_conversation ON messages (conversation_id) WHERE status = 'generating';

CREATE INDEX ix_messages_conversation_id ON messages (conversation_id);

CREATE INDEX ix_messages_heartbeat_at ON messages (heartbeat_at);

CREATE TABLE citations (
	id VARCHAR(36) NOT NULL, 
	message_id VARCHAR(36) NOT NULL, 
	chunk_id VARCHAR(36) NOT NULL, 
	label INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (message_id, label), 
	FOREIGN KEY(message_id) REFERENCES messages (id) ON DELETE CASCADE, 
	FOREIGN KEY(chunk_id) REFERENCES chunks (id) ON DELETE CASCADE
);

CREATE INDEX ix_citations_message_id ON citations (message_id);

CREATE INDEX ix_citations_chunk_id ON citations (chunk_id);