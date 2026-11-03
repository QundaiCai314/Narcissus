"""Immutable visual content revisions, jobs and private object cleanup ledger."""
from alembic import op
revision = "008"
down_revision = "007"
branch_labels = depends_on = None

def upgrade():
    op.execute('\nCREATE TABLE visual_artifacts (\n\tid VARCHAR(36) NOT NULL, \n\tnotebook_id VARCHAR(36) NOT NULL, \n\trequest_key VARCHAR(36) NOT NULL, \n\tkind VARCHAR(20) NOT NULL, \n\ttitle VARCHAR(120) NOT NULL, \n\tparams JSON NOT NULL, \n\tinputs JSON NOT NULL, \n\tevidence JSON NOT NULL, \n\tcontent JSON NOT NULL, \n\trevision INTEGER NOT NULL, \n\tstage VARCHAR(24) NOT NULL, \n\tdeleted_at TIMESTAMP WITH TIME ZONE, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (notebook_id, request_key), \n\tFOREIGN KEY(notebook_id) REFERENCES notebooks (id) ON DELETE CASCADE\n)\n\n')
    op.execute('CREATE INDEX ix_visual_artifacts_notebook_id ON visual_artifacts (notebook_id)')
    op.execute('\nCREATE TABLE visual_revisions (\n\tid VARCHAR(36) NOT NULL, \n\tartifact_id VARCHAR(36) NOT NULL, \n\trevision INTEGER NOT NULL, \n\tsnapshot JSON NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (artifact_id, revision), \n\tFOREIGN KEY(artifact_id) REFERENCES visual_artifacts (id) ON DELETE CASCADE\n)\n\n')
    op.execute('CREATE INDEX ix_visual_revisions_artifact_id ON visual_revisions (artifact_id)')
    op.execute('\nCREATE TABLE visual_jobs (\n\tid VARCHAR(36) NOT NULL, \n\tartifact_id VARCHAR(36) NOT NULL, \n\trequest_key VARCHAR(80) NOT NULL, \n\tkind VARCHAR(20) NOT NULL, \n\trevision INTEGER NOT NULL, \n\tsnapshot JSON NOT NULL, \n\tresult JSON NOT NULL, \n\tmodel VARCHAR(200), \n\tphase VARCHAR(24) NOT NULL, \n\tstatus VARCHAR(24) NOT NULL, \n\tattempts INTEGER NOT NULL, \n\tclaim VARCHAR(36), \n\terror TEXT, \n\tavailable_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tstarted_at TIMESTAMP WITH TIME ZONE, \n\tdispatched_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tusage JSON NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (artifact_id, request_key), \n\tFOREIGN KEY(artifact_id) REFERENCES visual_artifacts (id) ON DELETE CASCADE\n)\n\n')
    op.execute('CREATE INDEX ix_visual_jobs_artifact_id ON visual_jobs (artifact_id)')
    op.execute('CREATE INDEX ix_visual_jobs_status ON visual_jobs (status)')
    op.execute('\nCREATE TABLE visual_files (\n\tid VARCHAR(36) NOT NULL, \n\tartifact_id VARCHAR(36) NOT NULL, \n\tnotebook_id VARCHAR(36) NOT NULL, \n\tjob_id VARCHAR(36) NOT NULL, \n\trevision INTEGER NOT NULL, \n\tobject_key VARCHAR(500) NOT NULL, \n\tformat VARCHAR(12) NOT NULL, \n\tordinal INTEGER NOT NULL, \n\tstatus VARCHAR(24) NOT NULL, \n\terror TEXT, \n\tattempts INTEGER NOT NULL, \n\tavailable_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (object_key)\n)\n\n')
    op.execute('CREATE INDEX ix_visual_files_artifact_id ON visual_files (artifact_id)')
    op.execute('CREATE INDEX ix_visual_files_job_id ON visual_files (job_id)')
    op.execute('CREATE INDEX ix_visual_files_notebook_id ON visual_files (notebook_id)')
    op.execute('CREATE INDEX ix_visual_files_status ON visual_files (status)')

def downgrade():
    op.drop_table('visual_files')
    op.drop_table('visual_jobs')
    op.drop_table('visual_revisions')
    op.drop_table('visual_artifacts')
