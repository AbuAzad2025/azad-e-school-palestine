"""RLS performance indexes — composite indexes for indirect-policy subqueries

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6m7
Create Date: 2026-09-09

P2-PERF-02: سياسات RLS غير المباشرة تُقيّم subquery لكل صف يُمس في كل
استعلام. بدون فهارس مركّبة تبدأ بمعرّف الجدول المستهدف يتحول الفحص إلى
seq scan على الجداول الوسيطة. هذه الفهارس تجعل كل subquery فحص فهرس.

كل فهرس يوضع على الجدول الوسيط بأعمدة (pk الوسيط + مفتاح الانضمام التالي)
بحيث يطابق نمط الاستخدام في سياسات rls.py بالضبط. الإنشاء idempotent
(IF NOT EXISTS) ليعمل على قواعد موجودة وقاعدة RLS migration القديمة.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "i3j4k5l6m7n8"
down_revision = "h2i3j4k5l6m7"
branch_labels = None
depends_on = None

# (table, index_name, columns) — one per indirect RLS subquery join path
_RLS_SUPPORT_INDEXES: list[tuple[str, str, list[str]]] = [
    # quizzes: WHERE c.id = quizzes.class_id → join on quizzes.class_id
    ("quizzes", "ix_rls_quizzes_class_id", ["class_id", "id"]),
    # quiz_attempts: JOIN quizzes q ON q.class_id=c.id WHERE q.id=qa.quiz_id
    ("quiz_attempts", "ix_rls_quiz_attempts_quiz_id", ["quiz_id", "id"]),
    # answers: JOIN quiz_attempts qa WHERE qa.id = answers.attempt_id
    ("answers", "ix_rls_answers_attempt_id", ["attempt_id", "id"]),
    # grade_entries: JOIN grade_items gi WHERE gi.id = grade_entries.grade_item_id
    ("grade_entries", "ix_rls_grade_entries_item_id", ["grade_item_id", "id"]),
    # submissions: JOIN assignments a WHERE a.id = submissions.assignment_id
    ("submissions", "ix_rls_submissions_assignment_id", ["assignment_id", "id"]),
    # proctoring_logs: WHERE qa.id = proctoring_logs.attempt_id
    ("proctoring_logs", "ix_rls_proctoring_attempt_id", ["attempt_id", "id"]),
    # classes side of every policy: c.id lookup + school_id projection
    ("classes", "ix_rls_classes_id_school", ["id", "school_id"]),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, index_name, columns in _RLS_SUPPORT_INDEXES:
        if table not in inspector.get_table_names():
            continue
        existing = {ix["name"] for ix in inspector.get_indexes(table)}
        if index_name in existing:
            continue
        op.create_index(index_name, table, columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, index_name, _cols in _RLS_SUPPORT_INDEXES:
        if table not in inspector.get_table_names():
            continue
        existing = {ix["name"] for ix in inspector.get_indexes(table)}
        if index_name in existing:
            op.drop_index(index_name, table_name=table)
