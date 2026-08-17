"""رموز آمنة موقّعة للبريد (تفعيل الحساب + إعادة تعيين كلمة المرور)"""

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

_SALT_CONFIRM = "azad-email-confirm"
_SALT_RESET = "azad-password-reset"


def _serializer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=salt)


def make_token(user_id: int, email: str, salt: str) -> str:
    """رمز موقّع عام بأي ملح (مفيد للتفعيل وإعادة التعيين)."""
    return _serializer(salt).dumps({"uid": user_id, "email": email})


def make_activation_token(user_id: int, email: str) -> str:
    return make_token(user_id, email, _SALT_CONFIRM)


def make_reset_token(user_id: int, email: str) -> str:
    return make_token(user_id, email, _SALT_RESET)


def read_token(token: str, salt: str = _SALT_CONFIRM, max_age_seconds: int = 86400):
    """يعيد (uid, email) أو (None, None) عند انتهاء/تزوير الرمز."""
    try:
        data = _serializer(salt).loads(token, max_age=max_age_seconds)
        return data.get("uid"), data.get("email")
    except (BadSignature, SignatureExpired):
        return None, None


def read_reset_token(token: str, max_age_seconds: int = 3600):
    """قراءة رمز إعادة التعيين — صالح ساعة واحدة فقط."""
    return read_token(token, salt=_SALT_RESET, max_age_seconds=max_age_seconds)
