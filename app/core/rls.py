"""PostgreSQL Row Level Security (RLS) — دفاع الطابق الثاني.

RLS يفرض عزل التينانتس على مستوى قاعدة البيانات نفسها. حتى لو خانت
التطبيق طبقة scope_by_school()، فإن PostgreSQL نفسها ترفض إرجاع بيانات
مدرسة أخرى.

الآلية:
  1. كل جدول يحمل school_id يُفعَّل عليه RLS مع سياسة بسيطة:
     WHERE school_id = current_setting('app.current_school_id')::bigint
  2. قبل كل طلب، يُضبط المتغير عبر SET LOCAL داخل نفس المعاملة.
  3. super_admin يتخطى RLS عبر bypass_policy.

P3-01: RLS as secondary fail-safe behind scope_by_school().
P3-02: Session-level variable set via SET LOCAL (auto-reset on transaction end).
"""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.core.logging import get_logger
from app.extensions import db

logger = get_logger(__name__)


def _table_exists(table_name: str) -> bool:
    """حماية زمن التشغيل: الجدول قد لا يكون موجوداً (اختبارات/ترحيل قديم)."""
    try:
        return inspect(db.session.get_bind()).has_table(table_name)
    except Exception:  # noqa: BLE001 — لا يوجد اتصال/جدول
        return False


def _has_column(table_name: str, column_name: str) -> bool:
    """فحص وجود عمود قبل بناء سياسة تعتمد عليه (مثل school_id)."""
    try:
        cols = inspect(db.session.get_bind()).get_columns(table_name)
        return column_name in {c["name"] for c in cols}
    except Exception:  # noqa: BLE001
        return False


# ─── Tables that carry school_id and MUST have RLS ─────────────────────
_TENANT_TABLES: list[str] = [
    "academic_events",
    "announcements",
    "assignments",
    "attendance",
    "audit_logs",
    "class_members",
    "classes",
    "certificate_templates",
    "discount_codes",
    "grade_categories",
    "grade_items",
    "grades",
    "lessons",
    "lesson_attachments",
    "onboarding_progress",
    "question_bank",
    "rubric_criteria",
    "rubric_templates",
    "school_settings",
    "student_progress",
    "whatsapp_links",
    "subscription_plans",
    "subscriptions",
    "tenant_quotas",
    "units",
    "video_progress",
    "offline_downloads",
    "manual_payments",
    "payment_receipts",
    "wallets",
    "wallet_transactions",
]

# Tables scoped by the acting user rather than by tenant.
#
# ``user_role_links`` is the table that *derives* the user's school, so a
# school-scoped policy would be circular — the query that resolves the tenant
# would be filtered by the tenant it is resolving. It is therefore scoped by
# ``app.current_user_id``, and ``audit_logs`` follows the same rule: a row
# records what *one* actor did, so each user reads their own trail and
# ``super_admin`` reads everything.
#
# The comparison is on ``::text`` on purpose: ``current_setting`` of an unset
# custom GUC returns ``''``, and ``''::bigint`` raises ``invalid input syntax``
# for every row of the table. Text comparison is total, so an unset variable
# simply matches nothing instead of exploding. PostgreSQL does not guarantee the
# evaluation order of the ``OR`` branches, so the safe form must be the one in
# both branches.
_USER_SCOPED_TABLES: list[str] = ["user_role_links", "audit_logs"]

# Tables that reference school_id via a JOIN through another table
# (indirect tenancy — RLS policy uses subquery)
_INDIRECT_TENANT_TABLES: dict[str, str] = {
    # Table: school_id derivation SQL
    #
    # Most of these predate a school_id column: they hang off ``classes`` (or
    # a table that does), and RLS used to skip them with a warning, which left
    # attendance, grades and billing with a single line of defence. The path
    # below restores the database-level floor without duplicating school_id
    # across the schema — a copied column drifts the moment a class moves.
    "announcements": "SELECT c.school_id FROM classes c WHERE c.id = announcements.class_id",
    "assignments": "SELECT c.school_id FROM classes c WHERE c.id = assignments.class_id",
    "attendance": "SELECT c.school_id FROM classes c WHERE c.id = attendance.class_id",
    "class_members": "SELECT c.school_id FROM classes c WHERE c.id = class_members.class_id",
    "grade_categories": "SELECT c.school_id FROM classes c WHERE c.id = grade_categories.class_id",
    "grade_items": "SELECT c.school_id FROM classes c WHERE c.id = grade_items.class_id",
    "lessons": "SELECT c.school_id FROM classes c WHERE c.id = lessons.class_id",
    "lesson_attachments": (
        "SELECT c.school_id FROM classes c JOIN units u ON u.class_id = c.id "
        "JOIN lessons l ON l.unit_id = u.id WHERE l.id = lesson_attachments.lesson_id"
    ),
    "rubric_criteria": ("SELECT t.school_id FROM rubric_templates t WHERE t.id = rubric_criteria.template_id"),
    "student_progress": "SELECT c.school_id FROM classes c WHERE c.id = student_progress.class_id",
    "subscriptions": "SELECT c.school_id FROM classes c WHERE c.id = subscriptions.class_id",
    "units": "SELECT c.school_id FROM classes c WHERE c.id = units.class_id",
    "video_progress": "SELECT c.school_id FROM classes c WHERE c.id = video_progress.class_id",
    "offline_downloads": (
        "SELECT c.school_id FROM classes c JOIN units u ON u.class_id = c.id "
        "JOIN lessons l ON l.unit_id = u.id WHERE l.id = offline_downloads.lesson_id"
    ),
    "manual_payments": (
        "SELECT c.school_id FROM classes c JOIN subscriptions s ON s.class_id = c.id "
        "WHERE s.id = manual_payments.subscription_id"
    ),
    "payment_receipts": (
        "SELECT c.school_id FROM classes c JOIN subscriptions s ON s.class_id = c.id "
        "JOIN manual_payments mp ON mp.subscription_id = s.id "
        "WHERE mp.id = payment_receipts.manual_payment_id"
    ),
    "quiz_attempts": (
        "SELECT c.school_id FROM classes c JOIN quizzes q ON q.class_id = c.id WHERE q.id = quiz_attempts.quiz_id"
    ),
    "answers": (
        "SELECT c.school_id FROM classes c "
        "JOIN quizzes q ON q.class_id = c.id "
        "JOIN quiz_attempts qa ON qa.quiz_id = q.id "
        "WHERE qa.id = answers.attempt_id"
    ),
    "quizzes": "SELECT c.school_id FROM classes c WHERE c.id = quizzes.class_id",
    "grade_entries": (
        "SELECT c.school_id FROM classes c "
        "JOIN grade_items gi ON gi.class_id = c.id "
        "WHERE gi.id = grade_entries.grade_item_id"
    ),
    "submissions": (
        "SELECT c.school_id FROM classes c "
        "JOIN assignments a ON a.class_id = c.id "
        "WHERE a.id = submissions.assignment_id"
    ),
    "proctoring_logs": (
        "SELECT c.school_id FROM classes c "
        "JOIN quizzes q ON q.class_id = c.id "
        "JOIN quiz_attempts qa ON qa.quiz_id = q.id "
        "WHERE qa.id = proctoring_logs.attempt_id"
    ),
}


def set_tenant_context(school_id: int | None) -> None:
    """Set the PostgreSQL session variable for RLS.

    Must be called within an active transaction (before any queries).
    Uses SET LOCAL so the variable auto-resets when the transaction ends.

    Args:
        school_id: The tenant's school ID, or None for super_admin bypass.
    """
    if school_id is None:
        # super_admin: bypass RLS by setting to 0 (no school has id=0)
        db.session.execute(text("SET LOCAL app.current_school_id = '0'"))
        db.session.execute(text("SET LOCAL app.is_super_admin = '1'"))
    else:
        db.session.execute(
            text("SET LOCAL app.current_school_id = :sid"),
            {"sid": str(school_id)},
        )
        db.session.execute(text("SET LOCAL app.is_super_admin = '0'"))


def reset_tenant_context() -> None:
    """Reset the session variables (defensive — SET LOCAL auto-resets)."""
    try:
        db.session.execute(text("RESET app.current_school_id"))
        db.session.execute(text("RESET app.is_super_admin"))
    except Exception:
        pass  # Non-critical: SET LOCAL auto-resets on transaction end


def enable_rls_on_table(table_name: str) -> bool:
    """Enable RLS and create the tenant isolation policy for a single table.

    Idempotent: safe to run multiple times.

    Returns True when a policy was (re)created, False when the table was
    skipped (missing table or missing school_id column — same guard as the
    g1h2i3j4k5l6 migration, so enable_all can never crash at runtime).
    """
    if not _table_exists(table_name):
        logger.warning("rls_skipped", table=table_name, reason="table does not exist")
        return False
    if not _has_column(table_name, "school_id"):
        # BUGFIX: several registry entries predate a schema decision (e.g.
        # announcements traces tenancy via classes, not a school_id column).
        # Building a policy against a missing column raises UndefinedColumn.
        logger.warning("rls_skipped", table=table_name, reason="missing school_id column")
        return False

    # 1. Enable RLS on the table
    db.session.execute(text(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY"))
    # 2. Force RLS even for table owners (defense in depth)
    db.session.execute(text(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY"))

    # 3. Drop existing policy if any (idempotent)
    policy_name = f"tenant_isolation_{table_name}"
    db.session.execute(text(f"DROP POLICY IF EXISTS {policy_name} ON {table_name}"))

    # 4. Create the policy
    #    - If is_super_admin = '1': allow all (super_admin bypass)
    #    - Otherwise: require school_id match
    db.session.execute(
        text(
            f"""
            CREATE POLICY {policy_name} ON {table_name}
                FOR ALL
                USING (
                    current_setting('app.is_super_admin', true) = '1'
                    OR school_id = current_setting('app.current_school_id', true)::bigint
                )
                WITH CHECK (
                    current_setting('app.is_super_admin', true) = '1'
                    OR school_id = current_setting('app.current_school_id', true)::bigint
                )
        """
        )
    )
    logger.info("rls_policy_created", table=table_name, policy=policy_name)
    return True


def enable_rls_on_indirect_table(table_name: str, subquery: str) -> bool:
    """Enable RLS on a table where school_id is derived via subquery.

    Used for tables like quiz_attempts that don't directly have school_id
    but can be traced to one through joins.

    Returns True when a policy was (re)created, False when skipped.
    """
    if not _table_exists(table_name):
        logger.warning("rls_skipped", table=table_name, reason="table does not exist")
        return False

    db.session.execute(text(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY"))
    db.session.execute(text(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY"))

    policy_name = f"tenant_isolation_{table_name}"
    db.session.execute(text(f"DROP POLICY IF EXISTS {policy_name} ON {table_name}"))

    db.session.execute(
        text(
            f"""
            CREATE POLICY {policy_name} ON {table_name}
                FOR ALL
                USING (
                    current_setting('app.is_super_admin', true) = '1'
                    OR ({subquery}) = current_setting('app.current_school_id', true)::bigint
                )
                WITH CHECK (
                    current_setting('app.is_super_admin', true) = '1'
                    OR ({subquery}) = current_setting('app.current_school_id', true)::bigint
                )
        """
        )
    )
    logger.info("rls_policy_created_indirect", table=table_name, policy=policy_name)
    return True


def enable_rls_on_user_scoped_table(table_name: str) -> bool:
    """Enable RLS for a table scoped by the acting user, not by tenant.

    Used for ``user_role_links`` (the table the tenant is derived from — a
    school policy there is circular) and ``audit_logs`` (a row records what one
    actor did). ``super_admin`` keeps full visibility.

    The identity comparison uses ``::text`` so an unset ``app.current_user_id``
    (empty string) matches nothing instead of raising ``invalid input syntax``
    for every row — and it cannot be pushed into the ``OR``'s other branch,
    because PostgreSQL does not promise to evaluate ``OR`` left to right.

    Returns True when a policy was (re)created, False when skipped.
    """
    if not _table_exists(table_name):
        logger.warning("rls_skipped", table=table_name, reason="table does not exist")
        return False

    db.session.execute(text(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY"))
    db.session.execute(text(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY"))

    policy_name = f"tenant_isolation_{table_name}"
    db.session.execute(text(f"DROP POLICY IF EXISTS {policy_name} ON {table_name}"))
    db.session.execute(
        text(
            f"""
            CREATE POLICY {policy_name} ON {table_name}
                FOR ALL
                USING (
                    current_setting('app.is_super_admin', true) = '1'
                    OR user_id::text = current_setting('app.current_user_id', true)
                )
                WITH CHECK (
                    current_setting('app.is_super_admin', true) = '1'
                    OR user_id::text = current_setting('app.current_user_id', true)
                )
        """
        )
    )
    logger.info("rls_policy_created_user_scoped", table=table_name, policy=policy_name)
    return True


def enable_all_rls_policies() -> None:
    """Enable RLS on all tenant-scoped tables.  Call from Alembic migration.

    Tables lacking a school_id column (schema decision pending) are skipped
    with a warning instead of crashing the whole migration/upgrade.

    """
    enabled: list[str] = []
    skipped: list[str] = []
    for table in _TENANT_TABLES:
        (enabled if enable_rls_on_table(table) else skipped).append(table)

    for table, subquery in _INDIRECT_TENANT_TABLES.items():
        (enabled if enable_rls_on_indirect_table(table, subquery) else skipped).append(table)

    for table in _USER_SCOPED_TABLES:
        (enabled if enable_rls_on_user_scoped_table(table) else skipped).append(table)

    db.session.commit()
    logger.info("all_rls_policies_enabled", enabled=len(enabled), skipped=len(skipped))
    if skipped:
        logger.warning("rls_skipped_tables", tables=skipped)


def disable_all_rls_policies() -> None:
    """Disable RLS on all tables.  Used for rollback migration."""
    all_tables = _TENANT_TABLES + list(_INDIRECT_TENANT_TABLES.keys()) + _USER_SCOPED_TABLES
    for table in all_tables:
        policy_name = f"tenant_isolation_{table}"
        try:
            db.session.execute(text(f"DROP POLICY IF EXISTS {policy_name} ON {table}"))
            db.session.execute(text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
        except Exception:
            pass  # Table may not exist in test environment
    db.session.commit()
