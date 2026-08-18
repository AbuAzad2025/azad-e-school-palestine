"""اختبارات C13 — حدود التينانتس (TenantQuota — check_quota, set_tier, get_quota)."""

from app.extensions import db
from app.models.tenant import TenantQuota
from tests.conftest import make_class, make_class_member, make_grade, make_school, make_subject, make_tenant_quota, make_user


def test_get_quota_creates_default(app):
    """جلب حصة بدون وجود = إنشاء حصة free افتراضية."""
    from app.services.tenant import get_quota

    school_id = make_school(app)
    with app.app_context():
        quota = get_quota(school_id)
        assert quota.tier == "free"
        assert quota.max_students == 50


def test_check_quota_students_within_limit(app):
    """التحقق من أن الطلاب ضمن الحد المسموح."""
    from app.services.tenant import check_quota

    school_id = make_school(app)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id)
    with app.app_context():
        make_class_member(app, class_id, student_id)
        ok, msg = check_quota(school_id, "students")
        assert ok is True


def test_check_quota_classes(app):
    """التحقق من عدد الصفوف ضمن الحد."""
    from app.services.tenant import check_quota

    school_id = make_school(app)
    make_tenant_quota(app, school_id, max_classes=2)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    with app.app_context():
        make_class(app, school_id, grade_id, subject_id)
        make_class(app, school_id, grade_id, subject_id)
        ok, msg = check_quota(school_id, "classes")
        assert not ok
        assert msg


def test_set_tier_invalid(app):
    """باقة غير صالحة تُرفض."""
    from app.services.tenant import set_tier

    school_id = make_school(app)
    with app.app_context():
        result, err = set_tier(school_id, "ultra_premium")
        assert result is None
        assert "صالحة" in err


def test_set_tier_updates_quota(app):
    """تحديث الباقة يُحدّث الحدود."""
    from app.services.tenant import set_tier

    school_id = make_school(app)
    with app.app_context():
        result, err = set_tier(school_id, "pro")
        assert result is not None
        assert err is None
        assert result.tier == "pro"
        assert result.max_students == 500
        assert result.ai_enabled is True


def test_check_quota_ai_disabled(app):
    """خدمة AI غير مفعّلة في الباقة المجانية."""
    from app.services.tenant import check_quota

    school_id = make_school(app)
    with app.app_context():
        ok, msg = check_quota(school_id, "ai")
        assert ok is False
        assert "غير مفعّلة" in msg
