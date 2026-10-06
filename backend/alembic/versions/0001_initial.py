"""Initial schema. Freeze this revision; future changes use new revisions."""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    stamp = lambda name: sa.Column(name, sa.DateTime(timezone=True), nullable=True)
    op.create_table(
        "environment_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("image", sa.String(300), nullable=False),
        sa.Column("image_version", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        stamp("created_at"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(32), nullable=False, unique=True),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("uid_hint", sa.Integer, nullable=False, unique=True),
        sa.Column(
            "default_environment_id",
            sa.String(36),
            sa.ForeignKey("environment_templates.id"),
            nullable=False,
        ),
        sa.Column("max_gpus", sa.Integer, nullable=False),
        sa.Column("max_debug_hours", sa.Integer, nullable=False),
        stamp("created_at"),
        stamp("updated_at"),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        stamp("expires_at"),
    )
    op.create_table(
        "environment_variables",
        sa.Column("scope", sa.String(36), primary_key=True),
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("is_secret", sa.Boolean, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
    )
    op.create_table(
        "workspaces",
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True
        ),
        sa.Column("container_id", sa.String(64)),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("route_path", sa.String(100), nullable=False),
        stamp("last_started_at"),
        stamp("last_stopped_at"),
    )
    op.create_table(
        "workloads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("requested_gpus", sa.Integer, nullable=False),
        sa.Column("assigned_gpus_json", sa.JSON, nullable=False),
        sa.Column("requested_cpus", sa.Integer, nullable=False),
        sa.Column("requested_ram_mb", sa.Integer, nullable=False),
        sa.Column("time_limit_seconds", sa.Integer, nullable=False),
        sa.Column(
            "environment_id",
            sa.String(36),
            sa.ForeignKey("environment_templates.id"),
            nullable=False,
        ),
        sa.Column("command", sa.Text, nullable=False),
        sa.Column("workdir", sa.String(500), nullable=False),
        sa.Column("env_json", sa.JSON, nullable=False),
        sa.Column("output_name", sa.String(100), nullable=False),
        sa.Column("route_path", sa.String(100)),
        stamp("created_at"),
        stamp("started_at"),
        stamp("expires_at"),
        stamp("finished_at"),
        sa.Column("exit_code", sa.Integer),
        sa.Column("container_id", sa.String(64)),
        sa.Column("log_path", sa.String(300)),
        sa.Column("error_message", sa.Text),
        sa.Column("cancel_requested", sa.Boolean, nullable=False),
    )
    op.create_index("ix_workloads_user_id", "workloads", ["user_id"])
    op.create_index("ix_workloads_status", "workloads", ["status"])
    op.create_table(
        "gpu_slots",
        sa.Column("gpu_index", sa.Integer, primary_key=True),
        sa.Column("state", sa.String(10), nullable=False),
        sa.Column("owner_type", sa.String(10)),
        sa.Column("owner_id", sa.String(36)),
        stamp("updated_at"),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(50), nullable=False),
        sa.Column("target_id", sa.String(100), nullable=False),
        sa.Column("metadata_json", sa.JSON, nullable=False),
        stamp("created_at"),
    )


def downgrade():
    for name in [
        "audit_events",
        "gpu_slots",
        "workloads",
        "workspaces",
        "environment_variables",
        "auth_sessions",
        "users",
        "environment_templates",
    ]:
        op.drop_table(name)
