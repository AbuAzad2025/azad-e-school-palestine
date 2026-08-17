"""فحص تطابق النماذج مع الجداول الفعلية في PostgreSQL — يمنع انحراف المخطط"""
from sqlalchemy import inspect

from app import create_app
from app.extensions import db

EXPECTED_TABLES = {
    "users", "user_role_links", "schools", "school_settings", "grades",
    "subjects", "subject_grade_links", "classes", "class_members",
    "units", "lessons", "lesson_attachments", "quizzes", "questions",
    "quiz_attempts", "answers", "assignments", "submissions",
    "grade_categories", "grade_items", "grade_entries", "attendance",
    "subscription_plans", "subscriptions", "manual_payments",
    "payment_receipts", "announcements", "notifications",
    "ai_sessions", "ai_messages", "audit_logs", "settings",
    "tutor_profiles", "tutoring_requests", "tutoring_sessions",
}


def test_all_expected_tables_exist():
    app = create_app()
    with app.app_context():
        inspector = inspect(db.engine)
        actual = set(inspector.get_table_names())
        missing = EXPECTED_TABLES - actual
        assert not missing, f"جداول ناقصة في القاعدة: {missing}"


def test_foreign_keys_present():
    app = create_app()
    with app.app_context():
        inspector = inspect(db.engine)
        for table in ("class_members", "submissions", "answers", "grade_entries", "subscriptions"):
            fks = {fk["constrained_columns"][0] for fk in inspector.get_foreign_keys(table)}
            assert fks, f"{table} بدون علاقات FK"


def test_users_has_unique_email():
    app = create_app()
    with app.app_context():
        inspector = inspect(db.engine)
        uniques = inspector.get_unique_constraints("users")
        cols = {tuple(c["column_names"]) for c in uniques} | {
            tuple(i["column_names"]) for i in inspector.get_indexes("users") if i.get("unique")
        }
        assert ("email",) in cols, "users.email غير فريد"
