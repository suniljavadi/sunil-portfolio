"""Persist job-specific generated resume versions."""
from alembic import op
import sqlalchemy as sa

revision = "0002_resume_versions"
down_revision = "0001_job_agent_core"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "resume_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.String(length=36), nullable=False),
        sa.Column("source_resume_id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column(
            "content_type",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column("file_path", sa.String(length=1000), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=False),
        sa.Column("selected_skills", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"]),
        sa.ForeignKeyConstraint(["source_resume_id"], ["resumes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id"),
    )


def downgrade():
    op.drop_table("resume_versions")
