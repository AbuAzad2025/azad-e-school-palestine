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


def upgrade() -> None:
    # ═══════════════════════════════════════════════════════════════════
    # Assessment: QuizAttempt, Answer, Question
    # ═══════════════════════════════════════════════════════════════════
    op.create_index("ix_questions_quiz_id", "questions", ["quiz_id"])
    op.create_index("ix_quiz_attempts_quiz_id", "quiz_attempts", ["quiz_id"])
    op.create_index("ix_quiz_attempts_student_id", "quiz_attempts", ["student_id"])
    op.create_index("ix_answers_attempt_id", "answers", ["attempt_id"])
    op.create_index("ix_answers_question_id", "answers", ["question_id"])

    # Composite: quiz results by score
    op.create_index(
        "ix_quiz_attempts_quiz_score",
        "quiz_attempts",
        ["quiz_id", sa.text("score DESC")],
    )

    # ═══════════════════════════════════════════════════════════════════
    # Attendance: class + student + date
    # ═══════════════════════════════════════════════════════════════════
    op.create_index("ix_attendance_class_id", "attendance", ["class_id"])
    op.create_index("ix_attendance_student_id", "attendance", ["student_id"])
    op.create_index("ix_attendance_date", "attendance", ["date"])

    # Composite: attendance lookup by class + date
    op.create_index(
        "ix_attendance_class_date",
        "attendance",
        ["class_id", "date"],
    )

    # ═══════════════════════════════════════════════════════════════════
    # ClassRoom: school + subject + grade + teacher
    # ═══════════════════════════════════════════════════════════════════
    op.create_index("ix_classes_school_id", "classes", ["school_id"])
    op.create_index("ix_classes_subject_id", "classes", ["subject_id"])
    op.create_index("ix_classes_grade_id", "classes", ["grade_id"])
    op.create_index("ix_classes_teacher_id", "classes", ["teacher_id"])

    # Composite: classes by school + active
    op.create_index(
        "ix_classes_school_active",
        "classes",
        ["school_id", "is_active"],
    )

    # ClassMember: class + user
    op.create_index("ix_class_members_class_id", "class_members", ["class_id"])
    op.create_index("ix_class_members_user_id", "class_members", ["user_id"])

    # ═══════════════════════════════════════════════════════════════════
    # Content: Unit, Lesson, LessonAttachment
    # ═══════════════════════════════════════════════════════════════════
    op.create_index("ix_units_class_id", "units", ["class_id"])
    op.create_index("ix_lessons_unit_id", "lessons", ["unit_id"])
    op.create_index("ix_lesson_attachments_lesson_id", "lesson_attachments", ["lesson_id"])

    # ═══════════════════════════════════════════════════════════════════
    # Gradebook: GradeCategory, GradeItem, GradeEntry
    # ═══════════════════════════════════════════════════════════════════
    op.create_index("ix_grade_categories_class_id", "grade_categories", ["class_id"])
    op.create_index("ix_grade_items_category_id", "grade_items", ["category_id"])
    op.create_index("ix_grade_entries_grade_item_id", "grade_entries", ["grade_item_id"])

    # Composite: gradebook entries by student across items
    op.create_index(
        "ix_grade_entries_student_item",
        "grade_entries",
        ["student_id", "grade_item_id"],
    )

    # Rubric
    op.create_index("ix_rubric_templates_teacher_id", "rubric_templates", ["teacher_id"])
    op.create_index("ix_rubric_templates_school_id", "rubric_templates", ["school_id"])
    op.create_index("ix_rubric_criteria_template_id", "rubric_criteria", ["template_id"])
    op.create_index("ix_rubric_grades_submission_id", "rubric_grades", ["submission_id"])
    op.create_index("ix_rubric_grades_criterion_id", "rubric_grades", ["criterion_id"])

    # Grade Appeals
    op.create_index("ix_grade_appeals_submission_id", "grade_appeals", ["submission_id"])
    op.create_index("ix_grade_appeals_student_id", "grade_appeals", ["student_id"])

    # ═══════════════════════════════════════════════════════════════════
    # Billing: Subscription, ManualPayment, PaymentReceipt
    # ═══════════════════════════════════════════════════════════════════
    op.create_index("ix_subscription_plans_school_id", "subscription_plans", ["school_id"])
    op.create_index("ix_subscription_plans_class_id", "subscription_plans", ["class_id"])
    op.create_index("ix_subscriptions_plan_id", "subscriptions", ["plan_id"])
    op.create_index("ix_subscriptions_class_id", "subscriptions", ["class_id"])
    op.create_index("ix_manual_payments_subscription_id", "manual_payments", ["subscription_id"])
    op.create_index("ix_manual_payments_reviewed_by", "manual_payments", ["reviewed_by"])
    op.create_index("ix_payment_receipts_manual_payment_id", "payment_receipts", ["manual_payment_id"])

    # Composite: subscriptions by class + status
    op.create_index(
        "ix_subscriptions_class_status",
        "subscriptions",
        ["class_id", "status"],
    )

    # ═══════════════════════════════════════════════════════════════════
    # Progress: StudentProgress, VideoProgress
    # ═══════════════════════════════════════════════════════════════════
    op.create_index("ix_video_progress_lesson_id", "video_progress", ["lesson_id"])
    op.create_index("ix_video_progress_class_id", "video_progress", ["class_id"])

    # ═══════════════════════════════════════════════════════════════════
    # Tutoring: TutorReview, TutorCommission
    # ═══════════════════════════════════════════════════════════════════
    op.create_index("ix_tutor_reviews_session_id", "tutor_reviews", ["session_id"])
    op.create_index("ix_tutor_reviews_student_id", "tutor_reviews", ["student_id"])
    op.create_index("ix_tutor_commissions_session_id", "tutor_commissions", ["session_id"])

    # ═══════════════════════════════════════════════════════════════════
    # AI: AiSession, AiMessage, AiUsageLog
    # ═══════════════════════════════════════════════════════════════════
    op.create_index("ix_ai_sessions_user_id", "ai_sessions", ["user_id"])
    op.create_index("ix_ai_sessions_class_id", "ai_sessions", ["class_id"])
    op.create_index("ix_ai_messages_session_id", "ai_messages", ["session_id"])
    op.create_index("ix_ai_usage_logs_user_id", "ai_usage_logs", ["user_id"])

    # ═══════════════════════════════════════════════════════════════════
    # Communication: Announcement, NotificationPreference
    # ═══════════════════════════════════════════════════════════════════
    op.create_index("ix_announcements_class_id", "announcements", ["class_id"])
    op.create_index("ix_announcements_author_id", "announcements", ["author_id"])
    op.create_index("ix_notification_preferences_user_id", "notification_preferences", ["user_id"])

    # ═══════════════════════════════════════════════════════════════════
    # Family: FamilyLinkCode
    # ═══════════════════════════════════════════════════════════════════
    op.create_index("ix_family_link_codes_used_by", "family_link_codes", ["used_by"])

    # ═══════════════════════════════════════════════════════════════════
    # Gamification: StudentBadge
    # ═══════════════════════════════════════════════════════════════════
    op.create_index("ix_student_badges_badge_id", "student_badges", ["badge_id"])

    # ═══════════════════════════════════════════════════════════════════
    # Audit: composite indexes for filtering
    # ═══════════════════════════════════════════════════════════════════
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_entity", "audit_logs", ["entity"])

    # Composite: audit by entity + entity_id
    op.create_index(
        "ix_audit_logs_entity_id",
        "audit_logs",
        ["entity", "entity_id"],
    )

    # ═══════════════════════════════════════════════════════════════════
    # Question Bank: composite for filtering
    # ═══════════════════════════════════════════════════════════════════
    op.create_index("ix_question_bank_subject_id", "question_bank", ["subject_id"])

    # Composite: question bank by teacher + school
    op.create_index(
        "ix_question_bank_teacher_school",
        "question_bank",
        ["teacher_id", "school_id"],
    )

    # ═══════════════════════════════════════════════════════════════════
    # Offline: OfflineDownload
    # ═══════════════════════════════════════════════════════════════════
    op.create_index("ix_offline_downloads_attachment_id", "offline_downloads", ["attachment_id"])
    op.create_index("ix_offline_downloads_lesson_id", "offline_downloads", ["lesson_id"])


def downgrade() -> None:
    # Drop all indexes created in upgrade
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
