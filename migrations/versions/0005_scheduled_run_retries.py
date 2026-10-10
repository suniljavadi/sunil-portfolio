"""Link retry runs to the discovery run they recover."""
from alembic import op
import sqlalchemy as sa

revision = "0005_scheduled_run_retries"
down_revision = "0004_scheduler_controls"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("scheduled_runs") as batch_op:
        batch_op.add_column(sa.Column("retry_of_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_scheduled_runs_retry_of_id",
            "scheduled_runs",
            ["retry_of_id"],
            ["id"],
        )


def downgrade():
    with op.batch_alter_table("scheduled_runs") as batch_op:
        batch_op.drop_constraint("fk_scheduled_runs_retry_of_id", type_="foreignkey")
        batch_op.drop_column("retry_of_id")
