"""Store application answers encrypted with verification and expiry metadata."""
from alembic import op
import sqlalchemy as sa

revision = "0003_application_answers"
down_revision = "0002_resume_versions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "application_answers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("field_key", sa.String(length=100), nullable=False),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        sa.Column("verification_status", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sensitive", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("field_key"),
    )


def downgrade():
    op.drop_table("application_answers")
