"""مصنع التطبيق — منصة مدرسة أزاد الإلكترونية (Azad First Edition)

M0: هيكل قابل للتشغيل. تُضاف الوحدات (blueprints) في مراحلها.
"""

from config import Config
from flask import Flask, jsonify, render_template, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman

from .extensions import babel, csrf, db, login_manager, migrate


def _select_locale():
    """يختار اللغة من الكوكي ثم التفضيلات، مع الوقوع على الإعداد الافتراضي."""
    from flask import current_app

    lang = request.cookies.get("locale", "")
    if lang in current_app.config.get("LANGUAGES", ["ar"]):
        return lang
    return current_app.config.get("DEFAULT_LOCALE", "ar")


def _rate_limit_key():
    """مفتاح تحديد المعدل: IP + مستخدم مصادق إن وجد."""
    from flask_login import current_user

    if current_user.is_authenticated:
        return f"user:{current_user.id}"
    return get_remote_address()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # === أمان: Talisman (روؤوس HTTP، CSP، HSTS) ===
    if app.config.get("TALISMAN_ENABLED", True):
        Talisman(
            app,
            force_https=app.config.get("TALISMAN_FORCE_HTTPS", True),
            strict_transport_security=app.config.get("TALISMAN_STRICT_TRANSPORT_SECURITY", True),
            strict_transport_security_max_age=app.config.get("TALISMAN_STRICT_TRANSPORT_SECURITY_MAX_AGE", 31536000),
            content_security_policy=app.config.get("TALISMAN_CONTENT_SECURITY_POLICY"),
            content_security_policy_report_only=app.config.get("TALISMAN_CONTENT_SECURITY_POLICY_REPORT_ONLY", False),
            referrer_policy=app.config.get("TALISMAN_REFERRER_POLICY", "strict-origin-when-cross-origin"),
            permissions_policy=app.config.get("TALISMAN_PERMISSIONS_POLICY"),
            session_cookie_secure=app.config.get("SESSION_COOKIE_SECURE", True),
            session_cookie_http_only=app.config.get("SESSION_COOKIE_HTTPONLY", True),
            session_cookie_samesite=app.config.get("SESSION_COOKIE_SAMESITE", "Lax"),
        )

    # === أمان: معدل الطلبات (Flask-Limiter) ===
    limiter = Limiter(
        key_func=_rate_limit_key,
        default_limits=[app.config.get("RATELIMIT_DEFAULT", "200 per minute")],
        storage_uri=app.config.get("RATELIMIT_STORAGE_URL", "memory://"),
        strategy=app.config.get("RATELIMIT_STRATEGY", "fixed-window"),
    )
    limiter.init_app(app)

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

    from .modules.admin import bp as admin_bp
    from .modules.ai import bp as ai_bp
    from .modules.api import bp as api_bp
    from .modules.assessment import bp as assessment_bp
    from .modules.auth import bp as auth_bp
    from .modules.billing import bp as billing_bp
    from .modules.content import bp as content_bp
    from .modules.grades import bp as grades_bp
    from .modules.main import bp as main_bp
    from .modules.notifications import bp as notifications_bp
    from .modules.payments import bp as payments_bp
    from .modules.schools import bp as schools_bp
    from .modules.tutoring import bp as tutoring_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(schools_bp)
    app.register_blueprint(tutoring_bp)
    app.register_blueprint(content_bp)
    app.register_blueprint(assessment_bp)
    app.register_blueprint(grades_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(payments_bp)

    # تطبيق حدود معدل مخصصة للمسارات الحساسة
    with app.app_context():
        from .modules.api import bp as api_bp_local
        from .modules.auth import bp as auth_bp_local
        from .modules.tutoring import bp as tutoring_bp_local

        # auth routes
        for endpoint in ("login", "register", "forgot_password", "reset_password"):
            if endpoint in auth_bp_local.view_functions:
                limiter.limit("5 per minute")(auth_bp_local.view_functions[endpoint])
        # tutoring book
        if "book" in tutoring_bp_local.view_functions:
            limiter.limit("30 per minute")(tutoring_bp_local.view_functions["book"])
        # api blueprint (all routes)
        limiter.limit("100 per minute")(api_bp_local)

    from .core import context

    context.register(app)

    @app.get("/health")
    def health():
        return jsonify(status="ok", app="azad-e-school")

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(429)
    def ratelimit_exceeded(e):
        return render_template("errors/429.html"), 429

    @app.errorhandler(500)
    def server_error(e):
        db.session.rollback()
        return render_template("errors/500.html"), 500

    return app
