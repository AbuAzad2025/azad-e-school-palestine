"""مصادقة API — Session + Bearer Token هجينة.

P1-SEC-01: تطبيق الجوال يستخدم Personal Access Tokens (Bearer) موقّعة
بـ itsdangerous (نفس SECRET_KEY، صلاحية 30 يوماً)، بينما المتصفح يستمر
على الجلسة — توافق كامل مع المتصلين الحاليين.

آلية العمل:
    يُسجَّل ``login_manager.request_loader`` في app factory؛ فيقرأ Flask-Login
    ترويسة Authorization تلقائياً عند غياب الجلسة، فيصبح ``current_user``
    صحيحاً لطلبات Bearer في كل الحارس (api_auth_required وrole_required).

الاستخدام:
    Authorization: Bearer <token>

إصدار التوكن:
    POST /api/v1/auth/token  (email + password → token)
"""

from functools import wraps

from flask import current_app, request
from flask_login import current_user

_SALT_API = "azad-api-pat-v1"
_MAX_AGE = 60 * 60 * 24 * 30  # 30 يوماً


def make_api_token(user_id: int) -> str:
    """إصدار Personal Access Token لمستخدم (تُوقّع بـ SECRET_KEY)."""
    from itsdangerous import URLSafeTimedSerializer

    s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=_SALT_API)
    return s.dumps({"uid": user_id, "kind": "pat"})


def read_api_token(token: str) -> int | None:
    """قراءة التوكن وإرجاع user_id أو None (منتهي/مزيّف)."""
    from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

    try:
        s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=_SALT_API)
        data = s.loads(token, max_age=_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    if data.get("kind") != "pat":
        return None
    uid = data.get("uid")
    return int(uid) if uid else None


def user_from_bearer():
    """استخراج مستخدم من ترويسة Bearer (بلا جانب جلسات)."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        return None
    uid = read_api_token(token)
    if uid is None:
        return None
    from app.extensions import db
    from app.models.user import User

    user = db.session.get(User, uid)
    if user is None or not user.is_active or user.deleted_at is not None:
        return None
    return user


def api_auth_required(f):
    """Decorator يتحقق من مصادقة API (جلسة Flask-Login أو Bearer PAT).

    ملاحظة: current_user في Flask-Login يشمل الجلسة **والـ request_loader**،
    لذا الفحص واحد يغطي الحالتين — السلوك القديم للمتصفح لم يتغير.
    """

    @wraps(f)
    def wrapper(*args, **kwargs):
        if current_user.is_authenticated:
            return f(*args, **kwargs)

        # احتياط صريح (مثلاً request_loader غير مسجّل في بيئة اختبار معزولة)
        if user_from_bearer() is not None:
            return f(*args, **kwargs)

        from app.core.api import api_error

        return api_error("غير مصادق عليه", 401, "UNAUTHORIZED")

    return wrapper
