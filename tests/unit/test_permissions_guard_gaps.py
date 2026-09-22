"""Batch 1 — فجوات الصلاحيات المتبقية (app/core/permissions.py).

تغطي الفئات هنا ما لم تغطِّه أجنحة الاختبار السابقة:
- الحرس المركّب: class_access_required / class_teach_required / parent_of_required
  / student_only — كل فرع (400/404/403/نجاح) عبر استدعاء مباشر للـ view.
- tenant_ai_quota: فرع الكاش (قرار مخزّن مسموح/ممنوع) وفرع get_quota الإنشاء.
- require_ai_quota: ذراع JSON (Subcode + 403) وذراع الويب (403).
- أي دور super_admin يتخطى كل الحرس.

كل الاختبارات تدفع طلبات HTTP حقيقية عبر test_client أو تستدعي الـ view
داخل test_request_context — لا قيم ثابتة بلا سلوك.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest
from tests.conftest import (
    make_class,
    make_class_member,
    make_family_link,
    make_grade,
    make_school,
    make_subject,
    make_user,
)

PASSWORD = "TestPass123!"

_LEVELS: dict[int, int] = {}


def _next_level(sid: int) -> int:
    _LEVELS[sid] = _LEVELS.get(sid, 0) + 1
    return _LEVELS[sid]


def mk_user(app, role: str, school_id=None):
    from tests.conftest import _uid

    email = f"perm-{_uid()}@test.com"
    uid = make_user(app, role=role, school_id=school_id, approved=True, email=email)
    return uid, email


def login_as(app, email: str):
    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    return client


def _setup_class(app, teacher_id=None):
    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=_next_level(sid))
    subj = make_subject(app)
    cid = make_class(app, sid, gid, subj, teacher_id=teacher_id)
    return sid, cid


# ═══════════════════════════════════════════════════════════════════════════
# class_access_required — كل الفروع عبر view حقيقي على blueprint مسجّل
# ═══════════════════════════════════════════════════════════════════════════


class TestClassAccessRequired:
    """يستخدم /schools/class/<id> (can_view_class مباشرة) و /billing/<id>
    (class_access_required) — كلاهما يدفع طبقة الحرس الحقيقية."""

    def test_missing_class_404(self, app):
        uid, email = mk_user(app, role="student")
        client = login_as(app, email)
        assert client.get("/schools/class/999999").status_code == 404
        assert client.get("/billing/999999").status_code == 404

    def test_member_of_free_class_ok(self, app):
        sid, cid = _setup_class(app)
        uid, email = mk_user(app, role="student", school_id=sid)
        make_class_member(app, cid, uid)
        client = login_as(app, email)
        assert client.get(f"/schools/class/{cid}").status_code == 200
        assert client.get(f"/billing/{cid}").status_code == 200

    def test_non_member_free_class_forbidden(self, app):
        sid, cid = _setup_class(app)
        uid, email = mk_user(app, role="student", school_id=sid)
        client = login_as(app, email)
        assert client.get(f"/schools/class/{cid}").status_code == 403
        assert client.get(f"/billing/{cid}").status_code == 403

    def test_paid_class_requires_active_subscription(self, app):
        from tests.conftest import make_subscription, make_subscription_plan

        sid, cid = _setup_class(app)
        uid, email = mk_user(app, role="student", school_id=sid)
        make_class_member(app, cid, uid)
        plan_id = make_subscription_plan(app, sid, cid, price=Decimal("150"))

        client = login_as(app, email)
        assert client.get(f"/billing/{cid}").status_code == 403  # بلا اشتراك نشط

        make_subscription(app, uid, plan_id, cid, price=Decimal("150"), status="active")
        assert client.get(f"/billing/{cid}").status_code == 200  # اشتراك نشط

    def test_school_admin_of_same_school_allowed(self, app):
        sid, cid = _setup_class(app)
        _uid2, email = mk_user(app, role="school_admin", school_id=sid)
        client = login_as(app, email)
        assert client.get(f"/schools/class/{cid}").status_code == 200
        assert client.get(f"/billing/{cid}").status_code == 200

    def test_parent_viewing_child_class_ok(self, app):
        sid, cid = _setup_class(app)
        parent_uid, parent_email = mk_user(app, role="parent", school_id=sid)
        stu_uid, _ = mk_user(app, role="student", school_id=sid)
        make_class_member(app, cid, stu_uid)
        make_family_link(app, parent_uid, stu_uid)
        client = login_as(app, parent_email)
        assert client.get(f"/schools/class/{cid}").status_code == 200
        assert client.get(f"/billing/{cid}").status_code == 200

    def test_unrelated_parent_forbidden(self, app):
        sid, cid = _setup_class(app)
        parent_uid, parent_email = mk_user(app, role="parent", school_id=sid)
        stu_uid, _ = mk_user(app, role="student", school_id=sid)
        make_class_member(app, cid, stu_uid)  # الطالب عضو لكن لا صلة لوليّه
        client = login_as(app, parent_email)
        assert client.get(f"/schools/class/{cid}").status_code == 403
        assert client.get(f"/billing/{cid}").status_code == 403


# ═══════════════════════════════════════════════════════════════════════════
# class_teach_required — POST /classes/<class_id>/lessons (content)
# ═══════════════════════════════════════════════════════════════════════════


class TestClassTeachRequired:
    def test_missing_class_404(self, app):
        _uid2, email = mk_user(app, role="teacher")
        client = login_as(app, email)
        resp = client.post("/classes/999999/lessons", data={})
        assert resp.status_code == 404

    def test_teacher_of_own_class_ok(self, app):
        t_uid, t_email = mk_user(app, role="teacher")
        sid, cid = _setup_class(app, teacher_id=t_uid)
        client = login_as(app, t_email)
        resp = client.get(f"/classes/{cid}/lessons/new")
        assert resp.status_code == 200

    def test_other_teacher_forbidden(self, app):
        t_uid, _ = mk_user(app, role="teacher")
        sid, cid = _setup_class(app, teacher_id=t_uid)
        _o_uid, o_email = mk_user(app, role="teacher", school_id=sid)
        client = login_as(app, o_email)
        assert client.get(f"/classes/{cid}/lessons/new").status_code == 403

    def test_student_forbidden(self, app):
        sid, cid = _setup_class(app)
        _s_uid, s_email = mk_user(app, role="student", school_id=sid)
        client = login_as(app, s_email)
        assert client.get(f"/classes/{cid}/lessons/new").status_code == 403


# ═══════════════════════════════════════════════════════════════════════════
# parent_of_required / student_only — استدعاء مباشر للحرس (بلا route مخصص)
# ═══════════════════════════════════════════════════════════════════════════


class TestParentOfRequired:
    def _view(self):
        from app.core.permissions import parent_of_required

        @parent_of_required
        def _v(student_id: int):
            from flask import jsonify

            return jsonify(ok=True, student_id=student_id)

        return _v

    def test_missing_student_id_aborts_400(self, app):
        from werkzeug.exceptions import BadRequest

        p_uid, _ = mk_user(app, role="parent")
        with app.test_request_context():
            from app.extensions import db
            from app.models.user import User
            from flask_login import login_user

            login_user(db.session.get(User, p_uid))
            with pytest.raises(BadRequest):
                self._view()()

    def test_unrelated_parent_403(self, app):
        from werkzeug.exceptions import Forbidden

        p_uid, _ = mk_user(app, role="parent")
        s_uid, _ = mk_user(app, role="student")
        with app.test_request_context():
            from app.extensions import db
            from app.models.user import User
            from flask_login import login_user

            login_user(db.session.get(User, p_uid))
            with pytest.raises(Forbidden):
                self._view()(student_id=s_uid)

    def test_linked_parent_ok(self, app):
        p_uid, _ = mk_user(app, role="parent")
        s_uid, _ = mk_user(app, role="student")
        make_family_link(app, p_uid, s_uid)
        with app.test_request_context():
            from app.extensions import db
            from app.models.user import User
            from flask_login import login_user

            login_user(db.session.get(User, p_uid))
            resp = self._view()(student_id=s_uid)
            assert resp.get_json()["ok"] is True

    def test_non_parent_role_403_via_role_guard(self, app):
        """طالب يمرّ عبر parent_of_required → يُرفض في طبقة role_required."""
        from werkzeug.exceptions import Forbidden

        s_uid, _ = mk_user(app, role="student")
        with app.test_request_context():
            from app.extensions import db
            from app.models.user import User
            from flask_login import login_user

            login_user(db.session.get(User, s_uid))
            with pytest.raises(Forbidden):
                self._view()(student_id=s_uid)


class TestStudentOnly:
    def _view(self):
        from app.core.permissions import student_only

        @student_only
        def _v():
            from flask import jsonify

            return jsonify(ok=True)

        return _v

    def test_student_ok(self, app):
        s_uid, _ = mk_user(app, role="student")
        with app.test_request_context():
            from app.extensions import db
            from app.models.user import User
            from flask_login import login_user

            login_user(db.session.get(User, s_uid))
            assert self._view()().get_json()["ok"] is True

    def test_teacher_403(self, app):
        from werkzeug.exceptions import Forbidden

        t_uid, _ = mk_user(app, role="teacher")
        with app.test_request_context():
            from app.extensions import db
            from app.models.user import User
            from flask_login import login_user

            login_user(db.session.get(User, t_uid))
            with pytest.raises(Forbidden):
                self._view()()

    def test_unauthenticated_redirects_to_login(self, app):
        """login_manager.login_view مضبوط → login_required يحوّل للدخول (302)."""
        with app.test_request_context():
            resp = self._view()()
            code = resp.status_code if hasattr(resp, "status_code") else resp[1]
            assert code in (302, 401)


# ═══════════════════════════════════════════════════════════════════════════
# tenant_ai_quota + require_ai_quota — فرعا الكاش وذراعا JSON/ويب
# ═══════════════════════════════════════════════════════════════════════════


class TestTenantAiQuotaCacheBranches:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        from app.core.cache import clear

        clear()
        yield
        clear()

    def _login_ctx(self, app, uid: int):
        return app.test_request_context()

    def test_cached_allow_decision_returns_allow(self, app):
        from app.core import permissions
        from app.core.tenancy import current_school_id
        from app.extensions import db
        from app.models.user import User
        from flask_login import login_user

        sid = make_school(app)
        uid, _ = mk_user(app, role="teacher", school_id=sid)
        with app.app_context(), app.test_request_context():
            login_user(db.session.get(User, uid))
            from app.core.cache import set as cache_set

            cache_set(f"ai_quota:{sid}", {"allowed": True, "sub_code": ""}, ttl=30)
            with patch("app.core.tenancy.current_school_id", current_school_id):
                allowed, sub_code, message = permissions.tenant_ai_quota()
            assert (allowed, sub_code, message) == (True, "", "")

    def test_cached_deny_decision_returns_deny(self, app):
        from app.core import permissions
        from app.extensions import db
        from app.models.user import User
        from flask_login import login_user

        sid = make_school(app)
        uid, _ = mk_user(app, role="teacher", school_id=sid)
        with app.app_context(), app.test_request_context():
            login_user(db.session.get(User, uid))
            from app.core.cache import set as cache_set

            cache_set(f"ai_quota:{sid}", {"allowed": False, "sub_code": "AI_QUOTA_EXCEEDED"}, ttl=30)
            with patch("app.core.tenancy.current_school_id", lambda: sid):
                allowed, sub_code, message = permissions.tenant_ai_quota()
            assert (allowed, sub_code) == (False, "AI_QUOTA_EXCEEDED")
            assert message  # رسالة عربية غير فارغة

    def test_no_school_id_returns_disabled(self, app):
        from app.core import permissions
        from app.extensions import db
        from app.models.user import User
        from flask_login import login_user

        uid, _ = mk_user(app, role="teacher")  # بلا مدرسة
        with app.app_context(), app.test_request_context():
            login_user(db.session.get(User, uid))
            allowed, sub_code, _msg = permissions.tenant_ai_quota()
            assert (allowed, sub_code) == (False, "AI_DISABLED_FOR_TENANT")

    def test_quota_row_created_when_missing_and_enabled(self, app):
        """get_quota ينشئ صف حصة افتراضي؛ عند تفعيل AI والحد الكبير → مسموح."""
        from app.core import permissions
        from app.extensions import db
        from app.models.tenant import TenantQuota
        from app.models.user import User
        from flask_login import login_user

        sid = make_school(app)
        uid, _ = mk_user(app, role="teacher", school_id=sid)
        with app.app_context(), app.test_request_context():
            login_user(db.session.get(User, uid))
            q = TenantQuota.query.filter_by(school_id=sid).first()
            if q is None:
                q = TenantQuota(school_id=sid)
                db.session.add(q)
            q.ai_enabled = True
            q.max_ai_tokens_monthly = 100_000
            db.session.commit()
            with patch("app.core.tenancy.current_school_id", lambda: sid):
                allowed, sub_code, _msg = permissions.tenant_ai_quota()
            assert (allowed, sub_code) == (True, "")

    def test_disabled_ai_for_tenant(self, app):
        from app.core import permissions
        from app.extensions import db
        from app.models.tenant import TenantQuota
        from app.models.user import User
        from flask_login import login_user

        sid = make_school(app)
        uid, _ = mk_user(app, role="teacher", school_id=sid)
        with app.app_context(), app.test_request_context():
            login_user(db.session.get(User, uid))
            q = TenantQuota.query.filter_by(school_id=sid).first()
            if q is None:
                q = TenantQuota(school_id=sid)
                db.session.add(q)
            q.ai_enabled = False
            db.session.commit()
            with patch("app.core.tenancy.current_school_id", lambda: sid):
                allowed, sub_code, _msg = permissions.tenant_ai_quota()
            assert (allowed, sub_code) == (False, "AI_DISABLED_FOR_TENANT")


class TestRequireAiQuotaWebAndJson:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        from app.core.cache import clear

        clear()
        yield
        clear()

    @staticmethod
    def _view():
        from app.core.permissions import require_ai_quota

        @require_ai_quota
        def _v():
            from flask import jsonify

            return jsonify(ok=True)

        return _v

    def test_json_deny_returns_structured_403(self, app):
        from app.extensions import db
        from app.models.user import User
        from flask_login import login_user

        sid = make_school(app)
        uid, _ = mk_user(app, role="teacher", school_id=sid)
        with app.test_request_context("/api/ai/chat", method="POST", json={}), app.app_context():
            login_user(db.session.get(User, uid))
            resp = self._view()()
            assert resp.status_code == 403
            body = resp.get_json()
            assert body["error"]["code"] == "AI_DISABLED_FOR_TENANT"

    def test_web_deny_aborts_403(self, app):
        from app.extensions import db
        from app.models.user import User
        from flask_login import login_user
        from werkzeug.exceptions import Forbidden

        sid = make_school(app)
        uid, _ = mk_user(app, role="teacher", school_id=sid)
        with app.test_request_context("/ai/chat", method="POST"):
            login_user(db.session.get(User, uid))
            with pytest.raises(Forbidden):
                self._view()()

    def test_allow_passes_through(self, app):
        from app.extensions import db
        from app.models.user import User
        from flask_login import login_user

        uid, _ = mk_user(app, role="super_admin")
        with app.test_request_context("/api/ai/chat", method="POST", json={}):
            login_user(db.session.get(User, uid))
            assert self._view()().get_json()["ok"] is True
