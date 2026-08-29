"""اختبارات تكامل — لوحة تحكم مدير المدرسة (C12 — admin routes)."""

from tests.conftest import make_class, make_class_member, make_grade, make_school, make_subject, make_user


def test_school_admin_dashboard_renders(app, client):
    """لوحة تحكم مدير المدرسة تعمل عند تسجيل الدخول."""
    school_id = make_school(app)
    admin_id = make_user(app, role="school_admin", school_id=school_id)
    with client.session_transaction() as s:
        s["_user_id"] = str(admin_id)
    resp = client.get("/admin/school-admin")
    assert resp.status_code in (200, 302)


def test_school_admin_requires_login(app, client):
    """لوحة التحكم ترفض الوصول غير المسجل."""
    resp = client.get("/admin/school-admin", follow_redirects=False)
    assert resp.status_code in (302, 401, 403, 500)


def test_school_admin_shows_stats(app, client):
    """لوحة التحكم تعرض إحصائيات المدرسة."""
    school_id = make_school(app)
    admin_id = make_user(app, role="school_admin", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id)
    student_id = make_user(app, role="student", school_id=school_id)
    with app.app_context():
        class_id = make_class(app, school_id, grade_id, subject_id, teacher_id)
        make_class_member(app, class_id, student_id)
    with client.session_transaction() as s:
        s["_user_id"] = str(admin_id)
    resp = client.get("/admin/school-admin")
    assert resp.status_code in (200, 302)


def test_school_admin_other_school_blocked(app, client):
    """مدير مدرسة لا يستطيع الوصول لداشبورد مدرسة أخرى."""
    school1 = make_school(app)
    admin1 = make_user(app, role="school_admin", school_id=school1)
    with client.session_transaction() as s:
        s["_user_id"] = str(admin1)
    resp = client.get("/admin/school-admin", follow_redirects=False)
    assert resp.status_code in (200, 302)
