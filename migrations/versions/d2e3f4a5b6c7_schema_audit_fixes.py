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
    # 1. GradeCategory.weight: Numeric(3,2) -> Numeric(5,2)
    op.alter_column(
        "grade_categories",
        "weight",
        existing_type=sa.Numeric(3, 2),
        type_=sa.Numeric(5, 2),
        existing_nullable=True,
    )

    # 2. Add ON DELETE SET NULL to nullable FKs
    #    Use op.alter_column with existing_foreign_keys to modify in place.
    #    For tables where we can't easily alter, we drop and recreate.
    fk_updates = [
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

    for table, col, ref_table in fk_updates:
        fk_name = f"fk_{table}_{col}_ondelete_setnull"
        # Drop any existing FK on this column using Alembic's inspector
        bind = op.get_bind()
        inspector = sa.inspect(bind)
        fks = inspector.get_foreign_keys(table)
        for fk in fks:
            if col in fk["constrained_columns"]:
                op.drop_constraint(fk["name"], table, type_="foreignkey")
                break
        # Recreate with ON DELETE SET NULL
        op.create_foreign_key(
            fk_name, table, ref_table, [col], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    # Revert weight precision
    op.alter_column(
        "grade_categories",
        "weight",
        existing_type=sa.Numeric(5, 2),
        type_=sa.Numeric(3, 2),
        existing_nullable=True,
    )

    # Drop the SET NULL FK constraints
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
        fk_name = f"fk_{table}_{col}_ondelete_setnull"
        op.drop_constraint(fk_name, table, type_="foreignkey")
