"""Add quiz_attempts.display_order for per-attempt question/option shuffling

Revision ID: m6n7o8p9q0r1
Revises: l5m6n7o8p9q0
Create Date: 2026-10-04 00:00:00.000000

The ``Quiz.shuffle`` flag existed and was offered on the form, but nothing
read it: questions and MCQ options always rendered in the author's order, so
a student could answer "question 3" from memory of a previous attempt.

The order is stored on the attempt rather than shuffled at render time. Two
reasons, both load-bearing:

* A refresh must not move the options under the student's cursor. Rendering
  order derived from ``random`` at request time changes between the load and
  the submit, and the answer saved would belong to a different option.
* The stored answer uses the *author's* option index, so ``correct_answer``
  stays valid for every order. Grading therefore needs no knowledge of
  shuffling at all.

``display_order`` is nullable: attempts created before this migration (and
quizzes with ``shuffle`` off) keep the natural order.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "m6n7o8p9q0r1"
down_revision = "l5m6n7o8p9q0"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    return column_name in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    if not _has_column("quiz_attempts", "display_order"):
        op.add_column(
            "quiz_attempts",
            sa.Column("display_order", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )


def downgrade() -> None:
    if _has_column("quiz_attempts", "display_order"):
        op.drop_column("quiz_attempts", "display_order")
