"""اختبارات C1 — روابط الأسرة (generate_link_code, link_parent, is_parent_of, remove_link)."""

from app.extensions import db
from app.models.family import FamilyLinkCode
from tests.conftest import _uid, make_family_link, make_school, make_user


def test_generate_link_code(app):
    """إنشاء رمز ربط لطالب."""
    from app.services.family import generate_link_code

    school_id = make_school(app)
    sid = make_user(app, role="student", school_id=school_id)
    with app.app_context():
        code, err = generate_link_code(sid)
        assert code is not None
        assert err is None
        assert len(code) == 8


def test_generate_link_code_rejects_non_student(app):
    """رفض إنشاء رمز لمستخدم ليس طالباً."""
    from app.services.family import generate_link_code

    school_id = make_school(app)
    tid = make_user(app, role="teacher", school_id=school_id)
    with app.app_context():
        code, err = generate_link_code(tid)
        assert code is None
        assert "طالب" in err


def test_link_parent_success(app):
    """ربط ولي أمر بالطالب عبر الرمز."""
    from app.services.family import link_parent

    school_id = make_school(app)
    parent_id = make_user(app, role="parent", school_id=school_id)
    student_id = make_user(app, role="student", school_id=school_id)
    with app.app_context():
        code = f"LK-{_uid()[:6]}"
        db.session.add(FamilyLinkCode(student_id=student_id, code=code))
        db.session.commit()
        result, err = link_parent(parent_id, code)
        assert result is not None, f"link_parent failed: {err}"
        assert err is None
        assert result.status == "active"
        assert result.parent_id == parent_id
        assert result.student_id == student_id


def test_link_parent_invalid_code(app):
    """رفض ربط برمز غير صالح."""
    from app.services.family import link_parent

    school_id = make_school(app)
    parent_id = make_user(app, role="parent", school_id=school_id)
    with app.app_context():
        result, err = link_parent(parent_id, "FAKECODE")
        assert result is None
        assert "صالح" in err


def test_link_parent_duplicate_blocked(app):
    """منع الربط المكرر بالطالب."""
    from app.services.family import generate_link_code, link_parent

    school_id = make_school(app)
    parent_id = make_user(app, role="parent", school_id=school_id)
    student_id = make_user(app, role="student", school_id=school_id)
    with app.app_context():
        code, _ = generate_link_code(student_id)
        link_parent(parent_id, code)
        code2, _ = generate_link_code(student_id)
        result, err = link_parent(parent_id, code2)
        assert result is None
        assert "مسبقاً" in err


def test_is_parent_of(app):
    """التحقق من أن ولي الأمر مرتبط بالطالب."""
    from app.services.family import is_parent_of

    school_id = make_school(app)
    parent_id = make_user(app, role="parent", school_id=school_id)
    student_id = make_user(app, role="student", school_id=school_id)
    with app.app_context():
        assert not is_parent_of(parent_id, student_id)
        make_family_link(app, parent_id, student_id)
        assert is_parent_of(parent_id, student_id)


def test_remove_link(app):
    """إزالة رابط ولي الأمر."""
    from app.services.family import list_children, remove_link

    school_id = make_school(app)
    parent_id = make_user(app, role="parent", school_id=school_id)
    student_id = make_user(app, role="student", school_id=school_id)
    with app.app_context():
        link_id = make_family_link(app, parent_id, student_id)
        ok, err = remove_link(link_id, parent_id)
        assert ok
        assert err is None
        assert len(list_children(parent_id)) == 0


def test_remove_link_wrong_parent(app):
    """منع إزالة رابط بوحد أمر غير مطابق."""
    from app.services.family import remove_link

    school_id = make_school(app)
    parent1 = make_user(app, role="parent", school_id=school_id)
    parent2 = make_user(app, role="parent", school_id=school_id)
    student_id = make_user(app, role="student", school_id=school_id)
    with app.app_context():
        link_id = make_family_link(app, parent1, student_id)
        ok, err = remove_link(link_id, parent2)
        assert not ok


def test_get_parent(app):
    """جلب ولي الأمر الأول للطالب."""
    from app.services.family import get_parent

    school_id = make_school(app)
    parent_id = make_user(app, role="parent", school_id=school_id)
    student_id = make_user(app, role="student", school_id=school_id)
    with app.app_context():
        assert get_parent(student_id) is None
        make_family_link(app, parent_id, student_id)
        parent = get_parent(student_id)
        assert parent is not None
        assert parent.id == parent_id
