"""GPU selection and durable approval for long debug sessions."""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("workloads", sa.Column("requested_gpu_indices_json", sa.JSON(), nullable=True))
    op.add_column("workloads", sa.Column("approval_status", sa.String(20), nullable=False, server_default="NOT_REQUIRED"))
    op.add_column("workloads", sa.Column("approval_reason", sa.Text(), nullable=False, server_default=""))
    op.add_column("workloads", sa.Column("approval_note", sa.Text(), nullable=False, server_default=""))
    op.add_column("workloads", sa.Column("approved_by", sa.String(36), nullable=True))
    op.create_foreign_key("fk_workloads_approved_by", "workloads", "users", ["approved_by"], ["id"], ondelete="SET NULL")
    op.add_column("workloads", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE users SET max_debug_hours = 10")


def downgrade():
    op.drop_constraint("fk_workloads_approved_by", "workloads", type_="foreignkey")
    for column in ("approved_at", "approved_by", "approval_note", "approval_reason", "approval_status", "requested_gpu_indices_json"):
        op.drop_column("workloads", column)
