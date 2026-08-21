"""P0: Critical indexes, check constraints, JSONB GIN indexes

Revision ID: c0f0d1e2a3b4
Revises: a3b2c1d0e4f5
Create Date: 2026-08-21

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c0f0d1e2a3b4"
down_revision = "f0e1d2c3b4a5"
branch_labels = None
depends_on = None


def upgrade():
    # ============================================================
    # CHECK CONSTRAINTS — data integrity
    # ============================================================

    # subscriptions status
    op.execute("""
        ALTER TABLE subscriptions
        ADD CONSTRAINT chk_sub_status
        CHECK (status IN ('pending','active','expired','cancelled','pending_review'))
    """)

    # quiz_attempts status
    op.execute("""
        ALTER TABLE quiz_attempts
        ADD CONSTRAINT chk_attempt_status
        CHECK (status IN ('in_progress','submitted','graded','auto_submitted','abandoned'))
    """)

    # quiz_attempts attempt_no positive
    op.execute("""
        ALTER TABLE quiz_attempts
        ADD CONSTRAINT chk_attempt_no_positive
        CHECK (attempt_no > 0)
    """)

    # quiz_attempts time ordering
    op.execute("""
        ALTER TABLE quiz_attempts
        ADD CONSTRAINT chk_attempt_times
        CHECK (submitted_at IS NULL OR started_at IS NULL OR submitted_at >= started_at)
    """)

    # discount_codes usage
    op.execute("""
        ALTER TABLE discount_codes
        ADD CONSTRAINT chk_discount_usage
        CHECK (used_count <= max_uses AND max_uses > 0)
    """)

    # tutor_payouts amount positive
    op.execute("""
        ALTER TABLE tutor_payouts
        ADD CONSTRAINT chk_payout_amount
        CHECK (amount > 0)
    """)

    # classes prices non-negative
    op.execute("""
        ALTER TABLE classes
        ADD CONSTRAINT chk_class_price_first
        CHECK (price_first_term IS NULL OR price_first_term >= 0)
    """)
    op.execute("""
        ALTER TABLE classes
        ADD CONSTRAINT chk_class_price_second
        CHECK (price_second_term IS NULL OR price_second_term >= 0)
    """)
    op.execute("""
        ALTER TABLE classes
        ADD CONSTRAINT chk_class_price_annual
        CHECK (price_annual IS NULL OR price_annual >= 0)
    """)

    # ============================================================
    # COMPOSITE INDEXES — tenant-scoped queries
    # ============================================================

    op.create_index(
        "idx_lessons_class_status_pub",
        "lessons",
        ["class_id", "status"],
        postgresql_where=sa.text("status = 'published'"),
    )

    op.create_index(
        "idx_quiz_attempts_tenant_lookup",
        "quiz_attempts",
        ["quiz_id", "student_id", "attempt_no"],
    )

    op.create_index(
        "idx_notifications_inbox",
        "notifications",
        ["user_id", "is_read", sa.text("created_at DESC")],
    )

    op.create_index(
        "idx_student_progress_triple",
        "student_progress",
        ["class_id", "lesson_id", "student_id"],
    )

    op.create_index(
        "idx_video_progress_lookup",
        "video_progress",
        ["lesson_id", "student_id"],
    )

    op.create_index(
        "idx_ai_usage_analytics",
        "ai_usage_logs",
        ["user_id", "action", sa.text("created_at DESC")],
    )

    op.create_index(
        "idx_classes_school_active",
        "classes",
        ["school_id", "is_active"],
    )

    op.create_index(
        "idx_assignments_class_due",
        "assignments",
        ["class_id", "due_at"],
    )

    op.create_index(
        "idx_quizzes_class_status",
        "quizzes",
        ["class_id", "status"],
    )

    op.create_index(
        "idx_submissions_class_submitted",
        "submissions",
        ["assignment_id", sa.text("submitted_at DESC")],
    )

    op.create_index(
        "idx_grade_entries_item_student",
        "grade_entries",
        ["grade_item_id", "student_id"],
    )

    # ============================================================
    # JSONB GIN INDEXES — containment / key-exists queries
    # ============================================================

    # JSONB columns (native GIN support)
    op.execute("CREATE INDEX IF NOT EXISTS idx_school_settings_val ON school_settings USING GIN (value)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_questions_options ON questions USING GIN (options)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_questions_correct ON questions USING GIN (correct_answer)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tutor_availability ON tutor_profiles USING GIN (availability)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_subscription_benefits ON subscription_plans USING GIN (benefits)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_processed_events_payload ON processed_events USING GIN (payload)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ai_usage_meta ON ai_usage_logs USING GIN (meta)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_question_bank_tags ON question_bank USING GIN (tags)")

    # Text/varchar columns need pg_trgm extension + gin_trgm_ops
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE INDEX IF NOT EXISTS idx_lesson_attachments_mime ON lesson_attachments USING GIN (mime gin_trgm_ops)")

    # ============================================================
    # PARTIAL INDEX for active-only soft-deleted tables
    # ============================================================

    op.execute("CREATE INDEX IF NOT EXISTS idx_users_active ON users (id) WHERE deleted_at IS NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_classes_active ON classes (school_id) WHERE deleted_at IS NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_lessons_active ON lessons (class_id) WHERE deleted_at IS NULL")


def downgrade():
    # Drop check constraints
    op.execute("ALTER TABLE subscriptions DROP CONSTRAINT IF EXISTS chk_sub_status")
    op.execute("ALTER TABLE quiz_attempts DROP CONSTRAINT IF EXISTS chk_attempt_status")
    op.execute("ALTER TABLE quiz_attempts DROP CONSTRAINT IF EXISTS chk_attempt_no_positive")
    op.execute("ALTER TABLE quiz_attempts DROP CONSTRAINT IF EXISTS chk_attempt_times")
    op.execute("ALTER TABLE discount_codes DROP CONSTRAINT IF EXISTS chk_discount_usage")
    op.execute("ALTER TABLE tutor_payouts DROP CONSTRAINT IF EXISTS chk_payout_amount")
    op.execute("ALTER TABLE classes DROP CONSTRAINT IF EXISTS chk_class_price_first")
    op.execute("ALTER TABLE classes DROP CONSTRAINT IF EXISTS chk_class_price_second")
    op.execute("ALTER TABLE classes DROP CONSTRAINT IF EXISTS chk_class_price_annual")

    # Drop indexes
    op.drop_index("idx_lessons_class_status_pub", table_name="lessons")
    op.drop_index("idx_quiz_attempts_tenant_lookup", table_name="quiz_attempts")
    op.drop_index("idx_notifications_inbox", table_name="notifications")
    op.drop_index("idx_student_progress_triple", table_name="student_progress")
    op.drop_index("idx_video_progress_lookup", table_name="video_progress")
    op.drop_index("idx_ai_usage_analytics", table_name="ai_usage_logs")
    op.drop_index("idx_classes_school_active", table_name="classes")
    op.drop_index("idx_assignments_class_due", table_name="assignments")
    op.drop_index("idx_quizzes_class_status", table_name="quizzes")
    op.drop_index("idx_submissions_class_submitted", table_name="submissions")
    op.drop_index("idx_grade_entries_item_student", table_name="grade_entries")

    op.execute("DROP INDEX IF EXISTS idx_school_settings_val")
    op.execute("DROP INDEX IF EXISTS idx_questions_options")
    op.execute("DROP INDEX IF EXISTS idx_questions_correct")
    op.execute("DROP INDEX IF EXISTS idx_tutor_availability")
    op.execute("DROP INDEX IF EXISTS idx_subscription_benefits")
    op.execute("DROP INDEX IF EXISTS idx_processed_events_payload")
    op.execute("DROP INDEX IF EXISTS idx_ai_usage_meta")
    op.execute("DROP INDEX IF EXISTS idx_lesson_attachments_mime")
    op.execute("DROP INDEX IF EXISTS idx_question_bank_tags")

    op.execute("DROP INDEX IF EXISTS idx_users_active")
    op.execute("DROP INDEX IF EXISTS idx_classes_active")
    op.execute("DROP INDEX IF EXISTS idx_lessons_active")