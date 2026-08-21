"""P1: Soft delete on missing tables + denormalized tenant columns + composite indexes

Revision ID: d1e2f3a4b5c6
Revises: c0f0d1e2a3b4
Create Date: 2026-08-21

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d1e2f3a4b5c6"
down_revision = "c0f0d1e2a3b4"
branch_labels = None
depends_on = None


def upgrade():
    # ============================================================
    # SOFT DELETE on tables missing deleted_at
    # ============================================================

    for tbl in (
        "grades",
        "subjects",
        "subscription_plans",
        "quizzes",
        "assignments",
        "grade_categories",
        "grade_items",
        "rubric_templates",
        "rubric_criteria",
        "units",
        "announcements",
        "attendance",
        "class_members",
        "submissions",
        "quiz_attempts",
        "answers",
        "proctoring_logs",
        "questions",
        "student_progress",
        "video_progress",
        "badges",
        "student_badges",
        "tutor_profiles",
        "tutoring_requests",
        "tutoring_sessions",
        "tutor_reviews",
        "tutor_commissions",
        "tutor_payouts",
        "ai_sessions",
        "ai_messages",
        "ai_usage_logs",
        "messages",
        "notifications",
        "notification_preferences",
        "contact_messages",
        "family_links",
        "family_link_codes",
        "discount_codes",
        "processed_events",
        "reminder_logs",
        "payment_receipts",
        "manual_payments",
        "school_settings",
        "subject_grade_links",
        "user_role_links",
    ):
        op.add_column(tbl, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        op.execute(f'CREATE INDEX IF NOT EXISTS idx_{tbl}_active ON {tbl} (id) WHERE deleted_at IS NULL')

    # ============================================================
    # DENORMALIZED tenant_id columns for query performance
    # ============================================================

    # quiz_attempts.school_id via quizzes -> classes -> schools
    op.add_column("quiz_attempts", sa.Column("school_id", sa.BigInteger(), nullable=True))
    op.execute("""
        UPDATE quiz_attempts qa
        SET school_id = c.school_id
        FROM quizzes q
        JOIN classes c ON q.class_id = c.id
        WHERE qa.quiz_id = q.id
    """)
    op.create_index("idx_quiz_attempts_school_status", "quiz_attempts", ["school_id", "status"])
    op.create_foreign_key("fk_quiz_attempts_school", "quiz_attempts", "schools", ["school_id"], ["id"])

    # submissions.school_id via assignments -> classes -> schools
    op.add_column("submissions", sa.Column("school_id", sa.BigInteger(), nullable=True))
    op.execute("""
        UPDATE submissions s
        SET school_id = c.school_id
        FROM assignments a
        JOIN classes c ON a.class_id = c.id
        WHERE s.assignment_id = a.id
    """)
    op.create_index("idx_submissions_school_submitted", "submissions", ["school_id", sa.text("submitted_at DESC")])
    op.create_foreign_key("fk_submissions_school", "submissions", "schools", ["school_id"], ["id"])

    # grade_entries.school_id via grade_items -> grade_categories -> classes -> schools
    op.add_column("grade_entries", sa.Column("school_id", sa.BigInteger(), nullable=True))
    op.execute("""
        UPDATE grade_entries ge
        SET school_id = c.school_id
        FROM grade_items gi
        JOIN grade_categories gc ON gi.category_id = gc.id
        JOIN classes c ON gc.class_id = c.id
        WHERE ge.grade_item_id = gi.id
    """)
    op.create_index("idx_grade_entries_school", "grade_entries", ["school_id", "student_id"])
    op.create_foreign_key("fk_grade_entries_school", "grade_entries", "schools", ["school_id"], ["id"])

    # notifications.school_id via user -> user_role_links -> school
    op.add_column("notifications", sa.Column("school_id", sa.BigInteger(), nullable=True))
    op.execute("""
        UPDATE notifications n
        SET school_id = (
            SELECT url.school_id
            FROM user_role_links url
            WHERE url.user_id = n.user_id AND url.is_active
            ORDER BY url.created_at DESC
            LIMIT 1
        )
    """)
    op.create_index("idx_notifications_school_read", "notifications", ["school_id", "user_id", "is_read"])
    op.create_foreign_key("fk_notifications_school", "notifications", "schools", ["school_id"], ["id"])

    # student_progress.school_id (already has class_id, add school_id via class)
    op.add_column("student_progress", sa.Column("school_id", sa.BigInteger(), nullable=True))
    op.execute("""
        UPDATE student_progress sp
        SET school_id = c.school_id
        FROM classes c
        WHERE sp.class_id = c.id
    """)
    op.create_index("idx_student_progress_school_lesson", "student_progress", ["school_id", "lesson_id", "student_id"])
    op.create_foreign_key("fk_student_progress_school", "student_progress", "schools", ["school_id"], ["id"])

    # video_progress.school_id
    op.add_column("video_progress", sa.Column("school_id", sa.BigInteger(), nullable=True))
    op.execute("""
        UPDATE video_progress vp
        SET school_id = c.school_id
        FROM classes c
        WHERE vp.class_id = c.id
    """)
    op.create_index("idx_video_progress_school", "video_progress", ["school_id", "lesson_id"])
    op.create_foreign_key("fk_video_progress_school", "video_progress", "schools", ["school_id"], ["id"])

    # ============================================================
    # ADDITIONAL COMPOSITE INDEXES for common query patterns
    # ============================================================

    op.create_index("idx_lessons_class_unit_order", "lessons", ["class_id", "unit_id", "sort_order"])
    op.create_index("idx_assignments_class_due_pub", "assignments", ["class_id", "due_at"], postgresql_where=sa.text("due_at IS NOT NULL"))
    op.create_index("idx_grade_items_cat_due", "grade_items", ["category_id", "due_at"])
    op.create_index("idx_submissions_assignment_student", "submissions", ["assignment_id", "student_id"])
    op.create_index("idx_quiz_questions_quiz_order", "questions", ["quiz_id", "sort_order"])
    op.create_index("idx_attendance_class_date", "attendance", ["class_id", "date"])
    op.create_index("idx_class_members_class_status", "class_members", ["class_id", "status"])
    op.create_index("idx_tutoring_sessions_tutor_status", "tutoring_sessions", ["tutor_id", "status"])
    op.create_index("idx_tutoring_sessions_student_status", "tutoring_sessions", ["student_id", "status"])
    op.create_index("idx_ai_sessions_user_type", "ai_sessions", ["user_id", "session_type"])
    op.create_index("idx_ai_messages_session_order", "ai_messages", ["session_id", "id"])
    op.create_index("idx_messages_recipient_read", "messages", ["recipient_id", "is_read", sa.text("created_at DESC")])
    op.create_index("idx_family_links_parent_status", "family_links", ["parent_id", "status"])
    op.create_index("idx_family_links_student_status", "family_links", ["student_id", "status"])
    op.create_index("idx_processed_events_gateway_event", "processed_events", ["gateway", "event_id"])
    op.create_index("idx_discount_codes_active_expiry", "discount_codes", ["is_active", "expiry_date"])
    op.create_index("idx_reminder_logs_sub_type", "reminder_logs", ["subscription_id", "reminder_type"])
    op.create_index("idx_manual_payments_sub_status", "manual_payments", ["subscription_id", "status"])
    op.create_index("idx_payment_receipts_payment", "payment_receipts", ["manual_payment_id"])

    # ============================================================
    # PARTIAL INDEXES for active records only
    # ============================================================

    op.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_active_tenant ON subscriptions (class_id, status) WHERE status IN ('active','pending','pending_review')")
    op.execute("CREATE INDEX IF NOT EXISTS idx_classes_active_tenant ON classes (school_id, is_active) WHERE is_active AND deleted_at IS NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_quizzes_active_tenant ON quizzes (class_id, status) WHERE status IN ('published','active') AND deleted_at IS NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_assignments_active_tenant ON assignments (class_id, due_at) WHERE due_at IS NOT NULL AND deleted_at IS NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_grade_items_active_tenant ON grade_items (class_id) WHERE deleted_at IS NULL")


def downgrade():
    # Drop denormalized columns
    for tbl in ("quiz_attempts", "submissions", "grade_entries", "notifications", "student_progress", "video_progress"):
        op.drop_index(f"idx_{tbl}_school_status" if tbl == "quiz_attempts" else
                      f"idx_{tbl}_school_submitted" if tbl == "submissions" else
                      f"idx_{tbl}_school" if tbl in ("grade_entries", "video_progress") else
                      f"idx_{tbl}_school_read" if tbl == "notifications" else
                      f"idx_{tbl}_school_lesson" if tbl == "student_progress" else "", table_name=tbl)
        op.drop_column(tbl, "school_id")

    # Drop additional composite indexes
    for idx in [
        "idx_lessons_class_unit_order",
        "idx_assignments_class_due_pub",
        "idx_grade_items_cat_due",
        "idx_submissions_assignment_student",
        "idx_quiz_questions_quiz_order",
        "idx_attendance_class_date",
        "idx_class_members_class_status",
        "idx_tutoring_sessions_tutor_status",
        "idx_tutoring_sessions_student_status",
        "idx_ai_sessions_user_type",
        "idx_ai_messages_session_order",
        "idx_messages_recipient_read",
        "idx_family_links_parent_status",
        "idx_family_links_student_status",
        "idx_processed_events_gateway_event",
        "idx_discount_codes_active_expiry",
        "idx_reminder_logs_sub_type",
        "idx_manual_payments_sub_status",
        "idx_payment_receipts_payment",
    ]:
        op.execute(f"DROP INDEX IF EXISTS {idx}")

    # Drop partial indexes
    for idx in [
        "idx_subscriptions_active_tenant",
        "idx_classes_active_tenant",
        "idx_quizzes_active_tenant",
        "idx_assignments_active_tenant",
        "idx_grade_items_active_tenant",
    ]:
        op.execute(f"DROP INDEX IF EXISTS {idx}")

    # Drop soft delete columns and indexes
    for tbl in (
        "grades", "subjects", "subscription_plans", "quizzes", "assignments",
        "grade_categories", "grade_items", "rubric_templates", "rubric_criteria",
        "units", "announcements", "attendance", "class_members", "submissions",
        "quiz_attempts", "answers", "proctoring_logs", "questions",
        "student_progress", "video_progress", "badges", "student_badges",
        "tutor_profiles", "tutoring_requests", "tutoring_sessions", "tutor_reviews",
        "tutor_commissions", "tutor_payouts", "ai_sessions", "ai_messages",
        "ai_usage_logs", "messages", "notifications", "notification_preferences",
        "contact_messages", "family_links", "family_link_codes", "discount_codes",
        "processed_events", "reminder_logs", "payment_receipts", "manual_payments",
        "school_settings", "subject_grade_links", "user_role_links",
    ):
        op.execute(f"DROP INDEX IF EXISTS idx_{tbl}_active")
        op.drop_column(tbl, "deleted_at")