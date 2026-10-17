"""Absence alert dedup log — one record per (student, absent day)

Revision ID: t3u4v5w6x7y8
Revises: s2t3u4v5w6x7
Create Date: 2026-10-17 00:00:00.000000

Why this migration exists
-------------------------
AZ-P2-12: ``send_absence_alert_email`` existed (and was test-covered) but no
route or scheduled job ever called it. Once the daily job wires it to the
linked guardian of every student recorded absent for the day, the cron-triggered
re-run must not email the same parent twice for the same student/day. That
requires a dedup log backed by a UNIQUE constraint rather than application-level
counting — concurrent or retried job runs would interleave reads ahead of writes
and duplicate alerts, exactly the failure mode the constraint eliminates.

No school_id here
-----------------
The log is keyed by student and read only server-side by the scheduled job; the
tenant-scoped join path already goes through ``FamilyLink``/``Attendance`` which
carry their own scoping. Adding a copy of ``school_id`` here would create a
second write target that must be kept consistent with the student's actual
school — a denormalization hazard with no reading route.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "t3u4v5w6x7y8"
down_revision = "s2t3u4v5w6x7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "absence_alert_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("student_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False, index=False),
        sa.Column("parent_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("student_id", "date", name="uq_absence_alert_day"),
    )
    op.create_index("ix_absence_alert_logs_student_id", "absence_alert_logs", ["student_id"])
    op.create_index("ix_absence_alert_logs_date", "absence_alert_logs", ["date"])


def downgrade() -> None:
    op.drop_table("absence_alert_logs")
