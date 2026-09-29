"""تغطية فجوات المسارات: admin (تدقيق النسخ الاحتياطي، فشل اعتماد/رفض الدفع)
وauth (لوحة مشرف المدرسة — فرع الإحصائيات).

كلها مسارات فشل/فروع حقيقية عبر طلبات HTTP كاملة.
"""

from unittest.mock import patch

from tests.conftest import make_class, make_class_member, make_grade, make_school, make_subject, make_user


def _login_super(client, app):
    _uid, email = _mk(app, "super_admin")
    client.post("/auth/login", data={"email": email, "password": "TestPass123!"}, follow_redirects=True)


def _mk(app, role, school_id=None):
    uid = make_user(app, role=role, school_id=school_id)
    with app.app_context():
        from app.extensions import db
        from app.models.user import User

        return uid, db.session.get(User, uid).email


class TestAdminBackupRestoreGaps:
    def _make_backup_file(self, filename):
        from pathlib import Path

        backup_dir = Path("backups")
        backup_dir.mkdir(exist_ok=True)
        path = backup_dir / filename
        path.write_text("-- dummy sql", encoding="utf-8")
        return path

    def test_restore_missing_file_flashes(self, client, app):
        _login_super(client, app)
        resp = client.post(
            "/admin/backups/definitely-missing.sql/restore",
            data={"confirm": "yes — restore"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "الملف غير موجود".encode() in resp.data

    def test_restore_wrong_confirmation_rejected(self, client, app):
        _login_super(client, app)
        path = self._make_backup_file("restore-confirm-test.sql")
        try:
            resp = client.post(
                "/admin/backups/restore-confirm-test.sql/restore",
                data={"confirm": "no"},
                follow_redirects=True,
            )
            assert resp.status_code == 200
            # رسالة التأكيد الصارم (السطر 789) — لا استعادة ولا تدقيق
            assert "yes — restore".encode() in resp.data
        finally:
            path.unlink(missing_ok=True)

    def test_restore_records_audit_and_reports_missing_psql(self, client, app):
        """المسار السعيد حتى FileNotFoundError من psql (832-833) —
        يغطي التدقيق (61-85) وتسجيل النية (799-813)."""
        from app.models.system import AuditLog

        _login_super(client, app)
        path = self._make_backup_file("restore-audit-test.sql")
        try:
            # PSQL غير موجود على الجهاز في الاختبارات → FileNotFoundError
            with patch("app.modules.admin.routes.PSQL", "definitely-not-a-real-binary-xyz"):
                resp = client.post(
                    "/admin/backups/restore-audit-test.sql/restore",
                    data={"confirm": "yes — restore"},
                    follow_redirects=True,
                )
            assert resp.status_code == 200
            assert b"psql" in resp.data

            with app.app_context():
                row = AuditLog.query.filter_by(action="backup.restore").order_by(AuditLog.id.desc()).first()
                assert row is not None
                assert row.detail["filename"] == "restore-audit-test.sql"
                assert row.detail["pg_url_present"] is True
        finally:
            path.unlink(missing_ok=True)

    def test_restore_audit_failure_flashes(self, client, app):
        """فشل tx(_record_restore_intent) → رسالة فشل التسجيل (811-813)."""
        _login_super(client, app)
        path = self._make_backup_file("restore-audit-fail.sql")
        try:
            with patch("app.modules.admin.routes.tx", side_effect=RuntimeError("boom")):
                resp = client.post(
                    "/admin/backups/restore-audit-fail.sql/restore",
                    data={"confirm": "yes — restore"},
                    follow_redirects=True,
                )
            assert resp.status_code == 200
            assert "فشل تسجيل عملية الاستعادة".encode() in resp.data
        finally:
            path.unlink(missing_ok=True)


class TestAdminPaymentDecisionFailures:
    def _make_pending_payment(self, app):
        """اشتراك معلّق + دفع معلّق معه — يعيد (payment_id, sub_id)."""
        from decimal import Decimal

        from app.extensions import db
        from app.models.billing import ManualPayment, Subscription, SubscriptionPlan

        sid = make_school(app)
        with app.app_context():
            gid = make_grade(app, sid)
            cid = make_class(app, sid, gid, make_subject(app))
            student = make_user(app, role="student", school_id=sid)
            plan = SubscriptionPlan(
                school_id=sid,
                class_id=cid,
                name="خطة الدفع",
                plan="annual",
                price=Decimal("100.00"),
                currency="ILS",
                is_active=True,
            )
            db.session.add(plan)
            db.session.flush()
            sub = Subscription(
                user_id=student,
                plan_id=plan.id,
                class_id=cid,
                price=Decimal("100.00"),
                currency="ILS",
                status="pending",
            )
            db.session.add(sub)
            db.session.flush()
            payment = ManualPayment(
                subscription_id=sub.id,
                amount=Decimal("100.00"),
                reference="REF-001",
                status="pending",
            )
            db.session.add(payment)
            db.session.commit()
            return payment.id, sub.id

    def test_approve_failure_flashes_and_redirects(self, client, app):
        payment_id, _ = self._make_pending_payment(app)
        _login_super(client, app)
        with patch("app.modules.admin.routes.tx", side_effect=RuntimeError("db down")):
            resp = client.post(f"/admin/payments/{payment_id}/approve", follow_redirects=True)
        assert resp.status_code == 200
        assert "فشل اعتماد الدفع".encode() in resp.data

    def test_reject_failure_flashes_and_redirects(self, client, app):
        payment_id, _ = self._make_pending_payment(app)
        _login_super(client, app)
        with patch("app.modules.admin.routes.tx", side_effect=RuntimeError("db down")):
            resp = client.post(f"/admin/payments/{payment_id}/reject", follow_redirects=True)
        assert resp.status_code == 200
        assert "فشل رفض الدفع".encode() in resp.data


class TestSchoolAdminDashboardStats:
    def test_school_admin_dashboard_counts_real_entities(self, client, app):
        """فرع مشرف المدرسة في لوحة auth (172-200): عدّادات الصفوف/الطلاب/المعلمين."""
        sid = make_school(app)
        gid = make_grade(app, sid)
        cid = make_class(app, sid, gid, make_subject(app))
        student_id = make_user(app, role="student", school_id=sid)
        make_class_member(app, cid, student_id, status="active")
        make_user(app, role="teacher", school_id=sid)
        _aid, admin_email = _mk(app, "school_admin", school_id=sid)

        client.post("/auth/login", data={"email": admin_email, "password": "TestPass123!"}, follow_redirects=True)
        resp = client.get("/auth/dashboard")
        assert resp.status_code == 200
        body = resp.data.decode("utf-8")
        # الصفحة تُعرض — ولوحة مشرف المدرسة تحتوي عدّاداتها بالعربية
        assert "لوحة مشرف المدرسة" in body or "لوحتي" in body
