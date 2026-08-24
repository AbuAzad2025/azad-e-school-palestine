"""مصادقة API — JWT + Session hybrid.

الهدف: دعم تطبيق الجوال (JWT) مع الحفاظ على مصادقة المتصفح (Session).
"""

from functools import wraps

from flask import request
from flask_login import current_user


def api_auth_required(f):
    """Decorator يتحقق من مصادقة API (Session أو JWT المستقبلي).

    حالياً: يعتمد على Flask-Login session.
    مستقبلاً: يتحقق من JWT header إذا وجد.
    """

    @wraps(f)
    def wrapper(*args, **kwargs):
        # Phase 1: Flask-Login session (الحالي)
        if current_user.is_authenticated:
            return f(*args, **kwargs)

        # Phase 2: JWT (مستقبلي — يُفعَّل عند تثبيت Flask-JWT-Extended)
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            # TODO: JWT verification when Flask-JWT-Extended is installed
            pass

        from app.core.api import api_error

        return api_error("غير مصادق عليه", 401, "UNAUTHORIZED")

    return wrapper
