"""اختبارات موافقات المدرسة — توزيع صلاحيات الموافقة."""

import pytest

from app.extensions import db
from app.models.user import User, UserApprovalStatus, UserRole, UserRoleLink
from app.services.school_approvals import (
    approve_user_role_link,
    can_user_approve,
    get_approval_queue_for_user,
    get_pending_approvals_for_school,
    get_pending_approvals_for_super_admin,
    get_school_admins,
    reject_user_role_link,
)
from tests.conftest import make_class, make_grade, make_school, make_subject, make_user, make_user_role_link


def test_school_admin_can_approve_own_school(app):
    """المشرف المدرسي يمكنه الموافقة على مستخدمي مدرسته."""
    school_id = make_school(app)
    school_admin_id = make_user(app, role="school_admin", school_id=school_id)
    teacher_id = make_user(app, role="teacher", school_id=school_id, approved=False)

    with app.app_context():
        from app.models.user import UserRoleLink
        link = UserRoleLink.query.filter_by(user_id=teacher_id, school_id=school_id).first()
        assert link is not None

    with app.app_context():
        success, error = approve_user_role_link(link.id, school_admin_id)

    assert success is True
    assert error is None

    with app.app_context():
        from app.extensions import db
        from app.models.user import User, UserApprovalStatus
        teacher = db.session.get(User, teacher_id)
        assert teacher.approval_status == UserApprovalStatus.approved


def test_school_admin_cannot_approve_other_school(app):
    """المشرف المدرسي لا يمكنه الموافقة على مستخدمين من مدارس أخرى."""
    school_id_1 = make_school(app)
    school_id_2 = make_school(app)
    school_admin_id = make_user(app, role="school_admin", school_id=school_id_1)
    teacher_id = make_user(app, role="teacher", school_id=school_id_2, approved=False)

    with app.app_context():
        from app.models.user import UserRoleLink
        link = UserRoleLink.query.filter_by(user_id=teacher_id, school_id=school_id_2).first()
        assert link is not None

    with app.app_context():
        success, error = approve_user_role_link(link.id, school_admin_id)

    assert success is False
    assert "مدارس أخرى" in error


def test_super_admin_can_approve_any_school(app):
    """السوبر أدمن يمكنه الموافقة على أي مدرسة."""
    school_id = make_school(app)
    super_admin_id = make_user(app, role="super_admin")
    teacher_id = make_user(app, role="teacher", school_id=school_id, approved=False)

    with app.app_context():
        from app.models.user import UserRoleLink
        link = UserRoleLink.query.filter_by(user_id=teacher_id, school_id=school_id).first()
        assert link is not None

    with app.app_context():
        success, error = approve_user_role_link(link.id, super_admin_id)

    assert success is True
    assert error is None


def test_school_admin_can_reject_own_school(app):
    """المشرف المدرسي يمكنه رفض مستخدمي مدرسته."""
    school_id = make_school(app)
    school_admin_id = make_user(app, role="school_admin", school_id=school_id)
    teacher_id = make_user(app, role="teacher", school_id=school_id, approved=False)

    with app.app_context():
        from app.models.user import UserRoleLink
        link = UserRoleLink.query.filter_by(user_id=teacher_id, school_id=school_id).first()

    with app.app_context():
        success, error = reject_user_role_link(link.id, school_admin_id, reason="بيانات ناقصة")

    assert success is True

    with app.app_context():
        from app.extensions import db
        from app.models.user import User, UserApprovalStatus
        teacher = db.session.get(User, teacher_id)
        assert teacher.approval_status == "rejected"


def test_super_admin_can_reject_any_school(app):
    """السوبر أدمن يمكنه رفض أي مدرسة."""
    school_id = make_school(app)
    super_admin_id = make_user(app, role="super_admin")
    teacher_id = make_user(app, role="teacher", school_id=school_id, approved=False)

    with app.app_context():
        from app.models.user import UserRoleLink
        link = UserRoleLink.query.filter_by(user_id=teacher_id, school_id=school_id).first()

    with app.app_context():
        success, error = reject_user_role_link(link.id, super_admin_id, reason="سياسة المنصة")

    assert success is True


def test_can_user_approve_super_admin(app):
    """السوبر أدمن يمكنه الموافقة على أي رابط."""
    school_id = make_school(app)
    super_admin_id = make_user(app, role="super_admin")
    teacher_id = make_user(app, role="teacher", school_id=school_id, approved=False)

    with app.app_context():
        from app.models.user import UserRoleLink
        link = UserRoleLink.query.filter_by(user_id=teacher_id, school_id=school_id).first()

    with app.app_context():
        can = can_user_approve(super_admin_id, link.id)

    assert can is True


def test_school_admin_can_approve_only_own_school(app):
    """المشرف المدرسي يوافق فقط على مدرسته."""
    school_id_1 = make_school(app)
    school_id_2 = make_school(app)
    school_admin_id = make_user(app, role="school_admin", school_id=school_id_1)
    teacher_id_1 = make_user(app, role="teacher", school_id=school_id_1, approved=False)
    teacher_id_2 = make_user(app, role="teacher", school_id=school_id_2, approved=False)

    with app.app_context():
        from app.models.user import UserRoleLink
        link_1 = UserRoleLink.query.filter_by(user_id=teacher_id_1, school_id=school_id_1).first()
        link_2 = UserRoleLink.query.filter_by(user_id=teacher_id_2, school_id=school_id_2).first()

    with app.app_context():
        can_1 = can_user_approve(school_admin_id, link_1.id)
        can_2 = can_user_approve(school_admin_id, link_2.id)

    assert can_1 is True
    assert can_2 is False


def test_get_pending_approvals_for_school(app):
    """جلب الطلبات المعلقة لمدرسة معينة."""
    school_id = make_school(app)
    school_admin_id = make_user(app, role="school_admin", school_id=school_id)
    teacher_id = make_user(app, role="teacher", school_id=school_id, approved=False)
    student_id = make_user(app, role="student", school_id=school_id, approved=False)

    with app.app_context():
        links = get_pending_approvals_for_school(school_id)

    assert len(links) == 2
    roles = {link.role for link in links}
    assert roles == {"teacher", "student"}


def test_get_pending_approvals_for_super_admin(app):
    """جلب جميع الطلبات المعلقة للسوبر أدمن."""
    school_id_1 = make_school(app)
    school_id_2 = make_school(app)
    teacher_id_1 = make_user(app, role="teacher", school_id=school_id_1, approved=False)
    teacher_id_2 = make_user(app, role="teacher", school_id=school_id_2, approved=False)

    with app.app_context():
        links = get_pending_approvals_for_super_admin()

    assert len(links) >= 2


def test_get_approval_queue_for_user(app):
    """جلب قائمة الانتظار حسب دور المستخدم."""
    school_id = make_school(app)
    school_admin_id = make_user(app, role="school_admin", school_id=school_id)
    teacher_id = make_user(app, role="teacher", school_id=school_id, approved=False)

    with app.app_context():
        from app.models.user import UserRoleLink
        link = UserRoleLink.query.filter_by(user_id=teacher_id, school_id=school_id).first()

    # للمشرف المدرسي
    with app.app_context():
        queue = get_approval_queue_for_user(school_admin_id)
    assert len(queue) == 1

    # للسوبر أدمن
    super_admin_id = make_user(app, role="super_admin")
    with app.app_context():
        queue = get_approval_queue_for_user(make_user(app, role="super_admin"))
    assert len(queue) >= 1


def test_get_school_admins(app):
    """جلب مشرفي مدرسة معينة."""
    school_id = make_school(app)
    admin1 = make_user(app, role="school_admin", school_id=school_id)
    admin2 = make_user(app, role="school_admin", school_id=school_id)
    teacher = make_user(app, role="teacher", school_id=school_id)

    with app.app_context():
        admins = get_school_admins(school_id)

    assert len(admins) == 2
    roles = {link.role for link in admins}
    assert roles == {"school_admin"}


def test_approve_reject_notifications(app):
    """التحقق من إرسال الإشعارات عند الموافقة/الرفض."""
    school_id = make_school(app)
    school_admin_id = make_user(app, role="school_admin", school_id=school_id)
    teacher_id = make_user(app, role="teacher", school_id=school_id, approved=False)

    with app.app_context():
        from app.models.user import UserRoleLink
        link = UserRoleLink.query.filter_by(user_id=teacher_id, school_id=school_id).first()

    # الموافقة
    with app.app_context():
        from app.services.communication import notify
        from app.extensions import db
        from app.models.communication import Notification

        success, error = approve_user_role_link(link.id, school_admin_id)
        assert success is True

        notification = Notification.query.filter_by(
            user_id=teacher_id, type="approval"
        ).first()
        assert notification is not None
        assert "قبول" in notification.title

    # الرفض
    teacher_id_2 = make_user(app, role="teacher", school_id=school_id, approved=False)
    with app.app_context():
        from app.models.user import UserRoleLink
        link2 = UserRoleLink.query.filter_by(user_id=teacher_id_2, school_id=school_id).first()

    with app.app_context():
        success, error = reject_user_role_link(link2.id, school_admin_id, reason="بيانات ناقصة")
        assert success is True

        notification = Notification.query.filter_by(
            user_id=teacher_id_2, type="rejection"
        ).first()
        assert notification is not None
        assert "رفض" in notification.title


# Route tests
def test_approval_queue_page_school_admin(app, client):
    """صفحة قائمة الانتظار تظهر للمشرف المدرسي."""
    school_id = make_school(app)
    school_admin_email = f"school_admin{school_id}@test.com"
    school_admin_id = make_user(app, role="school_admin", school_id=school_id, email=school_admin_email)
    teacher_id = make_user(app, role="teacher", school_id=school_id, approved=False)

    with client:
        client.post("/auth/login", data={"email": school_admin_email, "password": "TestPass123!"})
        resp = client.get("/school-admin/approvals")
        assert resp.status_code == 200
        assert "قائمة انتظار الموافقة" in resp.get_data(as_text=True)


def test_approval_queue_page_super_admin(app, client):
    """صفحة قائمة الانتظار تظهر للسوبر أدمن."""
    super_admin_email = f"superadmin_{id(app)}@test.com"
    super_admin_id = make_user(app, role="super_admin", email=super_admin_email)
    school_id = make_school(app)
    teacher_id = make_user(app, role="teacher", school_id=school_id, approved=False)

    with client:
        client.post("/auth/login", data={"email": super_admin_email, "password": "TestPass123!"})
        resp = client.get("/school-admin/admin/approvals")
        assert resp.status_code == 200
        assert "قائمة انتظار الموافقة" in resp.get_data(as_text=True)


def test_approve_route_school_admin(app, client):
    """مسار القبول يعمل للمشرف المدرسي."""
    school_id = make_school(app)
    school_admin_email = f"school_admin{school_id}@test.com"
    school_admin_id = make_user(app, role="school_admin", school_id=school_id, email=school_admin_email)
    teacher_id = make_user(app, role="teacher", school_id=school_id, approved=False)

    with app.app_context():
        from app.models.user import UserRoleLink
        link = UserRoleLink.query.filter_by(user_id=teacher_id, school_id=school_id).first()

    with client:
        client.post("/auth/login", data={"email": school_admin_email, "password": "TestPass123!"})
        resp = client.post(f"/school-admin/approvals/{link.id}/approve", follow_redirects=True)
        assert resp.status_code == 200
        assert "تم قبول المستخدم بنجاح" in resp.get_data(as_text=True)

    with app.app_context():
        from app.extensions import db
        from app.models.user import User, UserApprovalStatus
        teacher = db.session.get(User, teacher_id)
        assert teacher.approval_status == "approved"


def test_reject_route_school_admin(app, client):
    """مسار الرفض يعمل للمشرف المدرسي."""
    school_id = make_school(app)
    school_admin_email = f"school_admin{school_id}@test.com"
    school_admin_id = make_user(app, role="school_admin", school_id=school_id, email=school_admin_email)
    teacher_id = make_user(app, role="teacher", school_id=school_id, approved=False)

    with app.app_context():
        from app.models.user import UserRoleLink
        link = UserRoleLink.query.filter_by(user_id=teacher_id, school_id=school_id).first()

    with client:
        client.post("/auth/login", data={"email": school_admin_email, "password": "TestPass123!"})
        resp = client.post(f"/school-admin/approvals/{link.id}/reject", data={"reason": "بيانات ناقصة"}, follow_redirects=True)
        assert resp.status_code == 200
        assert "تم رفض المستخدم" in resp.get_data(as_text=True)

    with app.app_context():
        from app.extensions import db
        from app.models.user import User, UserApprovalStatus
        teacher = db.session.get(User, teacher_id)
        assert teacher.approval_status == "rejected"


def test_school_admin_cannot_access_other_school_approvals(app, client):
    """المشرف المدرسي لا يمكنه الوصول لموافقات مدارس أخرى."""
    school_id_1 = make_school(app)
    school_id_2 = make_school(app)
    school_admin_email = f"school_admin{school_id_1}@test.com"
    school_admin_id = make_user(app, role="school_admin", school_id=school_id_1, email=school_admin_email)
    teacher_id = make_user(app, role="teacher", school_id=school_id_2, approved=False)

    with app.app_context():
        from app.models.user import UserRoleLink
        link = UserRoleLink.query.filter_by(user_id=teacher_id, school_id=school_id_2).first()

    with client:
        client.post("/auth/login", data={"email": school_admin_email, "password": "TestPass123!"})
        resp = client.post(f"/school-admin/approvals/{link.id}/approve")
        assert resp.status_code == 403