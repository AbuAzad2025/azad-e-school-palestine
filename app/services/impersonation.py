"""انتحال الصفة — سوبر أدمن فقط، للأدوار الأدنى فقط، مع سجل تدقيق إلزامي.

الجلسة تحمل معرّف المشرف الكلي الأصلي (impersonator_id) بينما يلعب
current_user دور الهدف. كل دخول/خروج انتحال يُسجَّل في AuditLog.
"""

from flask import session
from flask_login import current_user, login_user, logout_user

from app.core.db import tx
from app.extensions import db
from app.models.system import AuditLog
from app.models.user import User, UserRole

SESSION_KEY = "impersonator_id"


def is_impersonating() -> bool:
    """هل الجلسة الحالية في وضع انتحال صفة؟"""
    return SESSION_KEY in session


def impersonator_user() -> User | None:
    """المشرف الكلي الأصلي أثناء الانتحال (None إن لم يكن انتحالاً)."""
    uid = session.get(SESSION_KEY)
    if not uid:
        return None
    return db.session.get(User, int(uid))


def _log(impersonator: User, action: str, target: User) -> None:
    def _insert():
        db.session.add(
            AuditLog(
                user_id=impersonator.id,
                action=action,
                entity="users",
                entity_id=target.id,
                detail={
                    "impersonator": impersonator.email,
                    "target_email": target.email,
                    "target_role": target.role.value,
                },
            )
        )

    tx(_insert)


def start_impersonation(target: User) -> str | None:
    """يبدأ انتحال صفة مستخدم أدنى من المشرف الكلي. يعيد رسالة خطأ أو None عند النجاح."""
    if not current_user.is_authenticated or current_user.role != UserRole.super_admin:
        return "غير مصرح بهذه العملية."
    if target.id == current_user.id:
        return "لا يمكنك انتحال صفة حسابك."
    if target.role == UserRole.super_admin:
        return "لا يمكن انتحال صفة مشرف كلي."
    if not target.is_active:
        return "الحساب معطّل ولا يمكن الانتحال به."

    impersonator = current_user
    _log(impersonator, "impersonate_start", target)
    session[SESSION_KEY] = impersonator.id
    logout_user()
    login_user(target)
    return None


def stop_impersonation() -> str | None:
    """إنهاء الانتحال والعودة إلى حساب المشرف الأصلي. يعيد رسالة خطأ أو None عند النجاح."""
    impersonator = impersonator_user()
    if impersonator is None:
        return "لا توجد جلسة انتحال نشطة."

    target = current_user
    _log(impersonator, "impersonate_stop", target)
    session.pop(SESSION_KEY, None)
    logout_user()
    login_user(impersonator)
    return None


def clear_impersonation() -> None:
    """يزيل علامة الانتحال من الجلسة (يُستدعى عند الخروج العادي كاحتياط)."""
    session.pop(SESSION_KEY, None)
