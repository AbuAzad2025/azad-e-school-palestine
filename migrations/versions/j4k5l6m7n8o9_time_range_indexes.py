"""time-range indexes — remove sequential scans from date-window and DESC-order queries

Revision ID: j4k5l6m7n8o9
Revises: i3j4k5l6m7n8
Create Date: 2026-10-02

P2-PERF-03: كل الفهارس القائمة مركّبة على مفاتيح غرفية (class_id / user_id /
status)، ولا يوجد فهرس واحد على created_at في أي جدول. مع ذلك تُنفَّذ
عشرات الاستعلامات بنافذة زمنية أو بترتيب تنازلي على created_at — وهي تُفحص
بمسح تسلسلي كامل (O(rows)) بمجرد أن يتجاوز الجدول ذاكرة PostgreSQL المؤقتة،
وتصير أبطأ خطياً مع نمو الجداول لأن PKMixin يضيف العمود بلا فهرس.

كل فهرس أدناه مرتبط باستعلام موجود فعلياً في الكود (سطره في التعليق)، ولم
يُبنَ شيء بلا مرجع. الفهارس المركّبة تضع عمود التصفية أولاً ثم عمود الترتيب
حتى يخدم B-tree المسارَين معاً بدل فهرس + فرز (index scan + sort) في كل طلب.

التكلفة: كل فهرس إضافي يجعل INSERT أبطأ. لذلك اقتصرنا على الجداول ذات
النمو المستمر والاستعلام المتكرر، واستُخدم فهرس جزئي (partial) حيث الحالة
نادرة flakes — فحجمه يبقى صغيراً ولا يثقل الكتابة إلا على الطاولات الحقيقية.

الإنشاء idempotent (IF NOT EXISTS عبر فحص المفتاح) ليعمل على قواعد موجودة.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "j4k5l6m7n8o9"
down_revision = "i3j4k5l6m7n8"
branch_labels = None
depends_on = None

# (table, index_name, columns, postgresql_where)
# كل سطر يقابل استعلاماً في الكود — لا فهرس بلا مستهلك.
_TIME_INDEXES: list[tuple[str, str, list[str], str | None]] = [
    # analytics.get_analytics_data: نافذة 7 أيام للمستخدمين النشطين يومياً
    ("student_progress", "ix_student_progress_created_at", ["created_at"], None),
    # analytics.get_analytics_data: تسجيلات جديدة لكل يوم
    ("users", "ix_users_created_at", ["created_at"], None),
    # analytics.get_analytics_data: created_at + status
    ("tutoring_sessions", "ix_tutoring_sessions_created_status", ["created_at", "status"], None),
    # ai.usage cutoff + ai_usage.monthly_stats: نافذة زمنية على جدول كتابة عالية
    ("ai_usage_logs", "ix_ai_usage_logs_created_at", ["created_at"], None),
    # revenue + payments.reconcile: نافذة زمنية على المدفوعات اليدوية
    ("manual_payments", "ix_manual_payments_created_at", ["created_at"], None),
    # gradebook.list_assignments: ترتيب داخل صف + created_at تنازلياً
    ("assignments", "ix_assignments_class_created", ["class_id", "created_at"], None),
    # messages.inbox: (is_read, created_at) لصندوق الوارد
    ("messages", "ix_messages_recipient_read_created", ["recipient_id", "is_read", "created_at"], None),
    # ai.last_messages: آخر 10 رسائل في جلسة
    ("ai_messages", "ix_ai_messages_session_created", ["session_id", "created_at"], None),
    # grade_appeals.get_pending_appeals: الطاولات المعلّقة فقط (طاولة صغيرة)
    ("grade_appeals", "ix_grade_appeals_pending_created", ["created_at"], "status = 'pending'"),
]


def _index_inventory() -> dict[str, set[str]]:
    """خريطة واحدة {جدول: {فهارس}} بجولة تفتيش واحدة بدل تفتيش لكل فهرس."""
    inspector = sa.inspect(op.get_bind())
    return {table: {ix["name"] for ix in inspector.get_indexes(table)} for table in inspector.get_table_names()}


def upgrade() -> None:
    inventory = _index_inventory()
    for table, index_name, columns, where in _TIME_INDEXES:
        # جدول غير موجود في قواعد أقدم لا يجعل الترحيل يفشل
        if table not in inventory:
            continue
        if index_name in inventory[table]:
            continue
        op.create_index(index_name, table, columns, postgresql_where=sa.text(where) if where else None)


def downgrade() -> None:
    inventory = _index_inventory()
    for table, index_name, _columns, _where in _TIME_INDEXES:
        if index_name not in inventory.get(table, set()):
            continue
        op.drop_index(index_name, table_name=table)
