"""مصنع التطبيق — منصة مدرسة أزاد الإلكترونية (Azad First Edition)

M0: هيكل قابل للتشغيل. تُضاف الوحدات (blueprints) في مراحلها.
"""

from config import Config
from flask import Flask, jsonify, render_template, request

from .extensions import babel, csrf, db, login_manager, migrate


def _select_locale():
    """يختار اللغة من الكوكي ثم التفضيلات، مع الوقوع على الإعداد الافتراضي."""
    from flask import current_app

    lang = request.cookies.get("locale", "")
    if lang in current_app.config.get("LANGUAGES", ["ar"]):
        return lang
    return current_app.config.get("DEFAULT_LOCALE", "ar")


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
    babel.init_app(app, locale_selector=_select_locale)

    from . import models  # noqa: F401  — تسجيل الجداول
    from .models.user import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from .modules.api import bp as api_bp
    from .modules.auth import bp as auth_bp
    from .modules.main import bp as main_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp)

    from .core import context

    context.register(app)

    @app.get("/health")
    def health():
        return jsonify(status="ok", app="azad-e-school")

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        db.session.rollback()
        return render_template("errors/500.html"), 500

    return app
