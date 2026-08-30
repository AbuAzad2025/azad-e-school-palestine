"""schema audit fixes: weight precision + FK ondelete SET NULL

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-08-30
"""

from alembic import op
import sqlalchemy as sa


revision = "d2e3f4a5b6c7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. GradeCategory.weight: Numeric(3,2) → Numeric(5,2) — fixes overflow for weights > 9.99
    op.alter_column(
        "grade_categories",
        "weight",
        existing_type=sa.Numeric(3, 2),
        type_=sa.Numeric(5, 2),
        existing_nullable=True,
    )

    # 2. Add ON DELETE SET NULL to all nullable FKs (prevents cascade failures)
    fk_set_null_updates = [
        ("user_role_links", "approved_by", "users"),
        ("classes", "teacher_id", "users"),
        ("lessons", "created_by", "users"),
        ("lessons", "original_lesson_id", "lessons"),
        ("quizzes", "created_by", "users"),
        ("assignments", "created_by", "users"),
        ("submissions", "graded_by", "users"),
        ("grade_entries", "recorded_by", "users"),
        ("rubric_grades", "graded_by", "users"),
        ("grade_appeals", "reviewed_by", "users"),
        ("manual_payments", "reviewed_by", "users"),
        ("attendance", "recorded_by", "users"),
        ("audit_logs", "user_id", "users"),
        ("ai_usage_logs", "user_id", "users"),
        ("tutor_payouts", "reviewed_by", "users"),
        ("subscription_plans", "class_id", "classes"),
        ("discount_codes", "school_id", "schools"),
        ("certificate_templates", "school_id", "schools"),
        ("question_bank", "subject_id", "subjects"),
        ("family_link_codes", "used_by", "users"),
        ("tutoring_sessions", "request_id", "tutoring_requests"),
    ]

    for table, col, ref_table in fk_set_null_updates:
        # Drop existing FK constraint (name varies by DB convention)
        op.execute(f"""
            DO $$
            DECLARE
                con_name text;
            BEGIN
                SELECT conname INTO con_name
                FROM pg_constraint
                WHERE conrelid = '{table}'::regclass
                  AND confrelid = '{ref_table}'::regclass
                  AND conkey = (SELECT attnum FROM pg_attribute WHERE attname = '{col}' AND attrelid = '{table}'::regclass)
                  AND contype = 'f';
                IF con_name IS NOT NULL THEN
                    EXECUTE 'ALTER TABLE {table} DROP CONSTRAINT ' || con_name;
                END IF;
            END $$;
        """)
        # Recreate with ON DELETE SET NULL
        op.execute(f"""
            ALTER TABLE {table}
            ADD CONSTRAINT fk_{table}_{col}
            FOREIGN KEY ({col}) REFERENCES {ref_table}(id) ON DELETE SET NULL
        """)


def downgrade() -> None:
    # Revert weight precision
    op.alter_column(
        "grade_categories",
        "weight",
        existing_type=sa.Numeric(5, 2),
        type_=sa.Numeric(3, 2),
        existing_nullable=True,
    )

    # Drop the new FK constraints (DB will use default behavior)
    fk_tables = [
        ("user_role_links", "approved_by"),
        ("classes", "teacher_id"),
        ("lessons", "created_by"),
        ("lessons", "original_lesson_id"),
        ("quizzes", "created_by"),
        ("assignments", "created_by"),
        ("submissions", "graded_by"),
        ("grade_entries", "recorded_by"),
        ("rubric_grades", "graded_by"),
        ("grade_appeals", "reviewed_by"),
        ("manual_payments", "reviewed_by"),
        ("attendance", "recorded_by"),
        ("audit_logs", "user_id"),
        ("ai_usage_logs", "user_id"),
        ("tutor_payouts", "reviewed_by"),
        ("subscription_plans", "class_id"),
        ("discount_codes", "school_id"),
        ("certificate_templates", "school_id"),
        ("question_bank", "subject_id"),
        ("family_link_codes", "used_by"),
        ("tutoring_sessions", "request_id"),
    ]

    for table, col in fk_tables:
        op.execute(f"""
            ALTER TABLE {table} DROP CONSTRAINT IF EXISTS fk_{table}_{col}
        """)
