"""تدقيق أمني: طابع تغيير كلمة المرور + فهارس فريدة جزئية

- P1-02: users.password_changed_at
- P2-07: استبدال قيد uq_subscription_active بفهرس جزئي (user_id, class_id) WHERE status='active'
- P1-05: فهرس جزئي uq_attempt_open_per_quiz_student WHERE status='in_progress'

Revision ID: a1b2c3d4e5f6
Revises: 5c63f56be2b2
Create Date: 2026-08-26
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "5c63f56be2b2"
branch_labels = None
depends_on = None


def upgrade():
    # P1-02
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))

    # P2-07: القيد القديم على 4 أعمدة يمنع إعادة الاشتراك بعد الانتهاء
    op.drop_constraint("uq_subscription_active", "subscriptions", type_="unique")
    op.create_index(
        "uq_subscription_active",
        "subscriptions",
        ["user_id", "class_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    # P1-05
    op.create_index(
        "uq_attempt_open_per_quiz_student",
        "quiz_attempts",
        ["quiz_id", "student_id"],
        unique=True,
        postgresql_where=sa.text("status = 'in_progress'"),
    )


def downgrade():
    op.drop_index("uq_attempt_open_per_quiz_student", table_name="quiz_attempts")
    op.drop_index("uq_subscription_active", table_name="subscriptions")
    op.create_unique_constraint(
        "uq_subscription_active",
        "subscriptions",
        ["user_id", "plan_id", "class_id", "status"],
    )
    op.drop_column("users", "password_changed_at")
