"""اختبارات تكامل — بوابة ولي الأمر (family blueprint HTTP routes)."""

from tests.conftest import (
    make_class,
    make_class_member,
    make_family_link,
    make_grade,
    make_school,
    make_subject,
    make_user,
)


def test_parent_index_page_renders(app, client):
    """صفحة بوابة ولي الأمر تعرض الأبناء."""
    school_id = make_school(app)
    parent_id = make_user(app, role="parent", school_id=school_id)
    student_id = make_user(app, role="student", school_id=school_id)
    with app.app_context():
        make_family_link(app, parent_id, student_id)
    with client.session_transaction() as s:
        s["_user_id"] = str(parent_id)
    resp = client.get("/family/")
    assert resp.status_code == 200


def test_student_progress_page_renders(app, client):
    """صفحة تقدم الطالب لولي الأمر."""
    school_id = make_school(app)
    parent_id = make_user(app, role="parent", school_id=school_id)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id)
    with app.app_context():
        make_family_link(app, parent_id, student_id)
        make_class_member(app, class_id, student_id)
    with client.session_transaction() as s:
        s["_user_id"] = str(parent_id)
    resp = client.get(f"/family/children/{student_id}/progress")
    assert resp.status_code == 200


def test_parent_cannot_view_unlinked_child(app, client):
    """ولي الأمر لا يستطيع تقدم طالب غير مرتبط."""
    school_id = make_school(app)
    parent_id = make_user(app, role="parent", school_id=school_id)
    student_id = make_user(app, role="student", school_id=school_id)
    with client.session_transaction() as s:
        s["_user_id"] = str(parent_id)
    resp = client.get(f"/family/children/{student_id}/progress")
    assert resp.status_code in (302, 403, 404)
