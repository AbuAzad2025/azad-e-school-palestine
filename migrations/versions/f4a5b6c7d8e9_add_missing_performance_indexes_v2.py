"""add missing performance indexes v2 — N+1 remediation & query optimization

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-08-30
"""

import sqlalchemy as sa
from alembic import op

revision = "f4a5b6c7d8e9"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None


def _create_index_if_not_exists(index_name: str, table: str, columns: list, **kwargs) -> None:
    """Create an index only if it doesn't already exist."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = [idx["name"] for idx in inspector.get_indexes(table)]
    if index_name not in existing:
        op.create_index(index_name, table, columns, **kwargs)


def upgrade() -> None:
    # ═══════════════════════════════════════════════════════════════════
    # UserRoleLinks: school lookups — filtered in 5+ queries
    # ═══════════════════════════════════════════════════════════════════
    _create_index_if_not_exists("ix_user_role_links_school_id", "user_role_links", ["school_id"])
    _create_index_if_not_exists("ix_user_role_links_school_role", "user_role_links", ["school_id", "role"])

    # ═══════════════════════════════════════════════════════════════════
    # Subscriptions: user_id + status composite (active subscription check)
    # ═══════════════════════════════════════════════════════════════════
    _create_index_if_not_exists("ix_subscriptions_user_status", "subscriptions", ["user_id", "status"])
    _create_index_if_not_exists("ix_subscriptions_status", "subscriptions", ["status"])

    # ═══════════════════════════════════════════════════════════════════
    # DiscountCodes: school-scoped lookups
    # ═══════════════════════════════════════════════════════════════════
    _create_index_if_not_exists("ix_discount_codes_school_id", "discount_codes", ["school_id"])

    # ═══════════════════════════════════════════════════════════════════
    # Messages: unread count + thread queries
    # ═══════════════════════════════════════════════════════════════════
    _create_index_if_not_exists("ix_messages_is_read", "messages", ["is_read"])
    _create_index_if_not_exists("ix_messages_parent_message_id", "messages", ["parent_message_id"])
    _create_index_if_not_exists("ix_messages_recipient_read", "messages", ["recipient_id", "is_read"])

    # ═══════════════════════════════════════════════════════════════════
    # ClassMembers: active member count per class
    # ═══════════════════════════════════════════════════════════════════
    _create_index_if_not_exists("ix_class_members_class_status", "class_members", ["class_id", "status"])
    _create_index_if_not_exists("ix_class_members_user_status", "class_members", ["user_id", "status"])

    # ═══════════════════════════════════════════════════════════════════
    # Lessons: class + status (published lessons query)
    # ═══════════════════════════════════════════════════════════════════
    _create_index_if_not_exists("ix_lessons_class_status", "lessons", ["class_id", "status"])

    # ═══════════════════════════════════════════════════════════════════
    # StudentProgress: class + student composite (progress overview batch)
    # ═══════════════════════════════════════════════════════════════════
    _create_index_if_not_exists("ix_student_progress_class_student", "student_progress", ["class_id", "student_id"])
    _create_index_if_not_exists("ix_student_progress_class_status", "student_progress", ["class_id", "status"])

    # ═══════════════════════════════════════════════════════════════════
    # Tutoring: tutor_id + status (common filter)
    # ═══════════════════════════════════════════════════════════════════
    _create_index_if_not_exists("ix_tutoring_sessions_tutor_status", "tutoring_sessions", ["tutor_id", "status"])
    _create_index_if_not_exists("ix_tutoring_sessions_student_status", "tutoring_sessions", ["student_id", "status"])
    _create_index_if_not_exists("ix_tutor_commissions_tutor_status", "tutor_commissions", ["tutor_id", "status"])
    _create_index_if_not_exists("ix_tutor_payouts_tutor_status", "tutor_payouts", ["tutor_id", "status"])


def downgrade() -> None:
    indexes = [
        ("user_role_links", "ix_user_role_links_school_id"),
        ("user_role_links", "ix_user_role_links_school_role"),
        ("subscriptions", "ix_subscriptions_user_status"),
        ("subscriptions", "ix_subscriptions_status"),
        ("discount_codes", "ix_discount_codes_school_id"),
        ("messages", "ix_messages_is_read"),
        ("messages", "ix_messages_parent_message_id"),
        ("messages", "ix_messages_recipient_read"),
        ("class_members", "ix_class_members_class_status"),
        ("class_members", "ix_class_members_user_status"),
        ("lessons", "ix_lessons_class_status"),
        ("student_progress", "ix_student_progress_class_student"),
        ("student_progress", "ix_student_progress_class_status"),
        ("tutoring_sessions", "ix_tutoring_sessions_tutor_status"),
        ("tutoring_sessions", "ix_tutoring_sessions_student_status"),
        ("tutor_commissions", "ix_tutor_commissions_tutor_status"),
        ("tutor_payouts", "ix_tutor_payouts_tutor_status"),
    ]
    for table, index_name in indexes:
        op.drop_index(index_name, table_name=table)
