"""P2: Denormalization — materialized paths, aggregates, computed columns

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-08-21

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade():
    # ============================================================
    # MATERIALIZED PATH: class ancestry for fast subtree queries
    # ============================================================

    op.add_column(
        "classes",
        sa.Column("class_path", sa.Text(), nullable=True, comment="Materialized path: /school_id/grade_id/subject_id/semester/")
    )
    op.execute("""
        UPDATE classes c
        SET class_path = '/' || c.school_id || '/' || c.grade_id || '/' || c.subject_id || '/' || COALESCE(c.semester, 'annual') || '/'
    """)
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.alter_column("classes", "class_path", nullable=False)
    op.create_index("idx_classes_path", "classes", ["class_path"], postgresql_using="gin", postgresql_ops={"class_path": "gin_trgm_ops"})

    # ============================================================
    # AGGREGATE COLUMNS — precomputed counts for dashboards
    # ============================================================

    # ensure schools/subscriptions have deleted_at (missed in P1)
    op.execute("ALTER TABLE schools ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ")
    op.execute("ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ")
    op.execute("CREATE INDEX IF NOT EXISTS idx_schools_active ON schools (id) WHERE deleted_at IS NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_active ON subscriptions (id) WHERE deleted_at IS NULL")

    # schools: active counts
    for col, sql in [
        ("active_students_count", "SELECT COUNT(*) FROM users u JOIN user_role_links url ON u.id = url.user_id WHERE url.school_id = schools.id AND url.is_active AND url.role = 'student' AND u.is_active AND u.deleted_at IS NULL"),
        ("active_teachers_count", "SELECT COUNT(*) FROM users u JOIN user_role_links url ON u.id = url.user_id WHERE url.school_id = schools.id AND url.is_active AND url.role = 'teacher' AND u.is_active AND u.deleted_at IS NULL"),
        ("active_classes_count", "SELECT COUNT(*) FROM classes WHERE school_id = schools.id AND is_active AND deleted_at IS NULL"),
        ("active_subscriptions_count", "SELECT COUNT(*) FROM subscriptions s JOIN classes c ON s.class_id = c.id WHERE c.school_id = schools.id AND s.status = 'active' AND s.deleted_at IS NULL AND c.deleted_at IS NULL"),
    ]:
        op.add_column("schools", sa.Column(col, sa.Integer(), nullable=False, server_default="0"))
        op.execute(f"UPDATE schools SET {col} = ({sql})")

    # classes: student/teacher counts
    for col, sql in [
        ("students_count", "SELECT COUNT(*) FROM class_members cm JOIN users u ON cm.user_id = u.id WHERE cm.class_id = classes.id AND cm.status = 'active' AND u.role = 'student' AND u.is_active AND u.deleted_at IS NULL AND cm.deleted_at IS NULL"),
        ("teachers_count", "SELECT COUNT(*) FROM class_members cm JOIN users u ON cm.user_id = u.id WHERE cm.class_id = classes.id AND cm.status = 'active' AND u.role = 'teacher' AND u.is_active AND u.deleted_at IS NULL AND cm.deleted_at IS NULL"),
        ("lessons_published_count", "SELECT COUNT(*) FROM lessons WHERE class_id = classes.id AND status = 'published' AND deleted_at IS NULL"),
        ("assignments_count", "SELECT COUNT(*) FROM assignments WHERE class_id = classes.id AND deleted_at IS NULL"),
        ("quizzes_published_count", "SELECT COUNT(*) FROM quizzes WHERE class_id = classes.id AND status = 'published' AND deleted_at IS NULL"),
    ]:
        op.add_column("classes", sa.Column(col, sa.Integer(), nullable=False, server_default="0"))
        op.execute(f"UPDATE classes SET {col} = ({sql})")

    # users: class/subscription counts
    for col, sql in [
        ("classes_as_student_count", "SELECT COUNT(*) FROM class_members WHERE user_id = users.id AND status = 'active' AND deleted_at IS NULL"),
        ("classes_as_teacher_count", "SELECT COUNT(*) FROM classes WHERE teacher_id = users.id AND is_active AND deleted_at IS NULL"),
        ("active_subscriptions_count", "SELECT COUNT(*) FROM subscriptions WHERE user_id = users.id AND status = 'active' AND deleted_at IS NULL"),
    ]:
        op.add_column("users", sa.Column(col, sa.Integer(), nullable=False, server_default="0"))
        op.execute(f"UPDATE users SET {col} = ({sql})")

    # quizzes: attempt/score stats
    for col, sql in [
        ("attempts_count", "SELECT COUNT(*) FROM quiz_attempts WHERE quiz_id = quizzes.id AND deleted_at IS NULL"),
        ("avg_score", "SELECT AVG(score) FROM quiz_attempts WHERE quiz_id = quizzes.id AND score IS NOT NULL AND status = 'graded' AND deleted_at IS NULL"),
        ("pass_rate", "SELECT COUNT(*) FILTER (WHERE score >= total_mark * 0.6) * 100.0 / NULLIF(COUNT(*), 0) FROM quiz_attempts WHERE quiz_id = quizzes.id AND score IS NOT NULL AND status = 'graded' AND deleted_at IS NULL"),
    ]:
        if col == "avg_score":
            op.add_column("quizzes", sa.Column(col, sa.Numeric(6, 2), nullable=True))
        elif col == "pass_rate":
            op.add_column("quizzes", sa.Column(col, sa.Numeric(5, 2), nullable=True))
        else:
            op.add_column("quizzes", sa.Column(col, sa.Integer(), nullable=False, server_default="0"))
        op.execute(f"UPDATE quizzes SET {col} = ({sql})")

    # subscriptions: payment stats
    for col, sql in [
        ("payments_count", "SELECT COUNT(*) FROM manual_payments WHERE subscription_id = subscriptions.id AND deleted_at IS NULL"),
        ("total_paid", "SELECT COALESCE(SUM(amount), 0) FROM manual_payments WHERE subscription_id = subscriptions.id AND status = 'approved' AND deleted_at IS NULL"),
        ("pending_amount", "SELECT COALESCE(SUM(amount), 0) FROM manual_payments WHERE subscription_id = subscriptions.id AND status = 'pending' AND deleted_at IS NULL"),
    ]:
        if col in ("total_paid", "pending_amount"):
            op.add_column("subscriptions", sa.Column(col, sa.Numeric(10, 2), nullable=False, server_default="0"))
        else:
            op.add_column("subscriptions", sa.Column(col, sa.Integer(), nullable=False, server_default="0"))
        op.execute(f"UPDATE subscriptions SET {col} = ({sql})")

    # ============================================================
    # TRIGGERS to maintain aggregates (using pg_trigger)
    # ============================================================

    # schools aggregate maintenance
    op.execute("""
        CREATE OR REPLACE FUNCTION update_school_aggregates()
        RETURNS TRIGGER AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                UPDATE schools SET
                    active_students_count = active_students_count + CASE WHEN NEW.role = 'student' AND NEW.is_active THEN 1 ELSE 0 END,
                    active_teachers_count = active_teachers_count + CASE WHEN NEW.role = 'teacher' AND NEW.is_active THEN 1 ELSE 0 END
                WHERE id = NEW.school_id;
            ELSIF TG_OP = 'UPDATE' THEN
                UPDATE schools SET
                    active_students_count = active_students_count +
                        CASE WHEN NEW.role = 'student' AND NEW.is_active THEN 1 ELSE 0 END -
                        CASE WHEN OLD.role = 'student' AND OLD.is_active THEN 1 ELSE 0 END,
                    active_teachers_count = active_teachers_count +
                        CASE WHEN NEW.role = 'teacher' AND NEW.is_active THEN 1 ELSE 0 END -
                        CASE WHEN OLD.role = 'teacher' AND OLD.is_active THEN 1 ELSE 0 END
                WHERE id = COALESCE(NEW.school_id, OLD.school_id);
            ELSIF TG_OP = 'DELETE' THEN
                UPDATE schools SET
                    active_students_count = active_students_count - CASE WHEN OLD.role = 'student' AND OLD.is_active THEN 1 ELSE 0 END,
                    active_teachers_count = active_teachers_count - CASE WHEN OLD.role = 'teacher' AND OLD.is_active THEN 1 ELSE 0 END
                WHERE id = OLD.school_id;
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        DROP TRIGGER IF EXISTS trg_user_role_link_school_agg ON user_role_links;
        CREATE TRIGGER trg_user_role_link_school_agg
        AFTER INSERT OR UPDATE OR DELETE ON user_role_links
        FOR EACH ROW EXECUTE FUNCTION update_school_aggregates();
    """)

    # classes aggregate maintenance (students/teachers via class_members handled app-side; trigger only for lessons/assignments/quizzes)
    op.execute("""
        CREATE OR REPLACE FUNCTION update_class_aggregates()
        RETURNS TRIGGER AS $$
        DECLARE
            cid BIGINT;
        BEGIN
            IF TG_TABLE_NAME = 'lessons' THEN
                cid := COALESCE(NEW.class_id, OLD.class_id);
                UPDATE classes SET
                    lessons_published_count = lessons_published_count +
                        CASE WHEN NEW.status = 'published' THEN 1 ELSE 0 END -
                        CASE WHEN OLD.status = 'published' THEN 1 ELSE 0 END
                WHERE id = cid;
            ELSIF TG_TABLE_NAME = 'assignments' THEN
                cid := COALESCE(NEW.class_id, OLD.class_id);
                UPDATE classes SET
                    assignments_count = assignments_count +
                        CASE WHEN TG_OP = 'INSERT' THEN 1 WHEN TG_OP = 'DELETE' THEN -1 ELSE 0 END
                WHERE id = cid;
            ELSIF TG_TABLE_NAME = 'quizzes' THEN
                cid := COALESCE(NEW.class_id, OLD.class_id);
                UPDATE classes SET
                    quizzes_published_count = quizzes_published_count +
                        CASE WHEN NEW.status = 'published' THEN 1 ELSE 0 END -
                        CASE WHEN OLD.status = 'published' THEN 1 ELSE 0 END
                WHERE id = cid;
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
    """)

    for tbl in ('lessons', 'assignments', 'quizzes'):
        op.execute(f"""
            DROP TRIGGER IF EXISTS trg_{tbl}_class_agg ON {tbl};
            CREATE TRIGGER trg_{tbl}_class_agg
            AFTER INSERT OR UPDATE OR DELETE ON {tbl}
            FOR EACH ROW EXECUTE FUNCTION update_class_aggregates();
        """)

    # quiz stats maintenance
    op.execute("""
        CREATE OR REPLACE FUNCTION update_quiz_stats()
        RETURNS TRIGGER AS $$
        BEGIN
            IF TG_TABLE_NAME = 'quiz_attempts' THEN
                UPDATE quizzes SET
                    attempts_count = (
                        SELECT COUNT(*) FROM quiz_attempts WHERE quiz_id = COALESCE(NEW.quiz_id, OLD.quiz_id) AND deleted_at IS NULL
                    ),
                    avg_score = (
                        SELECT AVG(score) FROM quiz_attempts
                        WHERE quiz_id = COALESCE(NEW.quiz_id, OLD.quiz_id)
                          AND score IS NOT NULL AND status = 'graded' AND deleted_at IS NULL
                    ),
                    pass_rate = (
                        SELECT COUNT(*) FILTER (WHERE score >= q.total_mark * 0.6) * 100.0 / NULLIF(COUNT(*), 0)
                        FROM quiz_attempts qa
                        JOIN quizzes q ON qa.quiz_id = q.id
                        WHERE qa.quiz_id = COALESCE(NEW.quiz_id, OLD.quiz_id)
                          AND qa.score IS NOT NULL AND qa.status = 'graded' AND qa.deleted_at IS NULL
                    )
                WHERE id = COALESCE(NEW.quiz_id, OLD.quiz_id);
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        DROP TRIGGER IF EXISTS trg_quiz_attempts_stats ON quiz_attempts;
        CREATE TRIGGER trg_quiz_attempts_stats
        AFTER INSERT OR UPDATE OR DELETE ON quiz_attempts
        FOR EACH ROW EXECUTE FUNCTION update_quiz_stats();
    """)

    # subscription payment stats
    op.execute("""
        CREATE OR REPLACE FUNCTION update_subscription_payment_stats()
        RETURNS TRIGGER AS $$
        BEGIN
            UPDATE subscriptions SET
                payments_count = (
                    SELECT COUNT(*) FROM manual_payments WHERE subscription_id = COALESCE(NEW.subscription_id, OLD.subscription_id) AND deleted_at IS NULL
                ),
                total_paid = (
                    SELECT COALESCE(SUM(amount), 0) FROM manual_payments
                    WHERE subscription_id = COALESCE(NEW.subscription_id, OLD.subscription_id)
                      AND status = 'approved' AND deleted_at IS NULL
                ),
                pending_amount = (
                    SELECT COALESCE(SUM(amount), 0) FROM manual_payments
                    WHERE subscription_id = COALESCE(NEW.subscription_id, OLD.subscription_id)
                      AND status = 'pending' AND deleted_at IS NULL
                )
            WHERE id = COALESCE(NEW.subscription_id, OLD.subscription_id);
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        DROP TRIGGER IF EXISTS trg_manual_payments_sub_stats ON manual_payments;
        CREATE TRIGGER trg_manual_payments_sub_stats
        AFTER INSERT OR UPDATE OR DELETE ON manual_payments
        FOR EACH ROW EXECUTE FUNCTION update_subscription_payment_stats();
    """)

    # ============================================================
    # INDEXES for aggregate columns
    # ============================================================

    op.create_index("idx_schools_active_students", "schools", ["active_students_count"])
    op.create_index("idx_classes_students", "classes", ["students_count"])
    op.create_index("idx_users_classes_student", "users", ["classes_as_student_count"])
    op.create_index("idx_quizzes_avg_score", "quizzes", ["avg_score"])
    op.create_index("idx_subscriptions_total_paid", "subscriptions", ["total_paid"])

    # ============================================================
    # MATERIALIZED VIEW for admin dashboard (refreshed via cron)
    # ============================================================

    op.execute("""
        CREATE MATERIALIZED VIEW mv_admin_dashboard AS
        SELECT
            s.id AS school_id,
            s.name_ar AS school_name,
            s.active_students_count,
            s.active_teachers_count,
            s.active_classes_count,
            s.active_subscriptions_count,
            COUNT(DISTINCT c.id) FILTER (WHERE c.is_active) AS live_classes,
            COUNT(DISTINCT l.id) FILTER (WHERE l.status = 'published') AS published_lessons,
            COUNT(DISTINCT q.id) FILTER (WHERE q.status = 'published') AS published_quizzes,
            COUNT(DISTINCT sub.id) FILTER (WHERE sub.status = 'active') AS active_subs,
            COALESCE(SUM(mp.amount) FILTER (WHERE mp.status = 'approved'), 0) AS total_revenue
        FROM schools s
        LEFT JOIN classes c ON c.school_id = s.id AND c.deleted_at IS NULL
        LEFT JOIN lessons l ON l.class_id = c.id AND l.deleted_at IS NULL
        LEFT JOIN quizzes q ON q.class_id = c.id AND q.deleted_at IS NULL
        LEFT JOIN subscriptions sub ON sub.class_id = c.id AND sub.deleted_at IS NULL
        LEFT JOIN manual_payments mp ON mp.subscription_id = sub.id AND mp.deleted_at IS NULL
        WHERE s.deleted_at IS NULL
        GROUP BY s.id, s.name_ar, s.active_students_count, s.active_teachers_count, s.active_classes_count, s.active_subscriptions_count
    """)

    op.execute("CREATE UNIQUE INDEX ON mv_admin_dashboard (school_id)")

    # Refresh function
    op.execute("""
        CREATE OR REPLACE FUNCTION refresh_admin_dashboard()
        RETURNS VOID AS $$
        BEGIN
            REFRESH MATERIALIZED VIEW CONCURRENTLY mv_admin_dashboard;
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade():
    # Drop triggers
    op.execute("DROP TRIGGER IF EXISTS trg_user_role_link_school_agg ON user_role_links")
    op.execute("DROP TRIGGER IF EXISTS trg_class_members_class_agg ON class_members")
    op.execute("DROP TRIGGER IF EXISTS trg_lessons_class_agg ON lessons")
    op.execute("DROP TRIGGER IF EXISTS trg_assignments_class_agg ON assignments")
    op.execute("DROP TRIGGER IF EXISTS trg_quizzes_class_agg ON quizzes")
    op.execute("DROP TRIGGER IF EXISTS trg_quiz_attempts_stats ON quiz_attempts")
    op.execute("DROP TRIGGER IF EXISTS trg_manual_payments_sub_stats ON manual_payments")

    # Drop functions
    op.execute("DROP FUNCTION IF EXISTS update_school_aggregates()")
    op.execute("DROP FUNCTION IF EXISTS update_class_aggregates()")
    op.execute("DROP FUNCTION IF EXISTS update_quiz_stats()")
    op.execute("DROP FUNCTION IF EXISTS update_subscription_payment_stats()")
    op.execute("DROP FUNCTION IF EXISTS refresh_admin_dashboard()")

    # Drop materialized view
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_admin_dashboard")

    # Drop aggregate columns
    for tbl, cols in [
        ("schools", ["active_students_count", "active_teachers_count", "active_classes_count", "active_subscriptions_count"]),
        ("classes", ["students_count", "teachers_count", "lessons_published_count", "assignments_count", "quizzes_published_count", "class_path"]),
        ("users", ["classes_as_student_count", "classes_as_teacher_count", "active_subscriptions_count"]),
        ("quizzes", ["attempts_count", "avg_score", "pass_rate"]),
        ("subscriptions", ["payments_count", "total_paid", "pending_amount"]),
    ]:
        for col in cols:
            op.drop_column(tbl, col)

    # Drop indexes
    for idx in [
        "idx_schools_active_students", "idx_classes_students", "idx_users_classes_student",
        "idx_quizzes_avg_score", "idx_subscriptions_total_paid", "idx_classes_path",
    ]:
        op.execute(f"DROP INDEX IF EXISTS {idx}")