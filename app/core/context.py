"""سياق مشترك للقوالب — نقطة واحدة تُحقن في كل صفحة (لا تكرار في القوالب)."""

from datetime import datetime

from flask import request
from flask_babel import get_locale
from flask_login import current_user

from app.models.user import UserRole


def register(app):
    @app.context_processor
    def inject_app_context():
        return {
            "now": datetime.now(),
            "app_name": "مدرسة أزاد الإلكترونية",
            "is_admin": current_user.is_authenticated
            and current_user.role in (UserRole.super_admin, UserRole.school_admin),
            "current_user": current_user,
            "current_locale": str(get_locale()),
            "current_path": request.path,
        }
