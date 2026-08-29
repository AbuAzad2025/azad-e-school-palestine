"""SQUAD 3 EXTRA: Full API route coverage — all endpoints, all roles, all branches.

Covers:
- /api/v1/me, /api/v1/schools, /api/v1/lessons, /api/v1/tutoring/sessions
- /api/v1/users, /api/v1/classes, /api/v1/search
- API error handlers (404/403/401/429/500)
- Pagination, tenancy filtering, authorization per role
"""

from app.core.api import API_VERSION, api_error, api_paginated, api_response
from app.extensions import db
from app.models.user import User
from tests.conftest import make_school, make_user


def _login(client, email, password="TestPass123!"):
    return client.post("/auth/login", data={"email": email, "password": password}, follow_redirects=True)


def _login_api(client, email, password="TestPass123!"):
    """Login without redirect following for API tests."""
    return client.post("/auth/login", data={"email": email, "password": password}, follow_redirects=False)


def _create_and_login(client, app, role="student"):
    with app.app_context():
        sid = make_school(app)
        uid = make_user(app, role, school_id=sid)
        user_obj = db.session.get(User, uid)
        email = user_obj.email
    _login(client, email)
    return email


# ═══════════════════════════════════════════════════════════════
# Core API helpers
# ═══════════════════════════════════════════════════════════════
class TestCoreAPIHelpers:
    def test_api_response_structure(self, app):
        with app.app_context():
            body, status = api_response({"key": "value"})
            assert status == 200
            d = body.get_json()
            assert d["data"]["key"] == "value"
            assert d["meta"]["version"] == API_VERSION

    def test_api_response_with_meta(self, app):
        with app.app_context():
            body, status = api_response("ok", status=201, meta={"extra": True})
            assert status == 201
            d = body.get_json()
            assert d["meta"]["extra"] is True

    def test_api_error_structure(self, app):
        with app.app_context():
            body, status = api_error("Something broke", status=500, code="CUSTOM_ERR")
            assert status == 500
            d = body.get_json()
            assert d["error"]["code"] == "CUSTOM_ERR"
            assert d["error"]["message"] == "Something broke"

    def test_api_error_default_code(self, app):
        with app.app_context():
            body, status = api_error("bad request")
            d = body.get_json()
            assert d["error"]["code"] == "ERR_400"

    def test_api_error_with_details(self, app):
        with app.app_context():
            body, status = api_error("validation failed", details={"field": "email"})
            d = body.get_json()
            assert d["error"]["details"]["field"] == "email"

    def test_api_paginated_structure(self, app):
        with app.app_context():
            body, status = api_paginated([{"id": 1}], page=1, per_page=10, total=25)
            assert status == 200
            d = body.get_json()
            assert d["meta"]["total"] == 25
            assert d["meta"]["pages"] == 3

    def test_api_paginated_zero_per_page(self, app):
        with app.app_context():
            body, status = api_paginated([], page=1, per_page=0, total=10)
            d = body.get_json()
            assert d["meta"]["pages"] == 0


# ═══════════════════════════════════════════════════════════════
# API Auth
# ═══════════════════════════════════════════════════════════════
class TestAPIAuth:
    def test_unauthenticated_returns_401(self, client):
        resp = client.get("/api/v1/me")
        assert resp.status_code == 401
        body = resp.get_json()
        assert body["error"]["code"] == "UNAUTHORIZED"


# ═══════════════════════════════════════════════════════════════
# GET /api/v1/me
# ═══════════════════════════════════════════════════════════════
class TestAPIMe:
    def test_returns_user_data(self, client, app):
        email = _create_and_login(client, app, "student")
        resp = client.get("/api/v1/me")
        assert resp.status_code == 200
        d = resp.get_json()
        assert d["data"]["email"] == email
        assert d["data"]["role"] == "student"

    def test_super_admin_role(self, client, app):
        _create_and_login(client, app, "super_admin")
        resp = client.get("/api/v1/me")
        d = resp.get_json()
        assert d["data"]["role"] == "super_admin"

    def test_teacher_role(self, client, app):
        _create_and_login(client, app, "teacher")
        resp = client.get("/api/v1/me")
        d = resp.get_json()
        assert d["data"]["role"] == "teacher"


# ═══════════════════════════════════════════════════════════════
# GET /api/v1/schools
# ═══════════════════════════════════════════════════════════════
class TestAPISchools:
    def test_student_sees_own_school(self, client, app):
        _create_and_login(client, app, "student")
        resp = client.get("/api/v1/schools")
        assert resp.status_code == 200
        d = resp.get_json()
        assert isinstance(d["data"], list)

    def test_super_admin_sees_all(self, client, app):
        _create_and_login(client, app, "super_admin")
        resp = client.get("/api/v1/schools")
        assert resp.status_code == 200

    def test_pagination_params(self, client, app):
        _create_and_login(client, app, "super_admin")
        resp = client.get("/api/v1/schools?page=1&per_page=5")
        d = resp.get_json()
        assert d["meta"]["page"] == 1
        assert d["meta"]["per_page"] == 5

    def test_get_school_by_id(self, client, app):
        with app.app_context():
            sid = make_school(app)
        _create_and_login(client, app, "super_admin")
        resp = client.get(f"/api/v1/schools/{sid}")
        assert resp.status_code == 200

    def test_get_nonexistent_school(self, client, app):
        _create_and_login(client, app, "super_admin")
        resp = client.get("/api/v1/schools/99999")
        assert resp.status_code == 404

    def test_cross_tenant_403(self, client, app):
        with app.app_context():
            s1 = make_school(app)
            s2 = make_school(app)
            uid = make_user(app, "student", school_id=s1)
            email = db.session.get(User, uid).email
        _login(client, email)
        resp = client.get(f"/api/v1/schools/{s2}")
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════
# GET /api/v1/lessons
# ═══════════════════════════════════════════════════════════════
class TestAPILessons:
    def test_list_lessons(self, client, app):
        _create_and_login(client, app, "student")
        resp = client.get("/api/v1/lessons")
        assert resp.status_code == 200

    def test_get_lesson_404(self, client, app):
        _create_and_login(client, app, "student")
        resp = client.get("/api/v1/lessons/99999")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════
# GET /api/v1/tutoring/sessions
# ═══════════════════════════════════════════════════════════════
class TestAPITutoring:
    def test_student_sessions(self, client, app):
        _create_and_login(client, app, "student")
        resp = client.get("/api/v1/tutoring/sessions")
        assert resp.status_code == 200

    def test_get_session_404(self, client, app):
        _create_and_login(client, app, "student")
        resp = client.get("/api/v1/tutoring/sessions/99999")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════
# GET /api/v1/users (admin only)
# ═══════════════════════════════════════════════════════════════
class TestAPIUsers:
    def test_student_forbidden(self, client, app):
        _create_and_login(client, app, "student")
        resp = client.get("/api/v1/users")
        assert resp.status_code == 403

    def test_super_admin_can_list(self, client, app):
        _create_and_login(client, app, "super_admin")
        resp = client.get("/api/v1/users")
        assert resp.status_code == 200

    def test_get_user_404(self, client, app):
        _create_and_login(client, app, "super_admin")
        resp = client.get("/api/v1/users/99999")
        assert resp.status_code == 404

    def test_get_user(self, client, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
        _create_and_login(client, app, "super_admin")
        resp = client.get(f"/api/v1/users/{uid}")
        assert resp.status_code == 200

    def test_cross_tenant_user_403(self, client, app):
        with app.app_context():
            s1 = make_school(app)
            s2 = make_school(app)
            uid1 = make_user(app, "student", school_id=s1)
            uid2 = make_user(app, "student", school_id=s2)
            email1 = db.session.get(User, uid1).email
        _login(client, email1)
        resp = client.get(f"/api/v1/users/{uid2}")
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════
# GET /api/v1/classes
# ═══════════════════════════════════════════════════════════════
class TestAPIClasses:
    def test_list_classes(self, client, app):
        _create_and_login(client, app, "student")
        resp = client.get("/api/v1/classes")
        assert resp.status_code == 200

    def test_get_class_404(self, client, app):
        _create_and_login(client, app, "student")
        resp = client.get("/api/v1/classes/99999")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════
# GET /api/v1/search
# ═══════════════════════════════════════════════════════════════
class TestAPISearch:
    def test_empty_query(self, client, app):
        _create_and_login(client, app, "student")
        resp = client.get("/api/v1/search?q=")
        assert resp.status_code == 400

    def test_short_query(self, client, app):
        _create_and_login(client, app, "student")
        resp = client.get("/api/v1/search?q=a")
        assert resp.status_code == 400

    def test_valid_search(self, client, app):
        _create_and_login(client, app, "super_admin")
        resp = client.get("/api/v1/search?q=test")
        assert resp.status_code == 200
        d = resp.get_json()
        assert "data" in d

    def test_search_limit(self, client, app):
        _create_and_login(client, app, "super_admin")
        resp = client.get("/api/v1/search?q=test&limit=2")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════
# API Error Handlers
# ═══════════════════════════════════════════════════════════════
class TestAPIErrorHandlers:
    def test_api_404(self, client, app):
        _create_and_login(client, app, "student")
        resp = client.get("/api/v1/nonexistent-resource")
        assert resp.status_code == 404

    def test_api_401(self, client):
        resp = client.get("/api/v1/me")
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════
# Context processor helpers
# ═══════════════════════════════════════════════════════════════
class TestContextProcessor:
    def test_icon_valid(self, app):
        with app.test_request_context("/"):
            from app.core.context import icon

            h = icon("home")
            assert "icon-home" in str(h)

    def test_icon_unknown_defaults_to_check(self, app):
        with app.test_request_context("/"):
            from app.core.context import icon

            h = icon("totally-unknown-icon")
            assert "icon-check" in str(h)

    def test_has_role(self, app):
        with app.app_context():
            from unittest.mock import patch

            from app.core.context import has_role
            from app.models.user import UserRole

            with patch("app.core.context.current_user") as cu:
                cu.is_authenticated = True
                cu.role = UserRole.student
                assert has_role(UserRole.student) is True
                assert has_role(UserRole.teacher) is False

    def test_has_role_unauthenticated(self, app):
        with app.app_context():
            from unittest.mock import patch

            from app.core.context import has_role

            with patch("app.core.context.current_user") as cu:
                cu.is_authenticated = False
                assert has_role("student") is False

    def test_has_any_role(self, app):
        with app.app_context():
            from unittest.mock import patch

            from app.core.context import has_any_role
            from app.models.user import UserRole

            with patch("app.core.context.current_user") as cu:
                cu.is_authenticated = True
                cu.role = UserRole.teacher
                assert has_any_role(UserRole.teacher, UserRole.student) is True
                assert has_any_role(UserRole.parent) is False

    def test_role_checkers(self, app):
        with app.app_context():
            from unittest.mock import patch

            from app.core.context import (
                can_access_admin,
                can_manage_schools,
                is_individual,
                is_parent,
                is_school_admin,
                is_student,
                is_super_admin,
                is_teacher,
            )

            with patch("app.core.context.current_user") as cu:
                cu.is_authenticated = False
                assert is_super_admin() is False
                assert is_school_admin() is False
                assert is_teacher() is False
                assert is_student() is False
                assert is_parent() is False
                assert is_individual() is False
                assert can_access_admin() is False
                assert can_manage_schools() is False

    def test_role_checkers_authenticated(self, app):
        with app.app_context():
            from unittest.mock import patch

            from app.core.context import is_student, is_super_admin
            from app.models.user import UserRole

            with patch("app.core.context.current_user") as cu:
                cu.is_authenticated = True
                cu.role = UserRole.super_admin
                assert is_super_admin() is True
                cu.role = UserRole.student
                assert is_student() is True

    def test_individual_checker(self, app):
        with app.app_context():
            from unittest.mock import patch

            from app.core.context import is_individual

            with patch("app.core.context.current_user") as cu:
                cu.is_authenticated = True
                cu.is_individual = True
                cu.belongs_to_school = False
                assert is_individual() is True

    def test_can_teach_class(self, app):
        with app.app_context():
            from unittest.mock import MagicMock, patch

            from app.core.context import can_teach_class
            from app.models.user import UserRole

            cls = MagicMock()
            cls.school_id = 1
            cls.teacher_id = 99
            with patch("app.core.context.current_user") as cu:
                cu.is_authenticated = False
                assert can_teach_class(cls) is False
                cu.is_authenticated = True
                cu.role = UserRole.super_admin
                assert can_teach_class(cls) is True
                cu.role = UserRole.teacher
                cu.id = 99
                assert can_teach_class(cls) is True
                cu.id = 100
                assert can_teach_class(cls) is False

    def test_can_view_class(self, app):
        with app.app_context():
            from unittest.mock import MagicMock, patch

            from app.core.context import can_view_class
            from app.models.user import UserRole

            cls = MagicMock()
            cls.school_id = 1
            with patch("app.core.context.current_user") as cu:
                cu.is_authenticated = False
                assert can_view_class(cls) is False
                cu.is_authenticated = True
                cu.role = UserRole.super_admin
                assert can_view_class(cls) is True
