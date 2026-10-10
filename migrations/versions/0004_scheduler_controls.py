"""Persist scheduler enablement, schedule, and worker heartbeat."""
from alembic import op
import sqlalchemy as sa

revision = "0004_scheduler_controls"
down_revision = "0003_application_answers"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "scheduler_control",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("hour", sa.Integer(), nullable=False),
        sa.Column("minute", sa.Integer(), nullable=False),
        sa.Column("daily_application_limit", sa.Integer(), nullable=False),
        sa.Column("worker_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("scheduler_control")
