"""خدمات موافقات المدرسة — توزيع صلاحيات الموافقة على المشرفين."""

from datetime import UTC, datetime

from app.core.db import tx
from app.extensions import db
from app.models.user import User, UserApprovalStatus, UserRoleLink
from app.services.communication import notify


def get_pending_approvals_for_school(school_id: int):
    """جلب طلبات الموافقة المعلقة لمدرسة معينة (للمشرف المدرسي)."""
    return (
        UserRoleLink.query.filter_by(school_id=school_id, is_active=True)
        .join(UserRoleLink.user)
        .filter(User.approval_status == UserApprovalStatus.pending)
        .all()
    )


def get_pending_approvals_for_super_admin():
    """جلب جميع طلبات الموافقة المعلقة (للسوبر أدمن)."""
    return (
        UserRoleLink.query.filter_by(is_active=True)
        .join(UserRoleLink.user)
        .filter(User.approval_status == UserApprovalStatus.pending)
        .all()
    )


def get_school_admins(school_id: int):
    """جلب مشرفي مدرسة معينة."""
    return (
        UserRoleLink.query.filter_by(school_id=school_id, role="school_admin", is_active=True)
        .join(UserRoleLink.user)
        .all()
    )


def approve_user_role_link(link_id: int, approver_id: int) -> tuple[bool, str | None]:
    """الموافقة على رابط دور مستخدم."""
    from app.extensions import db
    from app.models.user import UserApprovalStatus

    link = db.session.get(UserRoleLink, link_id)
    if not link:
        return False, "رابط الدور غير موجود."

    if not link.user:
        return False, "المستخدم غير موجود."

    if link.user.approval_status != UserApprovalStatus.pending:
        return False, "الحساب ليس في انتظار الموافقة."

    approver = db.session.get(User, approver_id)
    if not approver:
        return False, "الموافق غير موجود."

    # التحقق من الصلاحيات
    if approver.role == "super_admin":
        pass  # السوبر أدمن يمكنه الموافقة على أي شيء
    elif approver.role == "school_admin":
        # المشرف المدرسي يمكنه الموافقة فقط على مدرسته
        if link.school_id != approver.school_id:
            return False, "لا يمكنك الموافقة على مستخدمين من مدارس أخرى."
    else:
        return False, "ليس لديك صلاحية الموافقة."

    def _approve():
        link.approved_by = approver_id
        link.approved_at = datetime.now(UTC)
        link.user.approval_status = UserApprovalStatus.approved

    tx(_approve)

    # إشعار المستخدم بالموافقة
    notify(
        link.user_id,
        "approval",
        "تم قبول حسابك",
        "تم قبول حسابك من قبل الإدارة. يمكنك الآن تسجيل الدخول.",
    )

    return True, None


def reject_user_role_link(link_id: int, approver_id: int, reason: str | None = None) -> tuple[bool, str | None]:
    """رفض رابط دور مستخدم."""
    from app.extensions import db
    from app.models.user import UserApprovalStatus

    link = db.session.get(UserRoleLink, link_id)
    if not link:
        return False, "رابط الدور غير موجود."

    if not link.user:
        return False, "المستخدم غير موجود."

    if link.user.approval_status != UserApprovalStatus.pending:
        return False, "الحساب ليس في انتظار الموافقة."

    approver = db.session.get(User, approver_id)
    if not approver:
        return False, "الموافق غير موجود."

    # التحقق من الصلاحيات
    if approver.role == "super_admin":
        pass
    elif approver.role == "school_admin":
        if link.school_id != approver.school_id:
            return False, "لا يمكنك رفض مستخدمين من مدارس أخرى."
    else:
        return False, "ليس لديك صلاحية الرفض."

    def _reject():
        link.user.approval_status = UserApprovalStatus.rejected
        link.is_active = False

    tx(_reject)

    # إشعار المستخدم بالرفض
    msg = "تم رفض حسابك."
    if reason:
        msg += " السبب: " + reason
    notify(
        link.user_id,
        "rejection",
        "تم رفض حسابك",
        msg,
    )

    return True, None


def get_approval_queue_for_user(user_id: int):
    """جلب قائمة الانتظار للموافقة حسب دور المستخدم."""
    user = db.session.get(User, user_id)
    if not user:
        return []

    if user.role == "super_admin":
        return get_pending_approvals_for_super_admin()
    elif user.role == "school_admin":
        school_id = user.school_id
        if not school_id:
            return []
        return get_pending_approvals_for_school(school_id)
    return []


def can_user_approve(approver_id: int, target_link_id: int) -> bool:
    """التحقق مما إذا كان المستخدم يمكنه الموافقة على رابط دور معين."""
    from app.extensions import db

    approver = db.session.get(User, approver_id)
    link = db.session.get(UserRoleLink, target_link_id)

    if not approver or not link:
        return False

    if approver.role == "super_admin":
        return True

    if approver.role == "school_admin":
        return link.school_id == approver.school_id

    return False
