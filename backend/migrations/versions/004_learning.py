"""Add versioned learning publications, flashcard progress, quiz attempts, and trusted chat context."""

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE messages ADD COLUMN learning_context json;
    CREATE TABLE learning_sets (
      id varchar(36) PRIMARY KEY, notebook_id varchar(36) NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
      family_id varchar(36) NOT NULL, version integer NOT NULL, request_key varchar(36) NOT NULL,
      kind varchar(16) NOT NULL CHECK (kind IN ('mindmap','flashcards','quiz')), title varchar(120) NOT NULL,
      params json NOT NULL, sources json NOT NULL, status varchar(20) NOT NULL,
      phase varchar(32) NOT NULL, result json NOT NULL, citations json NOT NULL, removed_cards json NOT NULL,
      model varchar(200), warning text, error text, attempts integer NOT NULL, claim varchar(36), usage json NOT NULL,
      available_at timestamptz NOT NULL, started_at timestamptz, dispatched_at timestamptz,
      created_at timestamptz NOT NULL, completed_at timestamptz,
      UNIQUE(family_id,version), UNIQUE(notebook_id,request_key));
    CREATE INDEX ix_learning_sets_notebook_id ON learning_sets(notebook_id);
    CREATE INDEX ix_learning_sets_family_id ON learning_sets(family_id);
    CREATE INDEX ix_learning_sets_status ON learning_sets(status);
    CREATE INDEX ix_learning_sets_available_at ON learning_sets(available_at);
    CREATE INDEX ix_learning_sets_created_at ON learning_sets(created_at);
    CREATE TABLE card_progress (
      id varchar(36) PRIMARY KEY, set_id varchar(36) NOT NULL REFERENCES learning_sets(id) ON DELETE CASCADE,
      user_id varchar(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE, revision integer NOT NULL,
      states json NOT NULL, "order" json NOT NULL, current_id varchar(40), mode varchar(16) NOT NULL,
      shuffled boolean NOT NULL, updated_at timestamptz NOT NULL, UNIQUE(set_id,user_id));
    CREATE INDEX ix_card_progress_set_id ON card_progress(set_id);
    CREATE INDEX ix_card_progress_user_id ON card_progress(user_id);
    CREATE TABLE quiz_attempts (
      id varchar(36) PRIMARY KEY, set_id varchar(36) NOT NULL REFERENCES learning_sets(id) ON DELETE CASCADE,
      user_id varchar(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE, request_key varchar(36) NOT NULL,
      previous_id varchar(36) REFERENCES quiz_attempts(id) ON DELETE SET NULL, mode varchar(16) NOT NULL,
      status varchar(20) NOT NULL, question_ids json NOT NULL, answers json NOT NULL, revision integer NOT NULL,
      created_at timestamptz NOT NULL, completed_at timestamptz, UNIQUE(user_id,request_key));
    CREATE INDEX ix_quiz_attempts_set_id ON quiz_attempts(set_id);
    CREATE INDEX ix_quiz_attempts_user_id ON quiz_attempts(user_id);
    """)


def downgrade():
    op.execute(
        "DROP TABLE quiz_attempts; DROP TABLE card_progress; DROP TABLE learning_sets; ALTER TABLE messages DROP COLUMN learning_context"
    )
