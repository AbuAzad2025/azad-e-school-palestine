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

from sqlalchemy import text

from app.core.logging import get_logger
from app.extensions import db

logger = get_logger(__name__)

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
    "subscription_plans",
    "subscriptions",
    "tenant_quotas",
    "units",
    "video_progress",
    "offline_downloads",
    "manual_payments",
    "payment_receipts",
]

# Tables that reference school_id via a JOIN through another table
# (indirect tenancy — RLS policy uses subquery)
_INDIRECT_TENANT_TABLES: dict[str, str] = {
    # Table: school_id derivation SQL
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


def enable_rls_on_table(table_name: str) -> None:
    """Enable RLS and create the tenant isolation policy for a single table.

    Idempotent: safe to run multiple times.
    """
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


def enable_rls_on_indirect_table(table_name: str, subquery: str) -> None:
    """Enable RLS on a table where school_id is derived via subquery.

    Used for tables like quiz_attempts that don't directly have school_id
    but can be traced to one through joins.
    """
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


def enable_all_rls_policies() -> None:
    """Enable RLS on all tenant-scoped tables.  Call from Alembic migration."""
    for table in _TENANT_TABLES:
        enable_rls_on_table(table)

    for table, subquery in _INDIRECT_TENANT_TABLES.items():
        enable_rls_on_indirect_table(table, subquery)

    db.session.commit()
    logger.info("all_rls_policies_enabled", count=len(_TENANT_TABLES) + len(_INDIRECT_TENANT_TABLES))


def disable_all_rls_policies() -> None:
    """Disable RLS on all tables.  Used for rollback migration."""
    all_tables = _TENANT_TABLES + list(_INDIRECT_TENANT_TABLES.keys())
    for table in all_tables:
        policy_name = f"tenant_isolation_{table}"
        try:
            db.session.execute(text(f"DROP POLICY IF EXISTS {policy_name} ON {table}"))
            db.session.execute(text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
        except Exception:
            pass  # Table may not exist in test environment
    db.session.commit()
