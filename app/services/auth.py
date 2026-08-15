"""خدمات المصادقة — منطق موحّد مُعاد الاستخدام من الويب والـ API"""

from flask_login import current_user

from app.core.security import hash_password, verify_password
from app.extensions import db
from app.models.user import User, UserRole

from .base import tx


def register_user(email: str, name_ar: str, role: str, password: str) -> tuple[User | None, str | None]:
    """ينشئ حساباً بذرّية كاملة. يعيد (user, error)."""
    email = email.strip().lower()
    if User.query.filter_by(email=email).first():
        return None, "هذا البريد مسجّل مسبقاً."
    if role not in {r.value for r in UserRole}:
        return None, "دور غير صالح."

    def _create():
        user = User(
            email=email,
            name_ar=name_ar.strip(),
            role=UserRole(role),
            password_hash=hash_password(password),
            is_verified=False,
        )
        db.session.add(user)
        return user

    return tx(_create), None


def authenticate(email: str, password: str) -> tuple[User | None, str | None]:
    """يعيد (user, error). النجاح: error None."""
    user = User.query.filter_by(email=email.strip().lower()).first()
    if not user or not verify_password(user.password_hash, password):
        return None, "بريد أو كلمة مرور غير صحيحة."
    if not user.is_active:
        return None, "حسابك معطّل. تواصل مع الإدارة."
    if not user.is_verified:
        return None, "فعّل بريدك الإلكتروني أولاً."
    return user, None


def mark_login(user: User) -> None:
    def _mark():
        user.last_login_at = db.func.now()

    tx(_mark)


def confirm_email(uid: int, email: str) -> bool:
    """يُفعّل البريد عند تطابق الرمز. يعيد نجاح/فشل (للـ API والويب معاً)."""
    user = db.session.get(User, uid)
    if not user or user.email != email:
        return False

    def _confirm():
        user.is_verified = True

    tx(_confirm)
    return True


def is_current(user: User) -> bool:
    return current_user.is_authenticated and current_user.id == user.id
