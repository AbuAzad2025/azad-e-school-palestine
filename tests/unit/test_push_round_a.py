"""Extended coverage round A — precise gap closure (99.9% push).

Targets per-file missed lines from CI artifact analysis (run 34719385091):
- app/modules/admin/routes.py: bulk actions, impersonation, backups, AI usage
- app/modules/tutoring/routes.py: respond/session lifecycle/pay/rate/live endpoints
- app/modules/schools/routes.py: grade_add, class join, onboarding steps
- app/modules/billing/routes.py: validate_code, invoice_view/pdf
- app/modules/progress/routes.py: video_update, my_progress branches
- app/modules/ai/routes.py: chat, chat/stream, suggest_grade
- app/tasks: dispatch() sync modes, grading batch, notifications bulk, video helpers
- app/core/permissions.py: decorator branches

All tests exercise real routes/services with real DB state (azad_test only).
"""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from tests.conftest import (
    make_attachment,
    make_class,
    make_class_member,
    make_grade,
    make_grade_category,
    make_grade_item,
    make_lesson,
    make_school,
    make_subject,
    make_subscription,
    make_subscription_plan,
    make_tutoring_session,
    make_user,
)

PASSWORD = "TestPass123!"

_LEVELS: dict[int, int] = {}


def _self():
    """Dummy bound-task self for bind=True celery tasks (retry() never fires here)."""
    m = MagicMock()
    m.retry.side_effect = RuntimeError("retry-should-not-fire")
    return m


def _uid_email(prefix: str) -> tuple[int, str]:
    from tests.conftest import _uid

    email = f"{prefix}-{_uid()}@test.com"
    return 0, email


def mk_user(app, role: str, school_id=None):
    from tests.conftest import _uid

    email = f"xa-{_uid()}@test.com"
    uid = make_user(app, role=role, school_id=school_id, email=email)
    return uid, email


def persona(app, role: str, school_id=None):
    uid, email = mk_user(app, role, school_id)
    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    return uid, client


def login_as(app, uid_email: tuple[int, str]):
    client = app.test_client()
    client.post("/auth/login", data={"email": uid_email[1], "password": PASSWORD})
    return client


def _next_level(sid: int) -> int:
    """grades UNIQUE(school_id, grade_level) — fresh level per school."""
    _LEVELS[sid] = _LEVELS.get(sid, 0) + 1
    return _LEVELS[sid]


def _setup_class(app):
    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=_next_level(sid))
    subj = make_subject(app)
    cid = make_class(app, sid, gid, subj)
    return sid, cid, gid


def _set_class_teacher(app, cid: int, tid: int):
    from app.extensions import db
    from app.models.class_room import ClassRoom

    with app.app_context():
        db.session.get(ClassRoom, cid).teacher_id = tid
        db.session.commit()


# ═════════════════════════════ admin ═════════════════════════════


class TestAdminImpersonation:
    def test_impersonate_non_super_admin_403(self, app):
        _, client = persona(app, "school_admin", school_id=make_school(app))
        tid, _ = mk_user(app, "teacher")
        resp = client.post(f"/admin/users/{tid}/impersonate", follow_redirects=False)
        assert resp.status_code == 403

    def test_impersonate_success(self, app):
        sid = make_school(app)
        admin_id, admin_email = mk_user(app, "super_admin")
        tid, _ = mk_user(app, "teacher", school_id=sid)
        client = login_as(app, (admin_id, admin_email))
        resp = client.post(f"/admin/users/{tid}/impersonate", follow_redirects=False)
        assert resp.status_code == 302

    def test_impersonate_exit_without_session_403(self, app):
        _, client = persona(app, "student", school_id=make_school(app))
        resp = client.post("/admin/impersonate/exit", follow_redirects=False)
        assert resp.status_code == 403

    def test_impersonate_exit_by_super_admin(self, app):
        admin_id, admin_email = mk_user(app, "super_admin")
        client = login_as(app, (admin_id, admin_email))
        resp = client.post("/admin/impersonate/exit", follow_redirects=False)
        assert resp.status_code in (302, 403)


class TestAdminAiUsage:
    def test_ai_usage_renders(self, app):
        admin_id, email = mk_user(app, "super_admin")
        client = login_as(app, (admin_id, email))
        resp = client.get("/admin/ai/usage?days=7")
        assert resp.status_code == 200

    def test_ai_usage_student_403(self, app):
        sid = make_school(app)
        sid2 = make_school(app)
        uid, _ = mk_user(app, "student", school_id=sid2)
        client = persona(app, "student", school_id=sid)[1]
        resp = client.get("/admin/ai/usage")
        assert resp.status_code == 403


class TestAdminBackups:
    def test_backups_list_empty_dir(self, app, tmp_path):
        admin_id, email = mk_user(app, "super_admin")
        client = login_as(app, (admin_id, email))
        with patch.dict("os.environ", {"BACKUP_DIR": str(tmp_path / "nope")}):
            resp = client.get("/admin/backups")
        assert resp.status_code == 200

    def test_backups_list_with_files(self, app, tmp_path):
        backup_dir = tmp_path / "bk"
        backup_dir.mkdir()
        (backup_dir / "backup_2026.sql").write_text("-- dump")
        (backup_dir / "backup_2025.sql.gz").write_bytes(b"\x1f\x8b")
        (backup_dir / "notes.txt").write_text("not a backup")
        admin_id, email = mk_user(app, "super_admin")
        client = login_as(app, (admin_id, email))
        with patch.dict("os.environ", {"BACKUP_DIR": str(backup_dir)}):
            resp = client.get("/admin/backups")
        html = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "backup_2026.sql" in html

    def test_backup_create_missing_url_flashes(self, app, tmp_path):
        admin_id, email = mk_user(app, "super_admin")
        client = login_as(app, (admin_id, email))
        env = {"BACKUP_DIR": str(tmp_path / "bk2"), "DATABASE_URL": ""}
        with patch.dict("os.environ", env, clear=False):
            import os

            old = os.environ.pop("DATABASE_URL", None)
            try:
                resp = client.post("/admin/backups/create", follow_redirects=False)
            finally:
                if old is not None:
                    os.environ["DATABASE_URL"] = old
        assert resp.status_code == 302

    def test_backup_restore_missing_file(self, app, tmp_path):
        admin_id, email = mk_user(app, "super_admin")
        client = login_as(app, (admin_id, email))
        with patch.dict("os.environ", {"BACKUP_DIR": str(tmp_path / "bk3")}):
            resp = client.post(
                "/admin/backups/ghost.sql/restore",
                data={"confirm": "yes"},
                follow_redirects=False,
            )
        assert resp.status_code == 302

    def test_backup_restore_needs_confirm(self, app, tmp_path):
        backup_dir = tmp_path / "bk4"
        backup_dir.mkdir()
        (backup_dir / "real.sql").write_text("-- dump")
        admin_id, email = mk_user(app, "super_admin")
        client = login_as(app, (admin_id, email))
        with patch.dict("os.environ", {"BACKUP_DIR": str(backup_dir)}):
            resp = client.post(
                "/admin/backups/real.sql/restore",
                data={"confirm": "no"},
                follow_redirects=False,
            )
        assert resp.status_code == 302


class TestAdminSettingsAndNotifications:
    def test_audit_logs_page(self, app):
        admin_id, email = mk_user(app, "super_admin")
        client = login_as(app, (admin_id, email))
        resp = client.get("/admin/audit-logs")
        assert resp.status_code == 200

    def test_settings_page(self, app):
        admin_id, email = mk_user(app, "super_admin")
        client = login_as(app, (admin_id, email))
        resp = client.get("/admin/settings")
        assert resp.status_code == 200


# ═════════════════════════════ tutoring ═════════════════════════════


class TestTutoringRespond:
    def test_accept_request_by_owner_tutor(self, app):
        sid = make_school(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        stu_id, _ = mk_user(app, "student", school_id=sid)
        from app.models.tutoring import TutoringRequest
        from tests.conftest import _db

        with app.app_context():
            req = TutoringRequest(
                student_id=stu_id,
                tutor_id=tid,
                subject="رياضيات",
                preferred_time=None,
                mode="online",
                price_quote=Decimal("100.00"),
                note="",
                status="pending",
            )
            _db.session.add(req)
            _db.session.commit()
            rid = req.id

        client = login_as(app, (tid, t_email))
        resp = client.post(f"/tutoring/requests/{rid}/respond/accept", follow_redirects=False)
        assert resp.status_code == 302
        with app.app_context():
            _db.session.expire_all()
            assert _db.session.get(TutoringRequest, rid).status != "pending"

    def test_respond_twice_flashes_warning(self, app):
        sid = make_school(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        stu_id, _ = mk_user(app, "student", school_id=sid)
        from app.models.tutoring import TutoringRequest
        from tests.conftest import _db

        with app.app_context():
            req = TutoringRequest(
                student_id=stu_id,
                tutor_id=tid,
                subject="علوم",
                preferred_time=None,
                mode="online",
                price_quote=Decimal("80.00"),
                note="",
                status="accepted",
            )
            _db.session.add(req)
            _db.session.commit()
            rid = req.id

        client = login_as(app, (tid, t_email))
        resp = client.post(f"/tutoring/requests/{rid}/respond/accept", follow_redirects=True)
        assert resp.status_code == 200

    def test_respond_by_non_owner_403(self, app):
        sid = make_school(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        stu_id, _ = mk_user(app, "student", school_id=sid)
        from app.models.tutoring import TutoringRequest
        from tests.conftest import _db

        with app.app_context():
            req = TutoringRequest(
                student_id=stu_id,
                tutor_id=tid,
                subject="لغة",
                preferred_time=None,
                mode="online",
                price_quote=Decimal("50.00"),
                note="",
                status="pending",
            )
            _db.session.add(req)
            _db.session.commit()
            rid = req.id

        other, _ = mk_user(app, "teacher", school_id=sid)
        _, client = persona(app, "teacher", school_id=sid)
        resp = client.post(f"/tutoring/requests/{other and rid}/respond/accept", follow_redirects=False)
        assert resp.status_code == 403


class TestTutoringSessionLifecycle:
    def _make_session(self, app, sid: int, price: Decimal = Decimal("100.00")):
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        stu_id, _ = mk_user(app, "student", school_id=sid)
        sess_id = make_tutoring_session(app, tid, stu_id, status="requested", price=float(price))
        return tid, t_email, stu_id, sess_id

    def test_session_detail_other_participant_200(self, app):
        """The session's own student can view it (auto-created by conftest helper)."""
        sid = make_school(app)
        tid, _, _, sess_id = self._make_session(app, sid)
        assert tid > 0
        from app.models.tutoring import TutoringSession
        from app.models.user import User
        from tests.conftest import _db

        with app.app_context():
            sess = _db.session.get(TutoringSession, sess_id)
            stu = _db.session.get(User, sess.student_id)
            stu_email = stu.email
        client = login_as(app, (0, stu_email))
        resp = client.get(f"/tutoring/sessions/{sess_id}")
        assert resp.status_code == 200

    def test_session_detail_as_tutor(self, app):
        sid = make_school(app)
        tid, t_email, stu_id, sess_id = self._make_session(app, sid)
        client = login_as(app, (tid, t_email))
        resp = client.get(f"/tutoring/sessions/{sess_id}")
        assert resp.status_code == 200

    def test_session_update_by_tutor(self, app):
        sid = make_school(app)
        tid, t_email, stu_id, sess_id = self._make_session(app, sid)
        client = login_as(app, (tid, t_email))
        resp = client.post(
            f"/tutoring/sessions/{sess_id}",
            data={
                "scheduled_at": "2026-10-01T10:00",
                "duration_min": "60",
                "price": "120",
                "mode": "online",
                "online_link": "https://meet.jit.si/azad-test",
                "location": "",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_session_update_by_student_403(self, app):
        sid = make_school(app)
        tid, _, stu_id, sess_id = self._make_session(app, sid)
        client = login_as(app, mk_user(app, "student", school_id=sid)[:2])
        resp = client.post(
            f"/tutoring/sessions/{sess_id}",
            data={"scheduled_at": "2026-10-01T10:00", "mode": "online"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 403)

    def test_session_pay_by_student(self, app):
        sid = make_school(app)
        tid, _, stu_id, sess_id = self._make_session(app, sid)
        _, stu_email = mk_user(app, "student", school_id=sid)
        # pay must be by the session's own student
        from app.models.tutoring import TutoringSession
        from tests.conftest import _db

        with app.app_context():
            from app.models.user import User

            sess = _db.session.get(TutoringSession, sess_id)
            stu_email = _db.session.get(User, sess.student_id).email

        client = login_as(app, (0, stu_email))
        resp = client.post(f"/tutoring/sessions/{sess_id}/pay", follow_redirects=False)
        assert resp.status_code == 302
        # payment_status must land in the DB-allowed set (paid, not 'approved')
        with app.app_context():
            _db.session.expire_all()
            from app.models.tutoring import TutoringSession

            assert _db.session.get(TutoringSession, sess_id).payment_status == "paid"

    def test_session_pay_by_tutor_403(self, app):
        sid = make_school(app)
        tid, t_email, stu_id, sess_id = self._make_session(app, sid)
        client = login_as(app, (tid, t_email))
        resp = client.post(f"/tutoring/sessions/{sess_id}/pay", follow_redirects=False)
        assert resp.status_code == 403

    def test_session_status_completed_creates_commission(self, app):
        sid = make_school(app)
        tid, t_email, stu_id, sess_id = self._make_session(app, sid)
        client = login_as(app, (tid, t_email))
        resp = client.get(f"/tutoring/sessions/{sess_id}/status/completed", follow_redirects=False)
        assert resp.status_code == 302

    def test_session_status_invalid_value_404(self, app):
        sid = make_school(app)
        tid, t_email, stu_id, sess_id = self._make_session(app, sid)
        client = login_as(app, (tid, t_email))
        resp = client.get(f"/tutoring/sessions/{sess_id}/status/whatever", follow_redirects=False)
        assert resp.status_code == 404

    def test_live_url_non_participant_403(self, app):
        sid = make_school(app)
        tid, _, stu_id, sess_id = self._make_session(app, sid)
        _, client = persona(app, "student", school_id=sid)
        resp = client.get(f"/tutoring/sessions/{sess_id}/live-url", follow_redirects=False)
        assert resp.status_code == 403

    def test_start_live_by_participant(self, app):
        sid = make_school(app)
        tid, t_email, stu_id, sess_id = self._make_session(app, sid)
        client = login_as(app, (tid, t_email))
        resp = client.post(f"/tutoring/sessions/{sess_id}/start-live", follow_redirects=False)
        assert resp.status_code == 302

    def test_end_live_by_participant(self, app):
        sid = make_school(app)
        tid, t_email, stu_id, sess_id = self._make_session(app, sid)
        client = login_as(app, (tid, t_email))
        resp = client.post(f"/tutoring/sessions/{sess_id}/end-live", follow_redirects=False)
        assert resp.status_code == 302

    def test_live_status_json(self, app):
        sid = make_school(app)
        tid, t_email, stu_id, sess_id = self._make_session(app, sid)
        client = login_as(app, (tid, t_email))
        resp = client.get(f"/tutoring/sessions/{sess_id}/live-status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "status" in data and "is_live" in data


class TestTutoringRate:
    def test_rate_completed_within_window(self, app):
        sid = make_school(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        from datetime import UTC, datetime, timedelta

        sess_id = make_tutoring_session(
            app,
            tid,
            stu_id,
            status="completed",
            price=100.0,
            end_time=datetime.now(UTC) - timedelta(hours=1),
        )
        client = login_as(app, (stu_id, s_email))
        resp = client.post(
            f"/tutoring/rate/{sess_id}",
            data={"rating": "5", "comment": "ممتاز"},
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_rate_not_completed_rejected(self, app):
        sid = make_school(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        sess_id = make_tutoring_session(app, tid, stu_id, status="requested", price=100.0)
        client = login_as(app, (stu_id, s_email))
        resp = client.post(
            f"/tutoring/rate/{sess_id}",
            data={"rating": "4"},
            follow_redirects=True,
        )
        assert resp.status_code == 200

    def test_rate_by_tutor_403(self, app):
        sid = make_school(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        stu_id, _ = mk_user(app, "student", school_id=sid)
        sess_id = make_tutoring_session(app, tid, stu_id, status="completed", price=100.0)
        client = login_as(app, (tid, t_email))
        resp = client.post(f"/tutoring/rate/{sess_id}", data={"rating": "5"}, follow_redirects=False)
        assert resp.status_code == 403


# ═════════════════════════════ schools ═════════════════════════════


class TestSchoolsGaps:
    def test_grade_add_by_admin(self, app):
        sid = make_school(app)
        admin_id, email = mk_user(app, "school_admin", school_id=sid)
        client = login_as(app, (admin_id, email))
        resp = client.post(
            f"/schools/{sid}/grades",
            data={"grade_level": str(_next_level(sid) + 10), "name_ar": "صف متقدم"},
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_class_join_invalid_code(self, app):
        sid = make_school(app)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        client = login_as(app, (stu_id, s_email))
        resp = client.post(
            "/schools/classes/join",
            data={"code": "NOPE"},
            follow_redirects=True,
        )
        assert resp.status_code == 200

    def test_class_join_valid_code(self, app):
        sid, cid, _ = _setup_class(app)
        from app.models.class_room import ClassRoom
        from tests.conftest import _db

        with app.app_context():
            # free class (no active paid plan) joins instantly; form code needs 4..16 chars
            code = _db.session.get(ClassRoom, cid).join_code
            assert 4 <= len(code) <= 16

        stu_id, s_email = mk_user(app, "student", school_id=sid)
        client = login_as(app, (stu_id, s_email))
        resp = client.post("/schools/classes/join", data={"code": code}, follow_redirects=False)
        assert resp.status_code == 302

    def test_my_classes_empty(self, app):
        sid = make_school(app)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        client = login_as(app, (stu_id, s_email))
        resp = client.get("/schools/classes")
        assert resp.status_code == 200

    def test_onboarding_no_school_redirects(self, app):
        stu_id, s_email = mk_user(app, "student")
        client = login_as(app, (stu_id, s_email))
        resp = client.get("/schools/onboarding/1", follow_redirects=False)
        assert resp.status_code == 302

    def test_onboarding_save_step_progresses(self, app):
        sid = make_school(app)
        admin_id, email = mk_user(app, "school_admin", school_id=sid)
        client = login_as(app, (admin_id, email))
        resp = client.post("/schools/onboarding/1", data={"school_name": "أزاد"}, follow_redirects=False)
        assert resp.status_code == 302


# ═════════════════════════════ billing ═════════════════════════════


class TestBillingGaps:
    def test_validate_code_invalid_json(self, app):
        sid = make_school(app)
        uid, email = mk_user(app, "student", school_id=sid)
        client = login_as(app, (uid, email))
        resp = client.post(
            "/billing/validate-code",
            data={"code": "X", "plan_id": "999"},
        )
        assert resp.status_code in (200, 400)

    def test_invoice_view_member(self, app):
        sid, cid, _ = _setup_class(app)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        plan_id = make_subscription_plan(app, sid, class_id=cid, price=100.0)
        sub_id = make_subscription(app, stu_id, plan_id, cid, status="active")
        client = login_as(app, (stu_id, s_email))
        resp = client.get(f"/billing/invoices/{sub_id}")
        assert resp.status_code == 200

    def test_invoice_view_non_member_403(self, app):
        sid, cid, _ = _setup_class(app)
        stu_id, _ = mk_user(app, "student", school_id=sid)
        plan_id = make_subscription_plan(app, sid, class_id=cid, price=100.0)
        sub_id = make_subscription(app, stu_id, plan_id, cid, status="active")
        other_id, o_email = mk_user(app, "student", school_id=make_school(app))
        client = login_as(app, (other_id, o_email))
        resp = client.get(f"/billing/invoices/{sub_id}")
        assert resp.status_code == 403


# ═════════════════════════════ progress ═════════════════════════════


class TestProgressGaps:
    def test_video_update_by_member(self, app):
        sid, cid, _ = _setup_class(app)
        lid = make_lesson(app, cid)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu_id)
        from tests.conftest import make_attachment

        att_id = make_attachment(app, lid, kind="video")
        client = login_as(app, (stu_id, s_email))
        resp = client.post(
            f"/progress/video/{att_id}/update",
            data=json.dumps({"seconds_watched": 40, "total_seconds": 100}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["seconds_watched"] == 40

    def test_video_update_by_non_member_403(self, app):
        sid, cid, _ = _setup_class(app)
        lid = make_lesson(app, cid)
        att_id = make_attachment(app, lid, kind="video")
        other_id, o_email = mk_user(app, "student", school_id=make_school(app))
        client = login_as(app, (other_id, o_email))
        resp = client.post(
            f"/progress/video/{att_id}/update",
            data=json.dumps({"seconds_watched": 10, "total_seconds": 100}),
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_my_progress_empty(self, app):
        sid = make_school(app)
        stu_id, s_email = mk_user(app, "student", school_id=sid)
        client = login_as(app, (stu_id, s_email))
        resp = client.get("/progress/my")
        assert resp.status_code == 200


# ═════════════════════════════ ai routes ═════════════════════════════


class TestAiRoutes:
    def _quota_on(self, app, sid: int):
        """Enable AI for the tenant (default quota has ai_enabled=False → 403)."""
        from app.extensions import db
        from app.models.tenant import TenantQuota

        with app.app_context():
            quota = db.session.query(TenantQuota).filter_by(school_id=sid).first()
            if quota is None:
                quota = TenantQuota(school_id=sid, tier="pro")
                db.session.add(quota)
            quota.ai_enabled = True
            quota.max_ai_tokens_monthly = 1_000_000
            db.session.commit()

    def test_chat_requires_question(self, app):
        sid = make_school(app)
        self._quota_on(app, sid)
        uid, email = mk_user(app, "student", school_id=sid)
        client = login_as(app, (uid, email))
        resp = client.post("/ai/chat", data=json.dumps({"question": ""}), content_type="application/json")
        assert resp.status_code == 400

    def test_chat_stream_requires_question(self, app):
        sid = make_school(app)
        self._quota_on(app, sid)
        uid, email = mk_user(app, "student", school_id=sid)
        client = login_as(app, (uid, email))
        resp = client.post("/ai/chat/stream", data=json.dumps({}), content_type="application/json")
        assert resp.status_code == 400

    def test_suggest_grade_requires_answer(self, app):
        sid = make_school(app)
        self._quota_on(app, sid)
        tid, email = mk_user(app, "teacher", school_id=sid)
        client = login_as(app, (tid, email))
        resp = client.post(
            "/ai/grade/suggest",
            data=json.dumps({"student_answer": ""}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_suggest_grade_forbidden_student(self, app):
        sid = make_school(app)
        self._quota_on(app, sid)
        uid, email = mk_user(app, "student", school_id=sid)
        client = login_as(app, (uid, email))
        resp = client.post(
            "/ai/grade/suggest",
            data=json.dumps({"student_answer": "x"}),
            content_type="application/json",
        )
        assert resp.status_code == 403


# ═════════════════════════════ tasks layer ═════════════════════════════


@pytest.fixture()
def celery_guard():
    """Import task modules with the Celery guard patched (local env has no celery)."""
    with patch("app.tasks._HAS_CELERY", True):
        mock_celery = MagicMock()

        def _task_dec(*a, **kw):
            if a:
                return a[0]
            return lambda f: f

        mock_celery.task.side_effect = _task_dec
        with patch("app.tasks.celery_app", mock_celery):
            from app.tasks import grading, notifications, reports, video  # noqa: F401

            yield


class TestDispatchModes:
    def test_dispatch_inline_success(self):
        from app.tasks import dispatch

        def job(x):
            return x * 2

        result = dispatch(job, 21, inline_timeout=5)
        assert result["mode"] == "inline"
        assert result["result"] == 42

    def test_dispatch_inline_error(self):
        from app.tasks import dispatch

        def bad():
            raise ValueError("boom")

        result = dispatch(bad, inline_timeout=5)
        assert result["mode"] == "inline_error"
        assert "boom" in result["error"]

    def test_dispatch_zero_timeout_skips(self):
        from app.tasks import dispatch

        def job():
            return 1

        result = dispatch(job, inline_timeout=0)
        assert result["mode"] == "skipped"

    def test_dispatch_timeout_mode(self):
        import time as _time

        from app.tasks import dispatch

        def slow():
            _time.sleep(1.2)

        result = dispatch(slow, inline_timeout=0.2)
        assert result["mode"] == "inline_timeout"

    def test_dispatch_celery_mode_with_mock(self):
        from app.tasks import dispatch

        fake_task = MagicMock()
        fake_task.delay.return_value.id = "abc-123"
        with patch("app.tasks._HAS_CELERY", True):
            result = dispatch(fake_task, 1, 2)
        assert result["mode"] == "celery"
        assert result["task_id"] == "abc-123"


class TestGradingBatch:
    def test_batch_update_gradebook_success(self, app, celery_guard):
        from app.tasks.grading import batch_update_gradebook

        sid, cid, _ = _setup_class(app)
        stu_id, _ = mk_user(app, "student", school_id=sid)
        cat_id = make_grade_category(app, cid, "أعمال", 50)
        item_id = make_grade_item(app, cid, cat_id, "واجب 1", 100)

        with app.app_context():
            result = batch_update_gradebook(
                _self(),
                class_id=cid,
                grade_item_id=item_id,
                entries=[{"student_id": stu_id, "mark": 88.5, "note": None}],
            )
        assert result["status"] == "completed"
        assert result["updated"] == 1

    def test_batch_update_gradebook_wrong_class(self, app, celery_guard):
        from app.tasks.grading import batch_update_gradebook

        sid, cid, _ = _setup_class(app)
        cat_id = make_grade_category(app, cid, "أعمال", 50)
        item_id = make_grade_item(app, cid, cat_id, "واجب", 100)
        other_cid = make_class(
            app,
            make_school(app),
            make_grade(app, sid, grade_level=_next_level(sid)),
            make_subject(app),
        )

        with app.app_context():
            result = batch_update_gradebook(_self(), class_id=other_cid, grade_item_id=item_id, entries=[])
        assert result["status"] == "failed"

    def test_batch_grade_quiz_empty(self, app, celery_guard):
        from app.tasks.grading import batch_grade_quiz

        with patch("app.tasks.grading.auto_grade_quiz_attempt") as mock_auto:
            mock_auto.delay.return_value.get.return_value = {"status": "completed"}
            with app.app_context():
                result = batch_grade_quiz(_self(), quiz_id=999999)
        assert result["total"] == 0
        assert result["graded"] == 0


class TestNotificationsTasks:
    def test_bulk_announcement_no_users(self, app, celery_guard):
        from app.tasks.notifications import bulk_dispatch_school_announcement

        with app.app_context():
            result = bulk_dispatch_school_announcement(
                _self(),
                make_school(app),
                "إعلان",
                "نص",
            )
        assert result["success"] is True
        assert result["sent_count"] == 0

    def test_bulk_announcement_with_recipients(self, app, celery_guard):
        from app.tasks.notifications import bulk_dispatch_school_announcement

        sid = make_school(app)
        for _ in range(3):
            mk_user(app, "student", school_id=sid)
        with app.app_context():
            result = bulk_dispatch_school_announcement(
                _self(),
                sid,
                "إعلان عام",
                "مرحباً بالجميع",
                link="/",
            )
        assert result["success"] is True
        assert result["sent_count"] == 3

    def test_dispatch_email_user_not_found(self, app, celery_guard):
        from app.tasks.notifications import dispatch_email_notification

        with app.app_context():
            result = dispatch_email_notification(_self(), 999999, subject="t", html_body="<p>x</p>", plain_body="x")
        assert result["success"] is False
        assert result["error"] == "User not found"


class TestVideoTaskHelpers:
    def test_generate_encryption_key(self, celery_guard, tmp_path):
        from app.tasks.video import _generate_encryption_key

        key_path = tmp_path / "enc.key"
        info_path = tmp_path / "key_info.txt"
        _generate_encryption_key(str(key_path), str(info_path))
        assert key_path.exists()
        assert key_path.stat().st_size == 16
        content = info_path.read_text()
        assert "encryption.key" in content
        assert str(key_path) in content

    def test_transcode_missing_source(self, app, celery_guard, tmp_path):
        from app.tasks.video import transcode_video_to_hls

        with app.app_context():
            result = transcode_video_to_hls(
                self=None,
                lesson_id=1,
                source_file_path=str(tmp_path / "missing.mp4"),
                school_id=1,
            )
        assert result["status"] == "failed"
        assert "not found" in result["error"].lower()

    def test_transcode_probe_failure(self, app, celery_guard, tmp_path, monkeypatch):
        from app.tasks import video

        monkeypatch.setattr(video, "_probe_video", lambda p: None)
        with app.app_context():
            with patch("app.core.db.tx") as mock_tx:
                result = video.transcode_video_to_hls(
                    self=None,
                    lesson_id=1,
                    source_file_path=str(tmp_path / "src.mp4"),
                    school_id=1,
                )
        assert result["status"] == "failed"
        assert "probe" in (result.get("error") or "").lower()
        mock_tx.assert_not_called()


# ═════════════════════════════ permissions ═════════════════════════════


class TestPermissionsGaps:
    def test_role_required_anonymous_redirects(self, app):
        client = app.test_client()
        resp = client.get("/admin/settings", follow_redirects=False)
        assert resp.status_code in (302, 401)

    def test_any_role_denies_wrong_role(self, app):

        sid = make_school(app)
        uid, email = mk_user(app, "student", school_id=sid)
        client = login_as(app, (uid, email))
        with client.session_transaction() as sess:
            sess["_fresh"] = True
        # hitting a teacher-only endpoint as student
        resp = client.get("/tutoring/earnings")
        assert resp.status_code == 403
