"""طبقة الأمان: هاش كلمات المرور argon2id + أدوات RBAC (D6)"""
from functools import wraps

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from flask import abort, flash
from flask_login import current_user

from app.models.user import UserRole

_ph = PasswordHasher()


def hash_password(raw: str) -> str:
    return _ph.hash(raw)


def verify_password(hashed: str, raw: str) -> bool:
    try:
        return _ph.verify(hashed, raw)
    except (VerifyMismatchError, InvalidHashError):
        return False


def role_required(*roles: UserRole):
    """D6: فحص الصلاحية على كل route قبل أي تنفيذ."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return abort(403)
            if current_user.role not in roles and current_user.role != UserRole.super_admin:
                return abort(403)
            return fn(*args, **kwargs)

        return wrapper

    return decorator
