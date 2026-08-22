"""P3: Sync models -> schema — add columns present in models but missing from migrations

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-08-22

Fixes E2E 500 errors: routes/templates reference model columns that
`flask db upgrade` never created (tests masked this via a conftest ALTER).
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f3a4b5c6d7e8"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade():
    # --- subscriptions ---
    op.add_column("subscriptions", sa.Column("auto_activated_at", sa.DateTime(timezone=True), nullable=True))

    # --- classes (paid/public class catalog) ---
    op.add_column("classes", sa.Column("max_students", sa.SmallInteger(), nullable=True))
    op.add_column("classes", sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("classes", sa.Column("price", sa.Numeric(10, 2), nullable=True))
    op.add_column("classes", sa.Column("duration_days", sa.SmallInteger(), nullable=True))

    # --- lessons (sharing / offline) ---
    op.add_column("lessons", sa.Column("is_shared", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("lessons", sa.Column("original_lesson_id", sa.BigInteger(), nullable=True))
    op.add_column("lessons", sa.Column("is_offline_available", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.create_foreign_key("fk_lessons_original_lesson", "lessons", "lessons", ["original_lesson_id"], ["id"])

    # --- schools ---
    op.add_column("schools", sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")))

    # --- subjects (MOE curriculum mapping) ---
    op.add_column("subjects", sa.Column("moe_code", sa.String(50), nullable=True))
    op.add_column("subjects", sa.Column("moe_curriculum_version", sa.String(50), nullable=True))

    # --- manual_payments ---
    op.add_column("manual_payments", sa.Column("gateway", sa.String(20), nullable=True))

    # --- tutor_profiles / tutoring_sessions (Zoom/Jitsi providers) ---
    op.add_column("tutor_profiles", sa.Column("video_provider", sa.String(10), nullable=False, server_default=sa.text("'jitsi'")))
    op.add_column("tutoring_sessions", sa.Column("end_time", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tutoring_sessions", sa.Column("video_provider", sa.String(10), nullable=False, server_default=sa.text("'jitsi'")))
    op.add_column("tutoring_sessions", sa.Column("zoom_meeting_id", sa.String(64), nullable=True))
    op.add_column("tutoring_sessions", sa.Column("zoom_join_url", sa.Text(), nullable=True))
    op.add_column("tutoring_sessions", sa.Column("zoom_start_url", sa.Text(), nullable=True))

    # --- user_role_links (approval flow) ---
    op.add_column("user_role_links", sa.Column("approved_by", sa.BigInteger(), nullable=True))
    op.add_column("user_role_links", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_user_role_links_approved_by", "user_role_links", "users", ["approved_by"], ["id"])

    # --- users ---
    op.add_column("users", sa.Column("is_individual", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade():
    op.drop_column("users", "is_individual")

    op.drop_constraint("fk_user_role_links_approved_by", "user_role_links", type_="foreignkey")
    op.drop_column("user_role_links", "approved_at")
    op.drop_column("user_role_links", "approved_by")

    op.drop_column("tutoring_sessions", "zoom_start_url")
    op.drop_column("tutoring_sessions", "zoom_join_url")
    op.drop_column("tutoring_sessions", "zoom_meeting_id")
    op.drop_column("tutoring_sessions", "video_provider")
    op.drop_column("tutoring_sessions", "end_time")
    op.drop_column("tutor_profiles", "video_provider")

    op.drop_column("manual_payments", "gateway")

    op.drop_column("subjects", "moe_curriculum_version")
    op.drop_column("subjects", "moe_code")

    op.drop_column("schools", "is_system")

    op.drop_constraint("fk_lessons_original_lesson", "lessons", type_="foreignkey")
    op.drop_column("lessons", "is_offline_available")
    op.drop_column("lessons", "original_lesson_id")
    op.drop_column("lessons", "is_shared")

    op.drop_column("classes", "duration_days")
    op.drop_column("classes", "price")
    op.drop_column("classes", "is_public")
    op.drop_column("classes", "max_students")

    op.drop_column("subscriptions", "auto_activated_at")
