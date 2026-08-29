"""fix student_progress.status varchar length

Revision ID: c1d2e3f4a5b6
Revises: b2c3d4e5f6g7
Create Date: 2026-08-29

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "c1d2e3f4a5b6"
down_revision = "b2c3d4e5f6g7"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "student_progress",
        "status",
        existing_type=sa.String(length=10),
        type_=sa.String(length=20),
        existing_nullable=False,
    )


def downgrade():
    op.alter_column(
        "student_progress",
        "status",
        existing_type=sa.String(length=20),
        type_=sa.String(length=10),
        existing_nullable=False,
    )
