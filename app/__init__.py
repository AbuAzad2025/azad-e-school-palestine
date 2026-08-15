"""مصنع التطبيق — منصة مدرسة أزاد الإلكترونية (Azad First Edition)

M0: هيكل قابل للتشغيل فقط. تُضاف النماذج والوحدات (blueprints) في مراحلها.
"""
from flask import Flask

from config import Config
from .extensions import babel, csrf, db, login_manager, migrate


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "يرجى تسجيل الدخول للمتابعة."
    login_manager.login_message_category = "warning"
    csrf.init_app(app)
    babel.init_app(app, locale_selector=lambda: app.config.get("DEFAULT_LOCALE", "ar"))

    @app.get("/health")
    def health():
        return {"status": "ok", "app": "azad-e-school"}

    @app.errorhandler(404)
    def not_found(e):
        return "الصفحة غير موجودة", 404

    @app.errorhandler(500)
    def server_error(e):
        db.session.rollback()
        return "خطأ داخلي في الخادم", 500

    return app
