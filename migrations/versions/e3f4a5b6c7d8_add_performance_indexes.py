"""add performance indexes for N+1 and query optimization

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-08-30
"""

from alembic import op
import sqlalchemy as sa


revision = "e3f4a5b6c7d8"
down_revision = "d2e3f4a5b6c7"
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
    # Assessment: QuizAttempt, Answer, Question
    # ═══════════════════════════════════════════════════════════════════
    _create_index_if_not_exists("ix_questions_quiz_id", "questions", ["quiz_id"])
    _create_index_if_not_exists("ix_quiz_attempts_quiz_id", "quiz_attempts", ["quiz_id"])
    _create_index_if_not_exists("ix_quiz_attempts_student_id", "quiz_attempts", ["student_id"])
    _create_index_if_not_exists("ix_answers_attempt_id", "answers", ["attempt_id"])
    _create_index_if_not_exists("ix_answers_question_id", "answers", ["question_id"])

    # Composite: quiz results by score
    _create_index_if_not_exists(
        "ix_quiz_attempts_quiz_score", "quiz_attempts",
        [sa.text("quiz_id"), sa.text("score DESC")],
    )

    # ═══════════════════════════════════════════════════════════════════
    # Attendance: class + student + date
    # ═══════════════════════════════════════════════════════════════════
    _create_index_if_not_exists("ix_attendance_class_id", "attendance", ["class_id"])
    _create_index_if_not_exists("ix_attendance_student_id", "attendance", ["student_id"])
    _create_index_if_not_exists("ix_attendance_date", "attendance", ["date"])
    _create_index_if_not_exists("ix_attendance_class_date", "attendance", ["class_id", "date"])

    # ═══════════════════════════════════════════════════════════════════
    # ClassRoom: school + subject + grade + teacher
    # ═══════════════════════════════════════════════════════════════════
    _create_index_if_not_exists("ix_classes_school_id", "classes", ["school_id"])
    _create_index_if_not_exists("ix_classes_subject_id", "classes", ["subject_id"])
    _create_index_if_not_exists("ix_classes_grade_id", "classes", ["grade_id"])
    _create_index_if_not_exists("ix_classes_teacher_id", "classes", ["teacher_id"])
    _create_index_if_not_exists("ix_classes_school_active", "classes", ["school_id", "is_active"])

    _create_index_if_not_exists("ix_class_members_class_id", "class_members", ["class_id"])
    _create_index_if_not_exists("ix_class_members_user_id", "class_members", ["user_id"])

    # ═══════════════════════════════════════════════════════════════════
    # Content: Unit, Lesson, LessonAttachment
    # ═══════════════════════════════════════════════════════════════════
    _create_index_if_not_exists("ix_units_class_id", "units", ["class_id"])
    _create_index_if_not_exists("ix_lessons_unit_id", "lessons", ["unit_id"])
    _create_index_if_not_exists("ix_lesson_attachments_lesson_id", "lesson_attachments", ["lesson_id"])

    # ═══════════════════════════════════════════════════════════════════
    # Gradebook: GradeCategory, GradeItem, GradeEntry
    # ═══════════════════════════════════════════════════════════════════
    _create_index_if_not_exists("ix_grade_categories_class_id", "grade_categories", ["class_id"])
    _create_index_if_not_exists("ix_grade_items_category_id", "grade_items", ["category_id"])
    _create_index_if_not_exists("ix_grade_entries_grade_item_id", "grade_entries", ["grade_item_id"])
    _create_index_if_not_exists("ix_grade_entries_student_item", "grade_entries", ["student_id", "grade_item_id"])

    _create_index_if_not_exists("ix_rubric_templates_teacher_id", "rubric_templates", ["teacher_id"])
    _create_index_if_not_exists("ix_rubric_templates_school_id", "rubric_templates", ["school_id"])
    _create_index_if_not_exists("ix_rubric_criteria_template_id", "rubric_criteria", ["template_id"])
    _create_index_if_not_exists("ix_rubric_grades_submission_id", "rubric_grades", ["submission_id"])
    _create_index_if_not_exists("ix_rubric_grades_criterion_id", "rubric_grades", ["criterion_id"])

    _create_index_if_not_exists("ix_grade_appeals_submission_id", "grade_appeals", ["submission_id"])
    _create_index_if_not_exists("ix_grade_appeals_student_id", "grade_appeals", ["student_id"])

    # ═══════════════════════════════════════════════════════════════════
    # Billing: Subscription, ManualPayment, PaymentReceipt
    # ═══════════════════════════════════════════════════════════════════
    _create_index_if_not_exists("ix_subscription_plans_school_id", "subscription_plans", ["school_id"])
    _create_index_if_not_exists("ix_subscription_plans_class_id", "subscription_plans", ["class_id"])
    _create_index_if_not_exists("ix_subscriptions_plan_id", "subscriptions", ["plan_id"])
    _create_index_if_not_exists("ix_subscriptions_class_id", "subscriptions", ["class_id"])
    _create_index_if_not_exists("ix_manual_payments_subscription_id", "manual_payments", ["subscription_id"])
    _create_index_if_not_exists("ix_manual_payments_reviewed_by", "manual_payments", ["reviewed_by"])
    _create_index_if_not_exists("ix_payment_receipts_manual_payment_id", "payment_receipts", ["manual_payment_id"])
    _create_index_if_not_exists("ix_subscriptions_class_status", "subscriptions", ["class_id", "status"])

    # ═══════════════════════════════════════════════════════════════════
    # Progress: VideoProgress
    # ═══════════════════════════════════════════════════════════════════
    _create_index_if_not_exists("ix_video_progress_lesson_id", "video_progress", ["lesson_id"])
    _create_index_if_not_exists("ix_video_progress_class_id", "video_progress", ["class_id"])

    # ═══════════════════════════════════════════════════════════════════
    # Tutoring: TutorReview, TutorCommission
    # ═══════════════════════════════════════════════════════════════════
    _create_index_if_not_exists("ix_tutor_reviews_session_id", "tutor_reviews", ["session_id"])
    _create_index_if_not_exists("ix_tutor_reviews_student_id", "tutor_reviews", ["student_id"])
    _create_index_if_not_exists("ix_tutor_commissions_session_id", "tutor_commissions", ["session_id"])

    # ═══════════════════════════════════════════════════════════════════
    # AI: AiSession, AiMessage, AiUsageLog
    # ═══════════════════════════════════════════════════════════════════
    _create_index_if_not_exists("ix_ai_sessions_user_id", "ai_sessions", ["user_id"])
    _create_index_if_not_exists("ix_ai_sessions_class_id", "ai_sessions", ["class_id"])
    _create_index_if_not_exists("ix_ai_messages_session_id", "ai_messages", ["session_id"])
    _create_index_if_not_exists("ix_ai_usage_logs_user_id", "ai_usage_logs", ["user_id"])

    # ═══════════════════════════════════════════════════════════════════
    # Communication: Announcement, NotificationPreference
    # ═══════════════════════════════════════════════════════════════════
    _create_index_if_not_exists("ix_announcements_class_id", "announcements", ["class_id"])
    _create_index_if_not_exists("ix_announcements_author_id", "announcements", ["author_id"])
    _create_index_if_not_exists("ix_notification_preferences_user_id", "notification_preferences", ["user_id"])

    # ═══════════════════════════════════════════════════════════════════
    # Family: FamilyLinkCode
    # ═══════════════════════════════════════════════════════════════════
    _create_index_if_not_exists("ix_family_link_codes_used_by", "family_link_codes", ["used_by"])

    # ═══════════════════════════════════════════════════════════════════
    # Gamification: StudentBadge
    # ═══════════════════════════════════════════════════════════════════
    _create_index_if_not_exists("ix_student_badges_badge_id", "student_badges", ["badge_id"])

    # ═══════════════════════════════════════════════════════════════════
    # Audit: composite indexes for filtering
    # ═══════════════════════════════════════════════════════════════════
    _create_index_if_not_exists("ix_audit_logs_action", "audit_logs", ["action"])
    _create_index_if_not_exists("ix_audit_logs_entity", "audit_logs", ["entity"])
    _create_index_if_not_exists("ix_audit_logs_entity_id", "audit_logs", ["entity", "entity_id"])

    # ═══════════════════════════════════════════════════════════════════
    # Question Bank: composite for filtering
    # ═══════════════════════════════════════════════════════════════════
    _create_index_if_not_exists("ix_question_bank_subject_id", "question_bank", ["subject_id"])
    _create_index_if_not_exists("ix_question_bank_teacher_school", "question_bank", ["teacher_id", "school_id"])

    # ═══════════════════════════════════════════════════════════════════
    # Offline: OfflineDownload
    # ═══════════════════════════════════════════════════════════════════
    _create_index_if_not_exists("ix_offline_downloads_attachment_id", "offline_downloads", ["attachment_id"])
    _create_index_if_not_exists("ix_offline_downloads_lesson_id", "offline_downloads", ["lesson_id"])


def downgrade() -> None:
    indexes = [
        ("questions", "ix_questions_quiz_id"),
        ("quiz_attempts", "ix_quiz_attempts_quiz_id"),
        ("quiz_attempts", "ix_quiz_attempts_student_id"),
        ("quiz_attempts", "ix_quiz_attempts_quiz_score"),
        ("answers", "ix_answers_attempt_id"),
        ("answers", "ix_answers_question_id"),
        ("attendance", "ix_attendance_class_id"),
        ("attendance", "ix_attendance_student_id"),
        ("attendance", "ix_attendance_date"),
        ("attendance", "ix_attendance_class_date"),
        ("classes", "ix_classes_school_id"),
        ("classes", "ix_classes_subject_id"),
        ("classes", "ix_classes_grade_id"),
        ("classes", "ix_classes_teacher_id"),
        ("classes", "ix_classes_school_active"),
        ("class_members", "ix_class_members_class_id"),
        ("class_members", "ix_class_members_user_id"),
        ("units", "ix_units_class_id"),
        ("lessons", "ix_lessons_unit_id"),
        ("lesson_attachments", "ix_lesson_attachments_lesson_id"),
        ("grade_categories", "ix_grade_categories_class_id"),
        ("grade_items", "ix_grade_items_category_id"),
        ("grade_entries", "ix_grade_entries_grade_item_id"),
        ("grade_entries", "ix_grade_entries_student_item"),
        ("rubric_templates", "ix_rubric_templates_teacher_id"),
        ("rubric_templates", "ix_rubric_templates_school_id"),
        ("rubric_criteria", "ix_rubric_criteria_template_id"),
        ("rubric_grades", "ix_rubric_grades_submission_id"),
        ("rubric_grades", "ix_rubric_grades_criterion_id"),
        ("grade_appeals", "ix_grade_appeals_submission_id"),
        ("grade_appeals", "ix_grade_appeals_student_id"),
        ("subscription_plans", "ix_subscription_plans_school_id"),
        ("subscription_plans", "ix_subscription_plans_class_id"),
        ("subscriptions", "ix_subscriptions_plan_id"),
        ("subscriptions", "ix_subscriptions_class_id"),
        ("subscriptions", "ix_subscriptions_class_status"),
        ("manual_payments", "ix_manual_payments_subscription_id"),
        ("manual_payments", "ix_manual_payments_reviewed_by"),
        ("payment_receipts", "ix_payment_receipts_manual_payment_id"),
        ("video_progress", "ix_video_progress_lesson_id"),
        ("video_progress", "ix_video_progress_class_id"),
        ("tutor_reviews", "ix_tutor_reviews_session_id"),
        ("tutor_reviews", "ix_tutor_reviews_student_id"),
        ("tutor_commissions", "ix_tutor_commissions_session_id"),
        ("ai_sessions", "ix_ai_sessions_user_id"),
        ("ai_sessions", "ix_ai_sessions_class_id"),
        ("ai_messages", "ix_ai_messages_session_id"),
        ("ai_usage_logs", "ix_ai_usage_logs_user_id"),
        ("announcements", "ix_announcements_class_id"),
        ("announcements", "ix_announcements_author_id"),
        ("notification_preferences", "ix_notification_preferences_user_id"),
        ("family_link_codes", "ix_family_link_codes_used_by"),
        ("student_badges", "ix_student_badges_badge_id"),
        ("audit_logs", "ix_audit_logs_action"),
        ("audit_logs", "ix_audit_logs_entity"),
        ("audit_logs", "ix_audit_logs_entity_id"),
        ("question_bank", "ix_question_bank_subject_id"),
        ("question_bank", "ix_question_bank_teacher_school"),
        ("offline_downloads", "ix_offline_downloads_attachment_id"),
        ("offline_downloads", "ix_offline_downloads_lesson_id"),
    ]
    for table, index_name in indexes:
        op.drop_index(index_name, table_name=table)
