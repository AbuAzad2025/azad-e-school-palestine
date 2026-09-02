"""Shared fixtures for security test suite.

Provides:
  - app / client (session-scoped for performance)
  - Persona factory: make_persona(app, role, school_id, **kw) → (user_id, client)
  - Two schools (school_a, school_b) for cross-tenant isolation tests
  - Pre-built persona fixtures for all 6 roles
"""

from __future__ import annotations

import uuid

import pytest
from app import create_app
from app.core.security import hash_password
from app.extensions import db as _db
from app.models.class_room import ClassMember, ClassRoom
from app.models.family import FamilyLink
from app.models.school import Grade, School, Subject
from app.models.user import User, UserApprovalStatus, UserRole, UserRoleLink

# ---------------------------------------------------------------------------
# App & DB
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def app():
    a = create_app()
    a.config["TESTING"] = True
    a.config["WTF_CSRF_ENABLED"] = False
    a.config["EMAIL_ENABLED"] = False
    a.config["TALISMAN_ENABLED"] = False
    a.config["SESSION_COOKIE_SECURE"] = False
    a.config["LOGIN_MAX_ATTEMPTS"] = 5
    a.config["LOGIN_LOCKOUT_DURATION"] = 900
    with a.app_context():
        from sqlalchemy import text

        _db.session.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
        _db.session.commit()
        _db.create_all()
    yield a


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def _clean_db(app):
    """Truncate all tables between tests to keep tests isolated."""
    yield
    with app.app_context():
        from sqlalchemy import inspect, text

        inspector = inspect(_db.engine)
        tables = inspector.get_table_names(schema="public")
        tables = [t for t in tables if t != "alembic_version"]
        if tables:
            _db.session.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
            _db.session.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return uuid.uuid4().hex[:10]


def _email() -> str:
    return f"u-{_uid()}@test.com"


def _create_user(app, role: str, school_id: int | None = None, **kw):
    """Create a user in the DB and return user_id."""
    with app.app_context():
        u = User(
            email=kw.get("email", _email()),
            name_ar=kw.get("name_ar", f"User {_uid()}"),
            role=UserRole(role),
            password_hash=hash_password(kw.get("password", "TestPass123!")),
            approval_status=UserApprovalStatus.approved,
            is_active=True,
            is_individual=kw.get("is_individual", False),
        )
        _db.session.add(u)
        _db.session.commit()
        if school_id:
            rl = UserRoleLink(user_id=u.id, school_id=school_id, role=UserRole(role))
            _db.session.add(rl)
            _db.session.commit()
        return u.id


def _login_client(client, email, password="TestPass123!"):
    """Log in via the test client. Returns the response."""
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def make_persona(app, role, school_id=None, **kw):
    """Create a user and a fresh client, return (user_id, client).

    Each persona gets its own test client to avoid session conflicts.
    """
    email = kw.pop("email", _email())
    password = kw.pop("password", "TestPass123!")
    uid = _create_user(app, role, school_id=school_id, email=email, password=password, **kw)
    new_client = app.test_client()
    _login_client(new_client, email, password)
    return uid, new_client


# ---------------------------------------------------------------------------
# Two schools for cross-tenant isolation
# ---------------------------------------------------------------------------

@pytest.fixture()
def school_a(app):
    with app.app_context():
        s = School(
            name_ar=f"مدرسة أ {_uid()}",
            name_en=f"School A {_uid()}",
            domain=f"a-{_uid()}.test.org",
            join_code=f"A-{_uid()[:6]}",
        )
        _db.session.add(s)
        _db.session.commit()
        return s.id


@pytest.fixture()
def school_b(app):
    with app.app_context():
        s = School(
            name_ar=f"مدرسة ب {_uid()}",
            name_en=f"School B {_uid()}",
            domain=f"b-{_uid()}.test.org",
            join_code=f"B-{_uid()[:6]}",
        )
        _db.session.add(s)
        _db.session.commit()
        return s.id


@pytest.fixture()
def grade_a(app, school_a):
    with app.app_context():
        g = Grade(school_id=school_a, grade_level=10, name_ar="العاشر")
        _db.session.add(g)
        _db.session.commit()
        return g.id


@pytest.fixture()
def grade_b(app, school_b):
    with app.app_context():
        g = Grade(school_id=school_b, grade_level=10, name_ar="العاشر")
        _db.session.add(g)
        _db.session.commit()
        return g.id


@pytest.fixture()
def subject(app):
    with app.app_context():
        s = Subject(name_ar=f"مادة {_uid()}")
        _db.session.add(s)
        _db.session.commit()
        return s.id


@pytest.fixture()
def class_a(app, school_a, grade_a, subject):
    with app.app_context():
        c = ClassRoom(
            school_id=school_a,
            grade_id=grade_a,
            subject_id=subject,
            join_code=f"CA-{_uid()[:6]}",
            name=f"صف A {_uid()}",
        )
        _db.session.add(c)
        _db.session.commit()
        return c.id


@pytest.fixture()
def class_b(app, school_b, grade_b, subject):
    with app.app_context():
        c = ClassRoom(
            school_id=school_b,
            grade_id=grade_b,
            subject_id=subject,
            join_code=f"CB-{_uid()[:6]}",
            name=f"صف B {_uid()}",
        )
        _db.session.add(c)
        _db.session.commit()
        return c.id


@pytest.fixture()
def lesson_a(app, class_a):
    with app.app_context():
        from app.models.content import Lesson

        lesson = Lesson(
            class_id=class_a,
            title=f"درس اختبار {_uid()}",
            status="published",
            sort_order=1,
        )
        _db.session.add(lesson)
        _db.session.commit()
        return lesson.id


# ---------------------------------------------------------------------------
# Persona fixtures — each gets its own test client
# ---------------------------------------------------------------------------

@pytest.fixture()
def superadmin_persona(app, school_a):
    return make_persona(app, "super_admin", school_id=school_a, name_ar="المدير العام")


@pytest.fixture()
def school_admin_a_persona(app, school_a):
    return make_persona(app, "school_admin", school_id=school_a, name_ar="مدير مدرسة أ")


@pytest.fixture()
def school_admin_b_persona(app, school_b):
    return make_persona(app, "school_admin", school_id=school_b, name_ar="مدير مدرسة ب")


@pytest.fixture()
def teacher_a_persona(app, school_a, class_a):
    uid, c = make_persona(app, "teacher", school_id=school_a, name_ar="معلم أ")
    with app.app_context():
        cr = ClassRoom.query.get(class_a)
        cr.teacher_id = uid
        _db.session.commit()
    return uid, c


@pytest.fixture()
def teacher_b_persona(app, school_b, class_b):
    uid, c = make_persona(app, "teacher", school_id=school_b, name_ar="معلم ب")
    with app.app_context():
        cr = ClassRoom.query.get(class_b)
        cr.teacher_id = uid
        _db.session.commit()
    return uid, c


@pytest.fixture()
def student_a_persona(app, school_a, class_a):
    uid, c = make_persona(app, "student", school_id=school_a, name_ar="طالب أ")
    with app.app_context():
        m = ClassMember(class_id=class_a, user_id=uid, status="active")
        _db.session.add(m)
        _db.session.commit()
    return uid, c


@pytest.fixture()
def student_b_persona(app, school_b, class_b):
    uid, c = make_persona(app, "student", school_id=school_b, name_ar="طالب ب")
    with app.app_context():
        m = ClassMember(class_id=class_b, user_id=uid, status="active")
        _db.session.add(m)
        _db.session.commit()
    return uid, c


@pytest.fixture()
def student_unlinked_persona(app):
    return make_persona(app, "student", name_ar="طالب فردي", is_individual=True)


@pytest.fixture()
def parent_a_persona(app, school_a, student_a_persona):
    student_id = student_a_persona[0]
    parent_id, c = make_persona(app, "parent", school_id=school_a, name_ar="ولي أمر")
    with app.app_context():
        fl = FamilyLink(parent_id=parent_id, student_id=student_id, status="active")
        _db.session.add(fl)
        _db.session.commit()
    return parent_id, c
