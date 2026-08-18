"""Phase 2: question_bank, proctoring_logs, messages, quiz proctoring columns

Revision ID: a3b2c1d0e4f5
Revises: 15f5388d4cf8
Create Date: 2026-08-18

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a3b2c1d0e4f5"
down_revision = "15f5388d4cf8"
branch_labels = None
depends_on = None


def upgrade():
    # --- quizzes proctoring columns ---
    with op.batch_alter_table("quizzes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("enable_proctoring", sa.Boolean(), nullable=False, server_default="false"))
        batch_op.add_column(sa.Column("max_tab_switches", sa.Integer(), nullable=False, server_default="3"))
        batch_op.add_column(sa.Column("fullscreen_required", sa.Boolean(), nullable=False, server_default="false"))

    # --- proctoring_logs table ---
    op.create_table(
        "proctoring_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("attempt_id", sa.Integer(), sa.ForeignKey("quiz_attempts.id"), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- question_bank table ---
    op.create_table(
        "question_bank",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("teacher_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("question_type", sa.String(length=15), nullable=False),
        sa.Column("options", sa.JSON(), nullable=True),
        sa.Column("correct_answer", sa.JSON(), nullable=True),
        sa.Column("difficulty", sa.SmallInteger(), nullable=False, server_default="3"),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("is_shared", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("sort_order", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- messages table ---
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sender_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("recipient_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("parent_message_id", sa.Integer(), sa.ForeignKey("messages.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("messages")
    op.drop_table("question_bank")
    op.drop_table("proctoring_logs")

    with op.batch_alter_table("quizzes", schema=None) as batch_op:
        batch_op.drop_column("fullscreen_required")
        batch_op.drop_column("max_tab_switches")
        batch_op.drop_column("enable_proctoring")
