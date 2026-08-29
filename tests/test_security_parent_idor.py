"""اختبارات أمنية — منع IDOR في واجهة ولي الأمر."""

from tests.conftest import make_family_link, make_school, make_user


def test_parent_cannot_view_other_parent_child(app, client):
    """ولي أمر لا يستطيع الوصول لتقدم طالب مرتبط بوحد أمر آخر."""
    school_id = make_school(app)
    parent1 = make_user(app, role="parent", school_id=school_id)
    parent2 = make_user(app, role="parent", school_id=school_id)
    student1 = make_user(app, role="student", school_id=school_id)
    student2 = make_user(app, role="student", school_id=school_id)
    with app.app_context():
        make_family_link(app, parent1, student1)
        make_family_link(app, parent2, student2)
    with client.session_transaction() as s:
        s["_user_id"] = str(parent1)
    resp = client.get(f"/family/children/{student2}/progress")
    assert resp.status_code in (302, 403, 404)


def test_unauthenticated_family_access_redirects(app, client):
    """غير مسجّل الدخول لا يصل لبوابة الأسرة."""
    resp = client.get("/family/", follow_redirects=False)
    assert resp.status_code == 302


def test_student_cannot_access_parent_portal(app, client):
    """الطالب لا يستطيع الوصول لبوابة ولي الأمر."""
    school_id = make_school(app)
    student_id = make_user(app, role="student", school_id=school_id)
    with client.session_transaction() as s:
        s["_user_id"] = str(student_id)
    resp = client.get("/family/", follow_redirects=False)
    assert resp.status_code in (302, 403)
