"""رموز آمنة موقّعة للبريد (تفعيل الحساب + إعادة التعيين)"""

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="azad-email-confirm")


def make_activation_token(user_id: int, email: str) -> str:
    return _serializer().dumps({"uid": user_id, "email": email})


def read_token(token: str, max_age_seconds: int = 86400):
    """يعيد (uid, email) أو None عند انتهاء/تزوير الرمز."""
    try:
        data = _serializer().loads(token, max_age=max_age_seconds)
        return data.get("uid"), data.get("email")
    except (BadSignature, SignatureExpired):
        return None, None
