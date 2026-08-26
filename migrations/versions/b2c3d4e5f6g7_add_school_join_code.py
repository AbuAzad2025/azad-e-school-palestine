"""إضافة كود الانضمام للمدرسة (school join_code)

هذا الكود يُستخدم في تسجيل حسابات المعلمين والطلاب وأولياء الأمور
لاستكمال عملية الربط بالمدرسة المناسبة.

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6g7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "schools",
        sa.Column("join_code", postgresql.CITEXT(), nullable=True),
    )
    op.create_unique_constraint("uq_school_join_code", "schools", ["join_code"])


def downgrade():
    op.drop_constraint("uq_school_join_code", "schools", type_="unique")
    op.drop_column("schools", "join_code")
