"""اختبارات شاملة لنقاط API v1 — /api/v1/* (app/modules/api/routes.py).

يغطي: المصادقة، العزل متعدد التينانتس، الترقيم، البحث، معالجات الأخطاء،
وسيناريوهات الصلاحيات لكل دور. كل اختبار يعمل على قاعدة بيانات اختبار نظيفة.
"""

from __future__ import annotations

import pytest
from tests.conftest import (
    make_class,
    make_class_member,
    make_grade,
    make_lesson,
    make_school,
    make_subject,
    make_subscription,
    make_subscription_plan,
    make_tutoring_session,
    make_user,
)


def _login_as(client, email, password="TestPass123!"):
    client.post("/auth/login", data={"email": email, "password": password}, follow_redirects=True)


def _email_of(app, user_id):
    with app.app_context():
        from app.extensions import db
        from app.models.user import User

        return db.session.get(User, user_id).email


def _make_user(app, role, school_id=None):
    """Returns (user_id, email)."""
    uid = make_user(app, role=role, school_id=school_id)
    return uid, _email_of(app, uid)


def _make_student(app, school_id=None):
    return _make_user(app, "student", school_id)


def _make_teacher(app, school_id=None):
    return _make_user(app, "teacher", school_id)


def _make_school_admin(app, school_id=None):
    return _make_user(app, "school_admin", school_id)


def _make_super_admin(app):
    return _make_user(app, "super_admin")


# ═══════════════════════════════════════════════════════════════════════
# Auth boundary
# ═══════════════════════════════════════════════════════════════════════


class TestApiAuthBoundary:
    """كل نقطة API يجب أن ترفض غير المصادق عليه بـ 401."""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/me",
            "/api/v1/schools",
            "/api/v1/schools/1",
            "/api/v1/lessons",
            "/api/v1/lessons/1",
            "/api/v1/tutoring/sessions",
            "/api/v1/tutoring/sessions/1",
            "/api/v1/users",
            "/api/v1/users/1",
            "/api/v1/classes",
            "/api/v1/classes/1",
            "/api/v1/search?q=abc",
        ],
    )
    def test_unauthenticated_gets_401(self, client, path):
        resp = client.get(path)
        assert resp.status_code == 401
        data = resp.get_json()
        assert data["error"]["code"] == "UNAUTHORIZED"


class TestApiMe:
    """نقطة /api/v1/me."""

    def test_me_returns_profile(self, client, app):
        _uid, email = _make_student(app)
        _login_as(client, email)
        resp = client.get("/api/v1/me")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["email"] == email
        assert data["data"]["role"] == "student"


# ═══════════════════════════════════════════════════════════════════════
# Schools
# ═══════════════════════════════════════════════════════════════════════


class TestApiSchools:
    def test_school_list_super_admin_sees_all(self, client, app):
        _aid, admin = _make_super_admin(app)
        s1 = make_school(app)
        s2 = make_school(app)
        _login_as(client, admin)
        resp = client.get("/api/v1/schools")
        assert resp.status_code == 200
        ids = {item["id"] for item in resp.get_json()["data"]}
        assert {s1, s2} <= ids

    def test_school_list_student_scoped_to_own_school(self, client, app):
        sid = make_school(app)
        other = make_school(app)
        _uid, student = _make_student(app, school_id=sid)
        _login_as(client, student)
        resp = client.get("/api/v1/schools")
        assert resp.status_code == 200
        ids = {item["id"] for item in resp.get_json()["data"]}
        assert sid in ids and other not in ids

    def test_school_get_own(self, client, app):
        sid = make_school(app)
        _uid, student = _make_student(app, school_id=sid)
        _login_as(client, student)
        resp = client.get(f"/api/v1/schools/{sid}")
        assert resp.status_code == 200
        assert resp.get_json()["data"]["id"] == sid

    def test_school_get_other_tenant_forbidden(self, client, app):
        s1 = make_school(app)
        s2 = make_school(app)
        _uid, student = _make_student(app, school_id=s1)
        _login_as(client, student)
        resp = client.get(f"/api/v1/schools/{s2}")
        assert resp.status_code == 403

    def test_school_get_missing_404(self, client, app):
        _uid, student = _make_student(app)
        _login_as(client, student)
        resp = client.get("/api/v1/schools/999999")
        assert resp.status_code == 404

    def test_school_get_super_admin_any_school(self, client, app):
        sid = make_school(app)
        _aid, admin = _make_super_admin(app)
        _login_as(client, admin)
        resp = client.get(f"/api/v1/schools/{sid}")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════
# Lessons
# ═══════════════════════════════════════════════════════════════════════


class TestApiLessons:
    def _setup_class_with_lesson(self, app):
        sid = make_school(app)
        gid = make_grade(app, sid)
        subj = make_subject(app)
        cid = make_class(app, sid, gid, subj)
        lid = make_lesson(app, cid)
        return sid, cid, lid

    def test_lesson_list_admin_sees_all(self, client, app):
        sid, cid, lid = self._setup_class_with_lesson(app)
        _aid, admin = _make_school_admin(app, school_id=sid)
        _login_as(client, admin)
        resp = client.get("/api/v1/lessons")
        assert resp.status_code == 200
        ids = {item["id"] for item in resp.get_json()["data"]}
        assert lid in ids

    def test_lesson_list_student_only_own_class(self, client, app):
        sid, cid, lid = self._setup_class_with_lesson(app)
        _uid, student = _make_student(app, school_id=sid)
        make_class_member(app, cid, _uid, status="active")
        _login_as(client, student)
        resp = client.get("/api/v1/lessons")
        assert resp.status_code == 200
        ids = {item["id"] for item in resp.get_json()["data"]}
        assert lid in ids

    def test_lesson_list_student_not_member_sees_none(self, client, app):
        sid, cid, lid = self._setup_class_with_lesson(app)
        other = make_school(app)
        _uid, student = _make_student(app, school_id=other)
        _login_as(client, student)
        resp = client.get("/api/v1/lessons")
        assert resp.status_code == 200
        ids = {item["id"] for item in resp.get_json()["data"]}
        assert lid not in ids

    def test_lesson_get_member_ok(self, client, app):
        sid, cid, lid = self._setup_class_with_lesson(app)
        _uid, student = _make_student(app, school_id=sid)
        make_class_member(app, cid, _uid, status="active")
        _login_as(client, student)
        resp = client.get(f"/api/v1/lessons/{lid}")
        assert resp.status_code == 200
        assert resp.get_json()["data"]["id"] == lid

    def test_lesson_get_non_member_forbidden(self, client, app):
        sid, cid, lid = self._setup_class_with_lesson(app)
        _uid, student = _make_student(app, school_id=sid)
        _login_as(client, student)
        resp = client.get(f"/api/v1/lessons/{lid}")
        assert resp.status_code == 403

    def test_lesson_get_missing_404(self, client, app):
        sid = make_school(app)
        _aid, admin = _make_school_admin(app, school_id=sid)
        _login_as(client, admin)
        resp = client.get("/api/v1/lessons/999999")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════
# Tutoring sessions
# ═══════════════════════════════════════════════════════════════════════


class TestApiTutoringSessions:
    def test_student_sees_only_own_sessions(self, client, app):
        sid = make_school(app)
        _t1, t1 = _make_teacher(app, school_id=sid)
        _s1, s1 = _make_student(app, school_id=sid)
        _s2, s2 = _make_student(app, school_id=sid)
        own = make_tutoring_session(app, _t1, _s1)
        other = make_tutoring_session(app, _t1, _s2)
        _login_as(client, s1)
        resp = client.get("/api/v1/tutoring/sessions")
        assert resp.status_code == 200
        ids = {item["id"] for item in resp.get_json()["data"]}
        assert own in ids and other not in ids

    def test_teacher_sees_only_own_sessions(self, client, app):
        sid = make_school(app)
        _t1, t1 = _make_teacher(app, school_id=sid)
        _t2, t2 = _make_teacher(app, school_id=sid)
        _s1, s1 = _make_student(app, school_id=sid)
        own = make_tutoring_session(app, _t1, _s1)
        other = make_tutoring_session(app, _t2, _s1)
        _login_as(client, t1)
        resp = client.get("/api/v1/tutoring/sessions")
        assert resp.status_code == 200
        ids = {item["id"] for item in resp.get_json()["data"]}
        assert own in ids and other not in ids

    def test_session_get_own_ok(self, client, app):
        sid = make_school(app)
        _t1, t1 = _make_teacher(app, school_id=sid)
        _s1, s1 = _make_student(app, school_id=sid)
        session_id = make_tutoring_session(app, _t1, _s1)
        _login_as(client, s1)
        resp = client.get(f"/api/v1/tutoring/sessions/{session_id}")
        assert resp.status_code == 200

    def test_session_get_unrelated_forbidden(self, client, app):
        sid = make_school(app)
        _t1, t1 = _make_teacher(app, school_id=sid)
        _s1, s1 = _make_student(app, school_id=sid)
        _s2, s2 = _make_student(app, school_id=sid)
        session_id = make_tutoring_session(app, _t1, _s1)
        _login_as(client, s2)
        resp = client.get(f"/api/v1/tutoring/sessions/{session_id}")
        assert resp.status_code == 403

    def test_session_get_missing_404(self, client, app):
        sid = make_school(app)
        _uid, student = _make_student(app, school_id=sid)
        _login_as(client, student)
        resp = client.get("/api/v1/tutoring/sessions/999999")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════
# Users
# ═══════════════════════════════════════════════════════════════════════


class TestApiUsers:
    def test_users_list_forbidden_for_student(self, client, app):
        _uid, student = _make_student(app)
        _login_as(client, student)
        resp = client.get("/api/v1/users")
        assert resp.status_code == 403

    def test_users_list_school_admin_scoped(self, client, app):
        sid = make_school(app)
        other = make_school(app)
        _aid, admin = _make_school_admin(app, school_id=sid)
        in_school = _make_student(app, school_id=sid)[0]
        out_school = _make_student(app, school_id=other)[0]
        _login_as(client, admin)
        resp = client.get("/api/v1/users")
        assert resp.status_code == 200
        ids = {item["id"] for item in resp.get_json()["data"]}
        assert in_school in ids and out_school not in ids

    def test_users_get_same_school_ok(self, client, app):
        sid = make_school(app)
        _aid, admin = _make_school_admin(app, school_id=sid)
        _uid, student = _make_student(app, school_id=sid)
        _login_as(client, admin)
        resp = client.get(f"/api/v1/users/{_uid}")
        assert resp.status_code == 200
        assert resp.get_json()["data"]["id"] == _uid

    def test_users_get_cross_tenant_forbidden(self, client, app):
        s1 = make_school(app)
        s2 = make_school(app)
        _aid, admin = _make_school_admin(app, school_id=s1)
        _uid, student = _make_student(app, school_id=s2)
        _login_as(client, admin)
        resp = client.get(f"/api/v1/users/{_uid}")
        assert resp.status_code == 403

    def test_users_get_missing_404(self, client, app):
        _aid, admin = _make_super_admin(app)
        _login_as(client, admin)
        resp = client.get("/api/v1/users/999999")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════
# Classes
# ═══════════════════════════════════════════════════════════════════════


class TestApiClasses:
    def _setup(self, app):
        sid = make_school(app)
        gid = make_grade(app, sid)
        subj = make_subject(app)
        cid = make_class(app, sid, gid, subj)
        return sid, cid

    def test_classes_list_super_admin_all(self, client, app):
        sid, cid = self._setup(app)
        _sid2, cid2 = self._setup(app)
        _aid, admin = _make_super_admin(app)
        _login_as(client, admin)
        resp = client.get("/api/v1/classes")
        assert resp.status_code == 200
        ids = {item["id"] for item in resp.get_json()["data"]}
        assert cid in ids and cid2 in ids

    def test_classes_list_student_member_only(self, client, app):
        sid, cid = self._setup(app)
        _uid, student = _make_student(app, school_id=sid)
        make_class_member(app, cid, _uid, status="active")
        _login_as(client, student)
        resp = client.get("/api/v1/classes")
        assert resp.status_code == 200
        ids = {item["id"] for item in resp.get_json()["data"]}
        assert cid in ids

    def test_classes_get_member_ok(self, client, app):
        sid, cid = self._setup(app)
        _uid, student = _make_student(app, school_id=sid)
        make_class_member(app, cid, _uid, status="active")
        _login_as(client, student)
        resp = client.get(f"/api/v1/classes/{cid}")
        assert resp.status_code == 200

    def test_classes_get_non_member_forbidden(self, client, app):
        sid, cid = self._setup(app)
        _uid, student = _make_student(app, school_id=sid)
        _login_as(client, student)
        resp = client.get(f"/api/v1/classes/{cid}")
        assert resp.status_code == 403

    def test_classes_get_missing_404(self, client, app):
        _aid, admin = _make_super_admin(app)
        _login_as(client, admin)
        resp = client.get("/api/v1/classes/999999")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════
# Search
# ═══════════════════════════════════════════════════════════════════════


class TestApiSearch:
    def test_search_short_query_400(self, client, app):
        _uid, student = _make_student(app)
        _login_as(client, student)
        resp = client.get("/api/v1/search?q=a")
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "QUERY_TOO_SHORT"

    def test_search_empty_query_400(self, client, app):
        _uid, student = _make_student(app)
        _login_as(client, student)
        resp = client.get("/api/v1/search")
        assert resp.status_code == 400

    def test_search_super_admin_finds_school(self, client, app):
        sid = make_school(app, name_ar="مدرسة البحث الفريدة")
        _aid, admin = _make_super_admin(app)
        _login_as(client, admin)
        resp = client.get("/api/v1/search?q=البحث الفريدة")
        assert resp.status_code == 200
        results = resp.get_json()["data"]
        school_ids = {s["id"] for s in results["schools"]}
        assert sid in school_ids

    def test_search_student_scoped_to_own_school(self, client, app):
        s1 = make_school(app, name_ar="مدرسة النجمة")
        s2 = make_school(app, name_ar="مدرسة النجمة")
        _uid, student = _make_student(app, school_id=s1)
        _login_as(client, student)
        resp = client.get("/api/v1/search?q=النجمة")
        assert resp.status_code == 200
        school_ids = {s["id"] for s in resp.get_json()["data"]["schools"]}
        assert s1 in school_ids and s2 not in school_ids

    def test_search_limit_capped(self, client, app):
        for _ in range(5):
            make_school(app, name_ar="مدرسة البحث")
        _uid, student = _make_student(app)
        _login_as(client, student)
        resp = client.get("/api/v1/search?q=البحث&limit=100")
        assert resp.status_code == 200
        # limit is capped at 20
        assert len(resp.get_json()["data"]["schools"]) <= 20


# ═══════════════════════════════════════════════════════════════════════
# Pagination + error handlers
# ═══════════════════════════════════════════════════════════════════════


class TestApiPagination:
    def test_page_and_per_page_validation(self, client, app):
        _aid, admin = _make_super_admin(app)
        _login_as(client, admin)
        resp = client.get("/api/v1/schools?page=0&per_page=0")
        assert resp.status_code == 200
        meta = resp.get_json()["meta"]
        assert meta["page"] >= 1
        assert meta["per_page"] >= 1

    def test_paginated_response_shape(self, client, app):
        _aid, admin = _make_super_admin(app)
        _login_as(client, admin)
        resp = client.get("/api/v1/schools")
        data = resp.get_json()["data"]
        meta = resp.get_json()["meta"]
        assert all(k in meta for k in ("page", "per_page", "total", "pages"))
        assert isinstance(data, list)


class TestApiErrorHandlers:
    def test_api_404_handler(self, client, app):
        _uid, student = _make_student(app)
        _login_as(client, student)
        resp = client.get("/api/v1/does-not-exist")
        # app-level routing 404 may render HTML; the bp-level JSON handler is
        # verified by direct invocation (same pattern as test_api_429_handler)
        assert resp.status_code == 404
        from app.modules.api.routes import api_404

        with app.test_request_context():
            body, status = api_404(None)
            assert status == 404
            assert body.get_json()["error"]["code"] == "NOT_FOUND"

    def test_api_429_handler(self, client, app):
        from app.modules.api.routes import api_429

        with app.test_request_context():
            resp = api_429(None)
            assert resp[1] == 429
            assert resp[0].get_json()["error"]["code"] == "RATE_LIMITED"


class TestApiSubscriptionsSearchBranch:
    """يغطي فرع الاشتراكات في البحث (super_admin / student / filtered)."""

    def test_search_subscriptions_super_admin(self, client, app):
        sid = make_school(app)
        gid = make_grade(app, sid)
        subj = make_subject(app)
        cid = make_class(app, sid, gid, subj)
        _uid, student = _make_student(app, school_id=sid)
        plan = make_subscription_plan(app, sid, class_id=cid, name="الخطة الذهبية")
        make_subscription(app, _uid, plan, cid, status="active")
        _aid, admin = _make_super_admin(app)
        _login_as(client, admin)
        resp = client.get("/api/v1/search", query_string={"q": "الخطة الذهبية"})
        assert resp.status_code == 200
        subs = resp.get_json()["data"]["subscriptions"]
        assert len(subs) == 1
        # search items expose status embedded in subtitle ("active — 100.00 ILS")
        assert subs[0]["subtitle"].startswith("active")

    def test_search_subscriptions_student_own_only(self, client, app):
        sid = make_school(app)
        gid = make_grade(app, sid)
        subj = make_subject(app)
        cid = make_class(app, sid, gid, subj)
        _s1, s1 = _make_student(app, school_id=sid)
        _s2, s2 = _make_student(app, school_id=sid)
        plan = make_subscription_plan(app, sid, class_id=cid, name="الخطة الذهبية")
        make_subscription(app, _s1, plan, cid, status="active")
        make_subscription(app, _s2, plan, cid, status="active")
        _login_as(client, s1)
        resp = client.get("/api/v1/search", query_string={"q": "الخطة الذهبية"})
        assert resp.status_code == 200
        subs = resp.get_json()["data"]["subscriptions"]
        assert len(subs) == 1
        assert subs[0]["subtitle"].startswith("active")
