"""طبقة الأمان: هاش كلمات المرور argon2id فقط.

الصلاحيات وRBAC في app/core/permissions.py — نقطة واحدة لا تتكرر.
"""

import re

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from flask import current_app

_ph = PasswordHasher()

# كلمات مرور شائعة للمنع (قائمة مختصرة، قابلة للتوسعة)
COMMON_PASSWORDS = {
    "password",
    "123456",
    "123456789",
    "qwerty",
    "abc123",
    "password123",
    "admin",
    "letmein",
    "welcome",
    "monkey",
    "12345678",
    "sunshine",
    "princess",
    "qwertyuiop",
    "111111",
}


def hash_password(raw: str) -> str:
    return _ph.hash(raw)


def verify_password(hashed: str, raw: str) -> bool:
    try:
        return _ph.verify(hashed, raw)
    except (VerifyMismatchError, InvalidHashError):
        return False


def validate_password_policy(password: str) -> tuple[bool, str | None]:
    """يتحقق من كلمة المرور ضد السياسة. يعيد (صحيح/خطأ، رسالة خطأ)."""
    cfg = current_app.config if current_app else {}

    min_len = cfg.get("PASSWORD_MIN_LENGTH", 10)
    if len(password) < min_len:
        return False, f"كلمة المرور يجب أن تكون {min_len} أحرف على الأقل."

    if cfg.get("PASSWORD_REQUIRE_UPPER", True) and not re.search(r"[A-Z]", password):
        return False, "يجب أن تحتوي على حرف كبير (A-Z) واحد على الأقل."
    if cfg.get("PASSWORD_REQUIRE_LOWER", True) and not re.search(r"[a-z]", password):
        return False, "يجب أن تحتوي على حرف صغير (a-z) واحد على الأقل."
    if cfg.get("PASSWORD_REQUIRE_DIGIT", True) and not re.search(r"\d", password):
        return False, "يجب أن تحتوي على رقم (0-9) واحد على الأقل."
    if cfg.get("PASSWORD_REQUIRE_SPECIAL", True) and not re.search(r"[!@#$%^&*_\-+=?/]", password):
        return False, "يجب أن تحتوي على رمز خاص (!@#$%^&*_-+=?/) واحد على الأقل."

    if password.lower() in COMMON_PASSWORDS:
        return False, "كلمة المرور شائعة جداً، اختر كلمة أقوى."

    return True, None


def check_password_reuse(user, new_password_hash: str, history_count: int = 5) -> tuple[bool, str | None]:
    """يتحقق مما إذا كان الهاش الجديد موجوداً في تاريخ المستخدم."""
    if user.password_history and new_password_hash in user.password_history:
        return False, "لا يمكن إعادة استخدام كلمة مرور سابقة."
    return True, None
