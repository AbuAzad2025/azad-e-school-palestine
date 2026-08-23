"""مصنع التطبيق — منصة مدرسة أزاد الإلكترونية (Azad First Edition)

M0: هيكل قابل للتشغيل. تُضاف الوحدات (blueprints) في مراحلها.
"""

import time as _time
from collections import deque

from config import Config
from flask import Flask, g, jsonify, redirect, render_template, request, url_for
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from werkzeug.exceptions import HTTPException

from .core.logging import configure_structlog, correlation_id_middleware, get_logger
from .core.openapi import init_swagger
from .extensions import babel, csrf, db, login_manager, mail, migrate

logger = get_logger(__name__)

_response_times: deque[int] = deque(maxlen=1000)


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

    # === Structured Logging + Correlation IDs ===
    configure_structlog(app)
    correlation_id_middleware(app)

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

    # === CORS for mobile/API clients ===
    CORS(
        app,
        resources={
            r"/api/v1/*": {
                "origins": app.config.get("CORS_ORIGINS", ["*"]),
                "supports_credentials": app.config.get("CORS_SUPPORTS_CREDENTIALS", True),
                "allow_headers": app.config.get("CORS_ALLOW_HEADERS", ["Content-Type", "X-CSRFToken", "Authorization"]),
            }
        },
    )

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "يرجى تسجيل الدخول للمتابعة."
    login_manager.login_message_category = "warning"
    csrf.init_app(app)
    babel.init_app(app, locale_selector=_select_locale)
    mail.init_app(app)

    if app.config.get("SENTRY_DSN"):
        from app.core.sentry import init_sentry, set_sentry_user

        init_sentry(app)

    @app.before_request
    def _track_response_time():
        g._request_start = _time.monotonic()
        if app.config.get("SENTRY_DSN"):
            from flask_login import current_user

            set_sentry_user(current_user)

    @app.after_request
    def _track_response_end(response):
        if hasattr(g, "_request_start"):
            elapsed_ms = int((_time.monotonic() - g._request_start) * 1000)
            _response_times.append(elapsed_ms)
        return response

    if not app.config.get("TALISMAN_ENABLED", True):

        @app.after_request
        def _security_headers_fallback(response):
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
            response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; frame-ancestors 'none'",
            )
            return response

    from . import models  # noqa: F401
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
    from .modules.calendar import bp as calendar_bp
    from .modules.contact import bp as contact_bp
    from .modules.content import bp as content_bp
    from .modules.export import bp as export_bp
    from .modules.family import bp as family_bp
    from .modules.grades import bp as grades_bp
    from .modules.individual import bp as individual_bp
    from .modules.main import bp as main_bp
    from .modules.messages import bp as messages_bp
    from .modules.notifications import bp as notifications_bp
    from .modules.payments import bp as payments_bp
    from .modules.payments import payments_ui_bp
    from .modules.progress import bp as progress_bp
    from .modules.school_approvals import bp as school_approvals_bp
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
    app.register_blueprint(payments_ui_bp)
    app.register_blueprint(family_bp)
    app.register_blueprint(progress_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(export_bp)
    app.register_blueprint(messages_bp)
    app.register_blueprint(school_approvals_bp)
    app.register_blueprint(individual_bp)
    app.register_blueprint(contact_bp)

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

    # API Version negotiation middleware
    @app.before_request
    def _negotiate_api_version():
        if request.path.startswith("/api/"):
            from .modules.api import negotiate_api_version

            request.api_version = negotiate_api_version(request)  # type: ignore[attr-defined]

    # Initialize Swagger/OpenAPI
    init_swagger(app)

    from .core import context

    context.register(app)

    @app.get("/health")
    def health():
        import shutil
        from datetime import UTC, datetime
        from pathlib import Path as _Path

        from sqlalchemy import text as sql_text

        checks = {}
        overall = "healthy"

        start = _time.monotonic()
        try:
            db.session.execute(sql_text("SELECT 1"))
            checks["database"] = {"status": "ok", "response_ms": int((_time.monotonic() - start) * 1000)}
        except Exception:
            checks["database"] = {"status": "error", "response_ms": int((_time.monotonic() - start) * 1000)}
            overall = "down"

        try:
            usage = shutil.disk_usage(".")
            free_pct = int((usage.free / usage.total) * 100)
            disk_status = "ok" if free_pct > 10 else ("warning" if free_pct > 2 else "error")
            checks["disk"] = {"status": disk_status, "free_percent": free_pct}
            if disk_status == "error":
                overall = "degraded"
        except Exception:
            checks["disk"] = {"status": "error", "free_percent": 0}

        avg_ms = round(sum(_response_times) / len(_response_times)) if _response_times else 0
        checks["performance"] = {"status": "ok", "avg_response_ms": avg_ms, "sample_count": len(_response_times)}

        backup_file = None
        backup_dir = app.config.get("BACKUP_DIR")
        if backup_dir:
            bp = _Path(str(backup_dir))
            if bp.exists():
                backups = sorted(bp.glob("backup_*"), key=lambda p: p.stat().st_mtime, reverse=True)
                if backups:
                    backup_file = datetime.fromtimestamp(backups[0].stat().st_mtime, tz=UTC).isoformat()
        checks["backup"] = {"status": "ok" if backup_file else "warning", "last_backup": backup_file or "none"}

        if any(c["status"] == "error" for c in checks.values()):
            overall = "down"
        elif any(c["status"] == "warning" for c in checks.values()):
            overall = "degraded"

        alert_email = app.config.get("ALERT_EMAIL")
        if overall == "down" and alert_email:
            try:
                from flask_mail import Message

                msg = Message(
                    subject=f"[Azad] Health Alert: {overall}",
                    recipients=[alert_email],
                    body=f"System status: {overall}. Checks: {checks}",
                )
                mail.send(msg)
            except Exception:
                pass

        return jsonify(
            status=overall,
            timestamp=datetime.now(UTC).isoformat(),
            checks=checks,
            version=app.config.get("APP_VERSION", "1.0.0"),
        )

    @app.get("/health/deep")
    def health_deep():
        from flask_login import current_user
        from werkzeug.exceptions import Forbidden, Unauthorized

        if not current_user.is_authenticated:
            raise Unauthorized()
        if not hasattr(current_user, "role") or current_user.role.value != "super_admin":
            raise Forbidden()

        import shutil

        test_app = app.test_client()
        with app.app_context():
            resp = test_app.get("/health")
            checks = resp.get_json() if resp.status_code == 200 else {}

        try:
            usage = shutil.disk_usage(".")
            checks["disk_detail"] = {
                "total_gb": round(usage.total / (1024**3), 1),
                "used_gb": round(usage.used / (1024**3), 1),
                "free_gb": round(usage.free / (1024**3), 1),
            }
        except Exception:
            checks["disk_detail"] = {}

        checks["response_times"] = {
            "avg_ms": round(sum(_response_times) / len(_response_times)) if _response_times else 0,
            "p95_ms": sorted(_response_times)[int(len(_response_times) * 0.95)] if _response_times else 0,
            "max_ms": max(_response_times) if _response_times else 0,
            "sample_count": len(_response_times),
        }

        return jsonify(checks)

    # ════════════════════════════════════════════════════════════
    # Legacy / user-facing URL aliases (E2E compatibility)
    # ════════════════════════════════════════════════════════════
    @app.get("/api/health")
    def api_health_legacy():
        return redirect(url_for("health"), code=307)

    @app.get("/content")
    def content_alias():
        return redirect(url_for("auth.login"), code=302)

    @app.get("/assessment")
    def assessment_alias():
        return redirect(url_for("auth.login"), code=302)

    @app.get("/grades")
    def grades_alias():
        return redirect(url_for("auth.login"), code=302)

    @app.errorhandler(401)
    def unauthorized(e):
        # طلبات API/health ترجع 401 JSON؛ متصفحات HTML تُوجَّه لصفحة الدخول
        if request.path.startswith(("/api/", "/health")) or not request.accept_mimetypes.accept_html:
            return jsonify({"error": "unauthorized"}), 401
        return redirect(url_for("auth.login"))

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

    @app.errorhandler(Exception)
    def handle_exception(e):
        # أخطاء HTTP المقصودة (401/403/404...) تمر لمعالجاتها — لا تُحوَّل إلى 500
        if isinstance(e, HTTPException):
            return e
        logger.exception("Unhandled exception: %s", e)
        db.session.rollback()
        return render_template("errors/500.html"), 500

    @app.template_filter("format_datetime")
    def _format_datetime(value, fmt="%Y-%m-%d %H:%M"):
        """تنسيق timestamp بشكل موحد في القوالب."""
        if not value:
            return "—"
        return value.strftime(fmt)

    @app.template_filter("format_date")
    def _format_date(value):
        """تنسيق تاريخ فقط."""
        if not value:
            return "—"
        return value.strftime("%Y-%m-%d")

    @app.template_filter("format_time")
    def _format_time(value):
        """تنسيق وقت فقط."""
        if not value:
            return "—"
        return value.strftime("%H:%M")

    @app.template_filter("relative_time")
    def _relative_time(value):
        """وقت نسبي (منذ X دقائق/ساعات)."""
        if not value:
            return "—"
        from datetime import UTC, datetime

        now = datetime.now(UTC) if value.tzinfo else datetime.utcnow()
        delta = now - value
        if delta.days > 365:
            return f"{delta.days // 365}y"
        if delta.days > 30:
            return f"{delta.days // 30}mo"
        if delta.days > 0:
            return f"{delta.days}d"
        if delta.seconds > 3600:
            return f"{delta.seconds // 3600}h"
        if delta.seconds > 60:
            return f"{delta.seconds // 60}m"
        return "now"

    return app
