"""Announcements, read receipts and eight-hour member debug limits."""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("announcements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_announcements_published_at", "announcements", ["published_at"])
    op.create_table("announcement_reads",
        sa.Column("announcement_id", sa.String(36), sa.ForeignKey("announcements.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False))
    op.execute("UPDATE users SET max_debug_hours = 8 WHERE max_debug_hours > 8")


def downgrade():
    op.drop_table("announcement_reads")
    op.drop_index("ix_announcements_published_at", table_name="announcements")
    op.drop_table("announcements")
