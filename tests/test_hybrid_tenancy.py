"""Tests for Hybrid Tenancy (School + Individual) feature."""

from app.extensions import db
from app.models.class_room import ClassMember, ClassRoom
from app.models.school import School
from app.models.user import User
from tests.conftest import (
    make_class,
    make_class_member,
    make_grade,
    make_individual_user,
    make_public_class,
    make_school,
    make_subject,
    make_system_school,
    make_user,
)

# ── System School ──


def test_system_school_exists(app):
    with app.app_context():
        from app.services.schools import get_or_create_system_school

        s = get_or_create_system_school()
        assert s.is_system is True
        assert "فردي" in s.name_ar


def test_system_school_idempotent(app):
    with app.app_context():
        from app.services.schools import get_or_create_system_school

        s1 = get_or_create_system_school()
        s2 = get_or_create_system_school()
        assert s1.id == s2.id


def test_system_school_has_grades(app):
    with app.app_context():
        from app.services.schools import get_or_create_system_school

        s = get_or_create_system_school()
        from app.models.school import Grade

        grades = Grade.query.filter_by(school_id=s.id).all()
        assert len(grades) == 12


# ── Individual Registration ──


def test_register_individual_success(app, client):
    resp = client.post(
        "/auth/register-individual",
        data={
            "name_ar": "طالب فردي",
            "email": "individual@test.com",
            "password": "StrongPass1!",
            "confirm": "StrongPass1!",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        u = User.query.filter_by(email="individual@test.com").first()
        assert u is not None
        assert u.is_individual is True
        assert u.is_approved is True


def test_register_individual_duplicate_email(app, client):
    with app.app_context():
        from app.services.auth import register_individual

        register_individual(email="dup@test.com", name_ar="أول", password="StrongPass1!")
    resp = client.post(
        "/auth/register-individual",
        data={
            "name_ar": "طالب",
            "email": "dup@test.com",
            "password": "StrongPass1!",
            "confirm": "StrongPass1!",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        assert User.query.filter_by(email="dup@test.com").count() == 1


def test_register_individual_weak_password(app, client):
    resp = client.post(
        "/auth/register-individual",
        data={
            "name_ar": "طالب",
            "email": "weak@test.com",
            "password": "123",
            "confirm": "123",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        assert User.query.filter_by(email="weak@test.com").first() is None


def test_register_individual_renders_form(app, client):
    resp = client.get("/auth/register-individual")
    assert resp.status_code == 200


def test_register_individual_creates_system_school_link(app, client):
    with app.app_context():
        from app.services.schools import get_or_create_system_school

        sys_school = get_or_create_system_school()
        sys_id = sys_school.id
    client.post(
        "/auth/register-individual",
        data={
            "name_ar": "طالب فردي",
            "email": "ind_link@test.com",
            "password": "StrongPass1!",
            "confirm": "StrongPass1!",
        },
        follow_redirects=True,
    )
    with app.app_context():
        u = User.query.filter_by(email="ind_link@test.com").first()
        assert u is not None
        links = [rl for rl in u.role_links if rl.school_id == sys_id]
        assert len(links) == 1


# ── Model Flags ──


def test_school_is_system_flag(app):
    with app.app_context():
        s = School(name_ar="مدرسة اختبار", is_system=True)
        db.session.add(s)
        db.session.commit()
        assert s.is_system is True
        assert s.is_individual_school is True


def test_user_is_individual_flag(app):
    with app.app_context():
        uid = make_individual_user(app)
        u = db.session.get(User, uid)
        assert u.is_individual is True


def test_classroom_is_public(app):
    with app.app_context():
        sid = make_school(app)
        gid = make_grade(app, sid)
        sub_id = make_subject(app)
        cid = make_public_class(app, sid, gid, sub_id, price=75.0)
        c = db.session.get(ClassRoom, cid)
        assert c.is_public is True
        assert float(c.price) == 75.0


def test_classroom_default_not_public(app):
    with app.app_context():
        sid = make_school(app)
        gid = make_grade(app, sid)
        sub_id = make_subject(app)
        cid = make_class(app, sid, gid, sub_id)
        c = db.session.get(ClassRoom, cid)
        assert c.is_public is False


# ── Service: is_individual_user ──


def test_is_individual_user_true(app):
    with app.app_context():
        sid = make_system_school(app)
        uid = make_individual_user(app, school_id=sid)
        u = db.session.get(User, uid)
        from app.services.schools import is_individual_user

        assert is_individual_user(u) is True


def test_is_individual_user_false_for_school_student(app):
    with app.app_context():
        sid = make_school(app)
        uid = make_user(app, role="student", school_id=sid)
        u = db.session.get(User, uid)
        from app.services.schools import is_individual_user

        assert is_individual_user(u) is False


def test_user_belongs_to_school(app):
    with app.app_context():
        sid = make_school(app)
        uid = make_user(app, role="student", school_id=sid)
        u = db.session.get(User, uid)
        assert u.belongs_to_school is True


def test_individual_user_not_belongs_to_school(app):
    with app.app_context():
        sid = make_system_school(app)
        uid = make_individual_user(app, school_id=sid)
        u = db.session.get(User, uid)
        assert u.belongs_to_school is False


# ── Public Course Catalog (service) ──


def test_get_public_classes(app):
    with app.app_context():
        sid = make_school(app)
        gid = make_grade(app, sid)
        sub_id = make_subject(app)
        uid = make_user(app, role="teacher", school_id=sid)
        make_public_class(app, sid, gid, sub_id, teacher_id=uid)
        from app.services.individual import get_public_classes

        classes = get_public_classes()
        assert any(c.subject_id == sub_id for c in classes)
        assert all(c.is_public for c in classes)


def test_get_public_classes_filters_by_subject(app):
    with app.app_context():
        sid = make_school(app)
        gid = make_grade(app, sid)
        sub_id = make_subject(app)
        sub2 = make_subject(app)
        uid = make_user(app, role="teacher", school_id=sid)
        make_public_class(app, sid, gid, sub_id, teacher_id=uid)
        make_public_class(app, sid, gid, sub2, teacher_id=uid)
        from app.services.individual import get_public_classes

        filtered = get_public_classes(subject_id=sub_id)
        assert all(c.subject_id == sub_id for c in filtered)
        assert len(filtered) >= 1


def test_non_public_class_not_returned_by_get_public_classes(app):
    with app.app_context():
        sid = make_school(app)
        gid = make_grade(app, sid)
        sub_id = make_subject(app)
        uid = make_user(app, role="teacher", school_id=sid)
        make_class(app, sid, gid, sub_id, teacher_id=uid)
        from app.services.individual import get_public_classes

        classes = get_public_classes()
        non_public = [c for c in classes if c.subject_id == sub_id]
        assert len(non_public) == 0


# ── Catalog route ──


def test_catalog_page(app, client):
    with app.app_context():
        sid = make_school(app)
        gid = make_grade(app, sid)
        sub_id = make_subject(app)
        uid = make_user(app, role="teacher", school_id=sid)
        make_public_class(app, sid, gid, sub_id, teacher_id=uid)
        sid2 = make_system_school(app)
        student_id = make_individual_user(app, school_id=sid2)
    with client.session_transaction() as sess:
        sess["_user_id"] = str(student_id)
    resp = client.get("/my/catalog")
    assert resp.status_code == 200


def test_catalog_filter_by_subject(app, client):
    with app.app_context():
        sid = make_school(app)
        gid = make_grade(app, sid)
        sub_id = make_subject(app)
        uid = make_user(app, role="teacher", school_id=sid)
        make_public_class(app, sid, gid, sub_id, teacher_id=uid)
        sid2 = make_system_school(app)
        student_id = make_individual_user(app, school_id=sid2)
    with client.session_transaction() as sess:
        sess["_user_id"] = str(student_id)
    resp = client.get(f"/my/catalog?subject_id={sub_id}")
    assert resp.status_code == 200


def test_catalog_requires_login(app, client):
    resp = client.get("/my/catalog", follow_redirects=False)
    assert resp.status_code in (302, 401)


# ── Subscribe to Public Class (service) ──


def test_subscribe_to_public_class_success(app):
    with app.app_context():
        sid = make_school(app)
        gid = make_grade(app, sid)
        sub_id = make_subject(app)
        uid = make_user(app, role="teacher", school_id=sid)
        cid = make_public_class(app, sid, gid, sub_id, teacher_id=uid, price=50.0)
        sid2 = make_system_school(app)
        student_id = make_individual_user(app, school_id=sid2)
        from app.services.individual import subscribe_to_class

        error = subscribe_to_class(student_id, cid)
        assert error is None
        m = ClassMember.query.filter_by(class_id=cid, user_id=student_id).first()
        assert m is not None
        assert m.status == "active"


def test_subscribe_duplicate_blocked(app):
    with app.app_context():
        sid = make_school(app)
        gid = make_grade(app, sid)
        sub_id = make_subject(app)
        uid = make_user(app, role="teacher", school_id=sid)
        cid = make_public_class(app, sid, gid, sub_id, teacher_id=uid)
        sid2 = make_system_school(app)
        student_id = make_individual_user(app, school_id=sid2)
        from app.services.individual import subscribe_to_class

        subscribe_to_class(student_id, cid)
        error = subscribe_to_class(student_id, cid)
        assert error is not None


def test_subscribe_non_public_blocked(app):
    with app.app_context():
        sid = make_school(app)
        gid = make_grade(app, sid)
        sub_id = make_subject(app)
        uid = make_user(app, role="teacher", school_id=sid)
        cid = make_class(app, sid, gid, sub_id, teacher_id=uid)
        sid2 = make_system_school(app)
        student_id = make_individual_user(app, school_id=sid2)
        from app.services.individual import subscribe_to_class

        error = subscribe_to_class(student_id, cid)
        assert error is not None


def test_subscribe_nonexistent_class_blocked(app):
    with app.app_context():
        sid2 = make_system_school(app)
        student_id = make_individual_user(app, school_id=sid2)
        from app.services.individual import subscribe_to_class

        error = subscribe_to_class(student_id, 999999)
        assert error is not None


# ── Subscribe route ──


def test_subscribe_route_success(app, client):
    with app.app_context():
        sid = make_school(app)
        gid = make_grade(app, sid)
        sub_id = make_subject(app)
        uid = make_user(app, role="teacher", school_id=sid)
        cid = make_public_class(app, sid, gid, sub_id, teacher_id=uid, price=50.0)
        sid2 = make_system_school(app)
        student_id = make_individual_user(app, school_id=sid2)
    with client.session_transaction() as sess:
        sess["_user_id"] = str(student_id)
    resp = client.post(f"/my/catalog/{cid}/subscribe", follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        m = ClassMember.query.filter_by(class_id=cid, user_id=student_id).first()
        assert m is not None
        assert m.status == "active"


def test_subscribe_route_duplicate(app, client):
    with app.app_context():
        sid = make_school(app)
        gid = make_grade(app, sid)
        sub_id = make_subject(app)
        uid = make_user(app, role="teacher", school_id=sid)
        cid = make_public_class(app, sid, gid, sub_id, teacher_id=uid)
        sid2 = make_system_school(app)
        student_id = make_individual_user(app, school_id=sid2)
    with client.session_transaction() as sess:
        sess["_user_id"] = str(student_id)
    client.post(f"/my/catalog/{cid}/subscribe", follow_redirects=True)
    resp = client.post(f"/my/catalog/{cid}/subscribe", follow_redirects=True)
    assert resp.status_code == 200


# ── My Courses ──


def test_my_courses_empty(app, client):
    with app.app_context():
        sid2 = make_system_school(app)
        student_id = make_individual_user(app, school_id=sid2)
    with client.session_transaction() as sess:
        sess["_user_id"] = str(student_id)
    resp = client.get("/my/courses")
    assert resp.status_code == 200


def test_my_courses_with_classes(app, client):
    with app.app_context():
        sid = make_school(app)
        gid = make_grade(app, sid)
        sub_id = make_subject(app)
        uid = make_user(app, role="teacher", school_id=sid)
        cid = make_public_class(app, sid, gid, sub_id, teacher_id=uid)
        sid2 = make_system_school(app)
        student_id = make_individual_user(app, school_id=sid2)
        make_class_member(app, cid, student_id)
    with client.session_transaction() as sess:
        sess["_user_id"] = str(student_id)
    resp = client.get("/my/courses")
    assert resp.status_code == 200


def test_get_student_classes(app):
    with app.app_context():
        sid = make_school(app)
        gid = make_grade(app, sid)
        sub_id = make_subject(app)
        uid = make_user(app, role="teacher", school_id=sid)
        cid = make_public_class(app, sid, gid, sub_id, teacher_id=uid)
        sid2 = make_system_school(app)
        student_id = make_individual_user(app, school_id=sid2)
        make_class_member(app, cid, student_id)
        from app.services.individual import get_student_classes

        memberships = get_student_classes(student_id)
        assert len(memberships) == 1
        assert memberships[0].class_id == cid


def test_get_student_classes_empty(app):
    with app.app_context():
        sid2 = make_system_school(app)
        student_id = make_individual_user(app, school_id=sid2)
        from app.services.individual import get_student_classes

        memberships = get_student_classes(student_id)
        assert len(memberships) == 0


# ── Access Control ──


def test_individual_can_view_subscribed_class_content(app, client):
    with app.app_context():
        sid = make_school(app)
        gid = make_grade(app, sid)
        sub_id = make_subject(app)
        teacher_id = make_user(app, role="teacher", school_id=sid)
        cid = make_public_class(app, sid, gid, sub_id, teacher_id=teacher_id)
        sid2 = make_system_school(app)
        student_id = make_individual_user(app, school_id=sid2)
        make_class_member(app, cid, student_id)
    with client.session_transaction() as sess:
        sess["_user_id"] = str(student_id)
    resp = client.get(f"/classes/{cid}/lessons")
    assert resp.status_code == 200


def test_individual_cannot_view_unsubscribed_class(app, client):
    with app.app_context():
        sid = make_school(app)
        gid = make_grade(app, sid)
        sub_id = make_subject(app)
        teacher_id = make_user(app, role="teacher", school_id=sid)
        cid = make_public_class(app, sid, gid, sub_id, teacher_id=teacher_id)
        sid2 = make_system_school(app)
        student_id = make_individual_user(app, school_id=sid2)
    with client.session_transaction() as sess:
        sess["_user_id"] = str(student_id)
    resp = client.get(f"/classes/{cid}/lessons")
    assert resp.status_code in (302, 403)


# ── join_class_individual service ──


def test_join_class_individual_success(app):
    with app.app_context():
        sid = make_school(app)
        gid = make_grade(app, sid)
        sub_id = make_subject(app)
        uid = make_user(app, role="teacher", school_id=sid)
        cid = make_public_class(app, sid, gid, sub_id, teacher_id=uid)
        sid2 = make_system_school(app)
        student_id = make_individual_user(app, school_id=sid2)
        from app.services.schools import join_class_individual

        member, error = join_class_individual(student_id, cid)
        assert error is None
        assert member is not None
        assert member.status == "active"


def test_join_class_individual_non_public(app):
    with app.app_context():
        sid = make_school(app)
        gid = make_grade(app, sid)
        sub_id = make_subject(app)
        uid = make_user(app, role="teacher", school_id=sid)
        cid = make_class(app, sid, gid, sub_id, teacher_id=uid)
        sid2 = make_system_school(app)
        student_id = make_individual_user(app, school_id=sid2)
        from app.services.schools import join_class_individual

        member, error = join_class_individual(student_id, cid)
        assert error is not None
        assert member is None


def test_join_class_individual_duplicate(app):
    with app.app_context():
        sid = make_school(app)
        gid = make_grade(app, sid)
        sub_id = make_subject(app)
        uid = make_user(app, role="teacher", school_id=sid)
        cid = make_public_class(app, sid, gid, sub_id, teacher_id=uid)
        sid2 = make_system_school(app)
        student_id = make_individual_user(app, school_id=sid2)
        from app.services.schools import join_class_individual

        join_class_individual(student_id, cid)
        member, error = join_class_individual(student_id, cid)
        assert error is not None
        assert member is None


def test_join_class_individual_nonexistent_user(app):
    with app.app_context():
        sid = make_school(app)
        gid = make_grade(app, sid)
        sub_id = make_subject(app)
        uid = make_user(app, role="teacher", school_id=sid)
        cid = make_public_class(app, sid, gid, sub_id, teacher_id=uid)
        from app.services.schools import join_class_individual

        member, error = join_class_individual(999999, cid)
        assert error is not None
        assert member is None


def test_join_class_individual_nonexistent_class(app):
    with app.app_context():
        sid2 = make_system_school(app)
        student_id = make_individual_user(app, school_id=sid2)
        from app.services.schools import join_class_individual

        member, error = join_class_individual(student_id, 999999)
        assert error is not None
        assert member is None


# ── Context Helpers ──


def test_is_individual_true(app):
    with app.app_context():
        sid2 = make_system_school(app)
        student_id = make_individual_user(app, school_id=sid2)
        u = db.session.get(User, student_id)
        assert u.is_individual is True
        assert u.belongs_to_school is False


def test_is_individual_false_for_school_student(app):
    with app.app_context():
        sid = make_school(app)
        student_id = make_user(app, role="student", school_id=sid)
        u = db.session.get(User, student_id)
        assert u.is_individual is False
        assert u.belongs_to_school is True


# ── Dual Access: School Student Unchanged ──


def test_school_student_dashboard(app, client):
    with app.app_context():
        sid = make_school(app)
        student_id = make_user(app, role="student", school_id=sid)
    with client.session_transaction() as sess:
        sess["_user_id"] = str(student_id)
    resp = client.get("/auth/dashboard")
    assert resp.status_code == 200


def test_school_student_classes_member(app):
    with app.app_context():
        sid = make_school(app)
        gid = make_grade(app, sid)
        sub_id = make_subject(app)
        teacher_id = make_user(app, role="teacher", school_id=sid)
        student_id = make_user(app, role="student", school_id=sid)
        cid = make_class(app, sid, gid, sub_id, teacher_id=teacher_id)
        make_class_member(app, cid, student_id)
        m = ClassMember.query.filter_by(class_id=cid, user_id=student_id).first()
        assert m is not None
        assert m.status == "active"


# ── Subscription capacity limits ──


def test_subscribe_respects_capacity(app):
    with app.app_context():
        sid = make_school(app)
        gid = make_grade(app, sid)
        sub_id = make_subject(app)
        uid = make_user(app, role="teacher", school_id=sid)
        cid = make_public_class(app, sid, gid, sub_id, teacher_id=uid)
        c = db.session.get(ClassRoom, cid)
        c.max_students = 1
        db.session.commit()
        sid2 = make_system_school(app)
        s1 = make_individual_user(app, school_id=sid2)
        s2 = make_individual_user(app, school_id=sid2)
        from app.services.individual import subscribe_to_class

        error1 = subscribe_to_class(s1, cid)
        assert error1 is None
        error2 = subscribe_to_class(s2, cid)
        assert error2 is not None
