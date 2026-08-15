"""طبقة الأمان: هاش كلمات المرور argon2id فقط.

الصلاحيات وRBAC في app/core/permissions.py — نقطة واحدة لا تتكرر.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_ph = PasswordHasher()


def hash_password(raw: str) -> str:
    return _ph.hash(raw)


def verify_password(hashed: str, raw: str) -> bool:
    try:
        return _ph.verify(hashed, raw)
    except (VerifyMismatchError, InvalidHashError):
        return False
