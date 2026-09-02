"""إضافة كود الانضمام للمدرسة (school join_code)

هذا الكود يُستخدم في تسجيل حسابات المعلمين والطلاب وأولياء الأمور
لاستكمال عملية الربط بالمدرسة المناسبة.

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-26
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6g7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column in {c["name"] for c in inspector.get_columns(table)}


def _constraint_exists(table: str, name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return name in {c["name"] for c in inspector.get_unique_constraints(table)}


def upgrade():
    if not _column_exists("schools", "join_code"):
        op.add_column(
            "schools",
            sa.Column("join_code", postgresql.CITEXT(), nullable=True),
        )
    if not _constraint_exists("schools", "uq_school_join_code"):
        op.create_unique_constraint("uq_school_join_code", "schools", ["join_code"])


def downgrade():
    if _constraint_exists("schools", "uq_school_join_code"):
        op.drop_constraint("uq_school_join_code", "schools", type_="unique")
    if _column_exists("schools", "join_code"):
        op.drop_column("schools", "join_code")
