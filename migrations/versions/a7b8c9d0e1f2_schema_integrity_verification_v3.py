"""schema integrity verification — CHECK constraints + new indexes

Revision ID: a7b8c9d0e1f2
Revises: f4a5b6c7d8e9
Create Date: 2026-08-30
"""

import sqlalchemy as sa
from alembic import op

revision = "a7b8c9d0e1f2"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None


def _create_index_if_not_exists(index_name: str, table: str, columns: list, **kwargs) -> None:
    """Create an index only if it doesn't already exist."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = [idx["name"] for idx in inspector.get_indexes(table)]
    if index_name not in existing:
        op.create_index(index_name, table, columns, **kwargs)


def _add_check_if_not_exists(constraint_name: str, table: str, condition: str) -> None:
    """Add a CHECK constraint only if it doesn't already exist."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = [c["name"] for c in inspector.get_check_constraints(table)]
    if constraint_name not in existing:
        op.create_check_constraint(constraint_name, table, condition)


def upgrade() -> None:
    # ═══════════════════════════════════════════════════════════════════
    # 1. CHECK CONSTRAINTS — enforce valid status/enumeration values
    # ═══════════════════════════════════════════════════════════════════

    # Subscriptions
    _add_check_if_not_exists(
        "ck_subscription_status",
        "subscriptions",
        "status IN ('pending', 'active', 'expired', 'cancelled', 'pending_review')",
    )

    # ManualPayment
    _add_check_if_not_exists(
        "ck_manual_payment_status",
        "manual_payments",
        "status IN ('pending', 'approved', 'rejected')",
    )

    # TutoringSession
    _add_check_if_not_exists(
        "ck_tutoring_session_status",
        "tutoring_sessions",
        "status IN ('requested', 'active', 'completed', 'cancelled', 'no_show')",
    )
    _add_check_if_not_exists(
        "ck_tutoring_session_payment_status",
        "tutoring_sessions",
        "payment_status IN ('pending', 'paid', 'refunded', 'cancelled')",
    )
    _add_check_if_not_exists(
        "ck_tutoring_session_video_provider",
        "tutoring_sessions",
        "video_provider IN ('jitsi', 'zoom')",
    )

    # TutorCommission
    _add_check_if_not_exists(
        "ck_tutor_commission_status",
        "tutor_commissions",
        "status IN ('pending', 'withdrawn')",
    )

    # TutorPayout
    _add_check_if_not_exists(
        "ck_tutor_payout_status",
        "tutor_payouts",
        "status IN ('pending', 'approved', 'rejected')",
    )

    # TutorProfile
    _add_check_if_not_exists(
        "ck_tutor_profile_mode",
        "tutor_profiles",
        "mode IN ('online', 'offline', 'both')",
    )
    _add_check_if_not_exists(
        "ck_tutor_profile_video_provider",
        "tutor_profiles",
        "video_provider IN ('jitsi', 'zoom')",
    )

    # TutoringRequest
    _add_check_if_not_exists(
        "ck_tutoring_request_status",
        "tutoring_requests",
        "status IN ('pending', 'accepted', 'rejected', 'cancelled')",
    )
    _add_check_if_not_exists(
        "ck_tutoring_request_mode",
        "tutoring_requests",
        "mode IN ('online', 'offline')",
    )

    # Attendance
    _add_check_if_not_exists(
        "ck_attendance_status",
        "attendance",
        "status IN ('present', 'absent', 'late', 'excused')",
    )

    # StudentProgress
    _add_check_if_not_exists(
        "ck_student_progress_status",
        "student_progress",
        "status IN ('not_started', 'in_progress', 'completed')",
    )
    _add_check_if_not_exists(
        "ck_student_progress_pct_range",
        "student_progress",
        "progress_pct >= 0 AND progress_pct <= 100",
    )

    # Lessons
    _add_check_if_not_exists(
        "ck_lesson_status",
        "lessons",
        "status IN ('draft', 'published', 'archived')",
    )

    # LessonAttachment
    _add_check_if_not_exists(
        "ck_lesson_attachment_kind",
        "lesson_attachments",
        "kind IN ('video', 'pdf', 'image', 'graph', 'audio')",
    )

    # ClassMember
    _add_check_if_not_exists(
        "ck_class_member_status",
        "class_members",
        "status IN ('active', 'removed', 'pending')",
    )

    # GradeEntry — mark range
    _add_check_if_not_exists(
        "ck_grade_entry_mark_range",
        "grade_entries",
        "mark >= 0 AND mark <= 100",
    )

    # RubricGrade — score range
    _add_check_if_not_exists(
        "ck_rubric_grade_score_range",
        "rubric_grades",
        "score >= 0 AND score <= 100",
    )

    # ═══════════════════════════════════════════════════════════════════
    # 2. NEW COMPOSITE INDEXES (not in e3f4a5b6c7d8 or f4a5b6c7d8e9)
    # ═══════════════════════════════════════════════════════════════════

    # Attendance: composite lookups not covered by e3f4a5b6c7d8
    _create_index_if_not_exists("ix_attendance_class_student", "attendance", ["class_id", "student_id"])
    _create_index_if_not_exists("ix_attendance_student_date", "attendance", ["student_id", "date"])

    # VideoProgress: composite lookups
    _create_index_if_not_exists("ix_video_progress_student_lesson", "video_progress", ["student_id", "lesson_id"])
    _create_index_if_not_exists("ix_video_progress_class_student", "video_progress", ["class_id", "student_id"])

    # Submissions: FK indexes (not covered by e3f4a5b6c7d8)
    _create_index_if_not_exists("ix_submissions_assignment", "submissions", ["assignment_id"])
    _create_index_if_not_exists("ix_submissions_student", "submissions", ["student_id"])

    # Assignments: FK index
    _create_index_if_not_exists("ix_assignments_class", "assignments", ["class_id"])

    # FK integrity: reviewed_by / recorded_by / created_by columns
    _create_index_if_not_exists("ix_tutor_payouts_reviewed_by", "tutor_payouts", ["reviewed_by"])
    _create_index_if_not_exists("ix_attendance_recorded_by", "attendance", ["recorded_by"])
    _create_index_if_not_exists("ix_lessons_created_by", "lessons", ["created_by"])


def downgrade() -> None:
    # Drop CHECK constraints
    check_constraints = [
        ("subscriptions", "ck_subscription_status"),
        ("manual_payments", "ck_manual_payment_status"),
        ("tutoring_sessions", "ck_tutoring_session_status"),
        ("tutoring_sessions", "ck_tutoring_session_payment_status"),
        ("tutoring_sessions", "ck_tutoring_session_video_provider"),
        ("tutor_commissions", "ck_tutor_commission_status"),
        ("tutor_payouts", "ck_tutor_payout_status"),
        ("tutor_profiles", "ck_tutor_profile_mode"),
        ("tutor_profiles", "ck_tutor_profile_video_provider"),
        ("tutoring_requests", "ck_tutoring_request_status"),
        ("tutoring_requests", "ck_tutoring_request_mode"),
        ("attendance", "ck_attendance_status"),
        ("student_progress", "ck_student_progress_status"),
        ("student_progress", "ck_student_progress_pct_range"),
        ("lessons", "ck_lesson_status"),
        ("lesson_attachments", "ck_lesson_attachment_kind"),
        ("class_members", "ck_class_member_status"),
        ("grade_entries", "ck_grade_entry_mark_range"),
        ("rubric_grades", "ck_rubric_grade_score_range"),
    ]
    for table, name in check_constraints:
        op.drop_constraint(name, table_name=table, type_="check")

    # Drop indexes (only those created in THIS migration)
    indexes = [
        ("attendance", "ix_attendance_class_student"),
        ("attendance", "ix_attendance_student_date"),
        ("video_progress", "ix_video_progress_student_lesson"),
        ("video_progress", "ix_video_progress_class_student"),
        ("submissions", "ix_submissions_assignment"),
        ("submissions", "ix_submissions_student"),
        ("assignments", "ix_assignments_class"),
        ("tutor_payouts", "ix_tutor_payouts_reviewed_by"),
        ("attendance", "ix_attendance_recorded_by"),
        ("lessons", "ix_lessons_created_by"),
    ]
    for table, index_name in indexes:
        op.drop_index(index_name, table_name=table)
