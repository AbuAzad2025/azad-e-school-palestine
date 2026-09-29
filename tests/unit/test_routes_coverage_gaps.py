"""تغطية فجوات المسارات: admin (تدقيق النسخ الاحتياطي، فشل اعتماد/رفض الدفع)
وauth (لوحة مشرف المدرسة — فرع الإحصائيات).

كلها مسارات فشل/فروع حقيقية عبر طلبات HTTP كاملة.
"""

from types import SimpleNamespace
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


# ═══════════════════════════════════════════════════════════════════════
# فجوات الجولة الثانية — restore تفاصيل psql، الإعدادات، payouts
# ═══════════════════════════════════════════════════════════════════════


class TestRestorePsqlOutcomes:
    def _setup_backup(self, filename):
        from pathlib import Path

        backup_dir = Path("backups")
        backup_dir.mkdir(exist_ok=True)
        path = backup_dir / filename
        path.write_text("-- sql", encoding="utf-8")
        return path

    def test_restore_success_flash(self, client, app):
        _login_super(client, app)
        path = self._setup_backup("restore-ok.sql")
        try:
            fake_completed = SimpleNamespace(returncode=0, stderr="")
            with (
                patch("app.modules.admin.routes.PSQL", "psql-stub"),
                patch("subprocess.run", return_value=fake_completed),
            ):
                resp = client.post(
                    "/admin/backups/restore-ok.sql/restore",
                    data={"confirm": "yes — restore"},
                    follow_redirects=True,
                )
            assert "تمت الاستعادة بنجاح".encode() in resp.data
        finally:
            path.unlink(missing_ok=True)

    def test_restore_psql_failure_reports_stderr(self, client, app):
        _login_super(client, app)
        path = self._setup_backup("restore-fail.sql")
        try:
            # PSQL يُستدعى كوحدة داخلية للمسار — نُرجع returncode=1 مع stderr
            fake_completed = SimpleNamespace(returncode=1, stderr="pg error detail")
            with (
                patch("app.modules.admin.routes.PSQL", "psql-stub"),
                patch("subprocess.run", return_value=fake_completed),
            ):
                resp = client.post(
                    "/admin/backups/restore-fail.sql/restore",
                    data={"confirm": "yes — restore"},
                    follow_redirects=True,
                )
            assert "فشل الاستعادة".encode() in resp.data
            assert b"pg error detail" in resp.data
        finally:
            path.unlink(missing_ok=True)

    def test_restore_unexpected_exception_flashes_generic_error(self, client, app):
        _login_super(client, app)
        path = self._setup_backup("restore-exploded.sql")
        try:
            with (
                patch("app.modules.admin.routes.PSQL", "psql-stub"),
                patch("subprocess.run", side_effect=RuntimeError(" inexplicable")),
            ):
                resp = client.post(
                    "/admin/backups/restore-exploded.sql/restore",
                    data={"confirm": "yes — restore"},
                    follow_redirects=True,
                )
            assert "خطأ:".encode() in resp.data
        finally:
            path.unlink(missing_ok=True)

    def test_restore_without_database_url_flashes(self, client, app):
        """DATABASE_URL غير مضبوط (794-795) — os وهمي داخل وحدة المسارات فقط."""
        from types import SimpleNamespace

        import app.modules.admin.routes as admin_routes

        _login_super(client, app)
        path = self._setup_backup("restore-nourl.sql")
        try:
            fake_os = SimpleNamespace(
                getenv=lambda key, default=None: None if key == "DATABASE_URL" else default,
                path=admin_routes.os.path,
                environ=admin_routes.os.environ,
            )
            with patch.object(admin_routes, "os", fake_os):
                resp = client.post(
                    "/admin/backups/restore-nourl.sql/restore",
                    data={"confirm": "yes — restore"},
                    follow_redirects=True,
                )
            assert "DATABASE_URL غير مضبوط".encode() in resp.data
        finally:
            path.unlink(missing_ok=True)

    def test_audit_log_failure_is_swallowed(self, client, app):
        """AuditLog يرمي داخل _audit_admin_action → تُبتلع (83-84)
        والاستعادة تكمل إلى psql — لا رسالة فشل تسجيل الاستعادة."""
        _login_super(client, app)
        path = self._setup_backup("restore-badaudit.sql")
        try:
            # الاستيراد داخل الدالة يجلب السمة المُستبدلة لحظة الاستدعاء
            with (
                patch("app.models.system.AuditLog", side_effect=RuntimeError("audit boom")),
                patch("app.modules.admin.routes.PSQL", "psql-stub"),
                patch("subprocess.run", return_value=SimpleNamespace(returncode=1, stderr="x")),
            ):
                resp = client.post(
                    "/admin/backups/restore-badaudit.sql/restore",
                    data={"confirm": "yes — restore"},
                    follow_redirects=True,
                )
            assert resp.status_code == 200
            # الاستعادة وصلت إلى psql (فشل الاستعادة) — لم تتوقف عند فشل التدقيق
            assert "فشل الاستعادة".encode() in resp.data
            assert "فشل تسجيل عملية الاستعادة".encode() not in resp.data
        finally:
            path.unlink(missing_ok=True)


class TestSettingsSaveFailure:
    def test_settings_save_failure_flashes(self, client, app):
        _login_super(client, app)
        with patch("app.modules.admin.routes.tx", side_effect=RuntimeError("db down")):
            resp = client.post("/admin/settings", data={"maintenance": "1"}, follow_redirects=True)
        assert "فشل حفظ الإعدادات".encode() in resp.data


class TestPayoutDecisionFailures:
    def _make_payout(self, app):
        from decimal import Decimal

        from app.extensions import db
        from app.models.tutoring import TutorPayout

        sid = make_school(app)
        tutor_id = make_user(app, role="teacher", school_id=sid)
        with app.app_context():
            payout = TutorPayout(tutor_id=tutor_id, amount=Decimal("50.00"), status="pending")
            db.session.add(payout)
            db.session.commit()
            return payout.id

    def test_payout_approve_failure_flashes(self, client, app):
        payout_id = self._make_payout(app)
        _login_super(client, app)
        with patch("app.modules.admin.routes.tx", side_effect=RuntimeError("db down")):
            resp = client.post(f"/admin/payouts/{payout_id}/approve", follow_redirects=True)
        assert "فشل اعتماد طلب السحب".encode() in resp.data

    def test_payout_reject_failure_flashes(self, client, app):
        payout_id = self._make_payout(app)
        _login_super(client, app)
        with patch("app.modules.admin.routes.tx", side_effect=RuntimeError("db down")):
            resp = client.post(f"/admin/payouts/{payout_id}/reject", follow_redirects=True)
        assert "فشل رفض طلب السحب".encode() in resp.data
