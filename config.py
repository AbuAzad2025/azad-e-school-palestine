"""إعدادات التطبيق — بيئات منفصلة (D4).

الاستخدام:
    from config import config_by_name
    app.config.from_object(config_by_name[env])

المتغيرات البيئية المطلوبة:
    FLASK_ENV = development | production | testing
    SECRET_KEY (في كل البيئات)
    DATABASE_URL (في كل البيئات غير testing)
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class _BaseConfig:
    """الإعدادات المشتركة بين كل البيئات."""

    SECRET_KEY = os.getenv("SECRET_KEY")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_size": int(os.getenv("DB_POOL_SIZE", "10")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "20")),
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "1800")),
        "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT", "30")),
        "connect_args": {
            "connect_timeout": 10,
            "application_name": "azad-eschool",
            "options": "-c statement_timeout=30000",
        },
    }

    DEFAULT_LOCALE = os.getenv("DEFAULT_LOCALE", "ar")
    LANGUAGES = ["ar", "en"]

    UPLOAD_FOLDER = BASE_DIR / "instance" / "uploads"
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024
    ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp", "gif", "mp4", "webm", "mp3", "docx", "pptx", "xlsx"}

    MAIL_SERVER = os.getenv("MAIL_SERVER", "")
    MAIL_PORT = int(os.getenv("MAIL_PORT", 587))
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "1") == "1"
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "")
    EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "0") == "1"

    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")

    BACKUP_DIR = BASE_DIR / "backups"

    # === أمان ===
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 3600

    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600
    WTF_CSRF_SSL_STRICT = True

    RATELIMIT_DEFAULT = "200 per minute"
    RATELIMIT_STORAGE_URL = os.getenv("RATELIMIT_STORAGE_URL", "memory://")
    RATELIMIT_STRATEGY = "fixed-window"

    TALISMAN_ENABLED = os.getenv("TALISMAN_ENABLED", "1") == "1"
    TALISMAN_FORCE_HTTPS = os.getenv("TALISMAN_FORCE_HTTPS", "1") == "1"
    TALISMAN_STRICT_TRANSPORT_SECURITY = True
    TALISMAN_STRICT_TRANSPORT_SECURITY_MAX_AGE = 31536000
    TALISMAN_CONTENT_SECURITY_POLICY = {
        "default-src": "'self'",
        "script-src": (
            "'self' 'unsafe-inline' "
            "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com "
            "https://browser.sentry-cdn.com https://plausible.io"
        ),
        "style-src": "'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net",
        "font-src": "'self' https://fonts.gstatic.com https://cdn.jsdelivr.net",
        "img-src": "'self' data: https:",
        "connect-src": ("'self' https://api.stripe.com https://*.sentry.io https://plausible.io"),
        "frame-src": "'self' https://meet.jit.si",
        "frame-ancestors": "'none'",
        "form-action": "'self'",
        "base-uri": "'self'",
        "object-src": "'none'",
    }
    TALISMAN_CONTENT_SECURITY_POLICY_REPORT_ONLY = False
    TALISMAN_REFERRER_POLICY = "strict-origin-when-cross-origin"
    TALISMAN_PERMISSIONS_POLICY = {
        "camera": "()",
        "microphone": "()",
        "geolocation": "()",
        "payment": "()",
    }

    PASSWORD_MIN_LENGTH = 10
    PASSWORD_REQUIRE_UPPER = True
    PASSWORD_REQUIRE_LOWER = True
    PASSWORD_REQUIRE_DIGIT = True
    PASSWORD_REQUIRE_SPECIAL = True
    PASSWORD_HISTORY_COUNT = 5

    LOGIN_MAX_ATTEMPTS = 5
    LOGIN_LOCKOUT_DURATION = 900

    TOTP_ISSUER = "Azad E-School"

    VIDEO_PROVIDER_DEFAULT = os.getenv("VIDEO_PROVIDER_DEFAULT", "jitsi")
    ZOOM_ACCOUNT_ID = os.getenv("ZOOM_ACCOUNT_ID", "")
    ZOOM_CLIENT_ID = os.getenv("ZOOM_CLIENT_ID", "")
    ZOOM_CLIENT_SECRET = os.getenv("ZOOM_CLIENT_SECRET", "")
    ZOOM_SDK_KEY = os.getenv("ZOOM_SDK_KEY", "")
    ZOOM_SDK_SECRET = os.getenv("ZOOM_SDK_SECRET", "")

    SENTRY_DSN = os.getenv("SENTRY_DSN", "")
    SENTRY_ENVIRONMENT = os.getenv("SENTRY_ENVIRONMENT", "production")
    SENTRY_TRACES_SAMPLE_RATE = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1"))

    BACKUP_ENABLED = os.getenv("BACKUP_ENABLED", "0") == "1"
    BACKUP_S3_ENDPOINT = os.getenv("BACKUP_S3_ENDPOINT", "")
    BACKUP_S3_BUCKET = os.getenv("BACKUP_S3_BUCKET", "")
    BACKUP_S3_ACCESS_KEY = os.getenv("BACKUP_S3_ACCESS_KEY", "")
    BACKUP_S3_SECRET_KEY = os.getenv("BACKUP_S3_SECRET_KEY", "")
    BACKUP_LOCAL_RETENTION_DAYS = int(os.getenv("BACKUP_LOCAL_RETENTION_DAYS", "7"))

    ALERT_EMAIL = os.getenv("ALERT_EMAIL", "")

    PLAUSIBLE_SCRIPT_URL = os.getenv("PLAUSIBLE_SCRIPT_URL", "")
    WHATSAPP_BUSINESS_NUMBER = os.getenv("WHATSAPP_BUSINESS_NUMBER", "")

    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_JSON = os.getenv("LOG_JSON", "0") == "1"

    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "").split(",") if os.getenv("CORS_ORIGINS") else []
    CORS_SUPPORTS_CREDENTIALS = os.getenv("CORS_SUPPORTS_CREDENTIALS", "1") == "1"
    CORS_ALLOW_HEADERS = ["Content-Type", "X-CSRFToken", "Authorization"]

    SWAGGER_ENABLED = os.getenv("SWAGGER_ENABLED", "0") == "1"
    SWAGGER_HOST = os.getenv("SWAGGER_HOST", "")


class DevelopmentConfig(_BaseConfig):
    """بيئة التطوير — مريحة للمطوّر، أقل حماية."""

    DEBUG = True
    TESTING = False
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "postgresql://localhost:5432/azad_eschool_dev")
    SESSION_COOKIE_SECURE = False
    TALISMAN_FORCE_HTTPS = False
    TALISMAN_STRICT_TRANSPORT_SECURITY = False
    WTF_CSRF_SSL_STRICT = False
    SWAGGER_ENABLED = os.getenv("SWAGGER_ENABLED", "1") == "1"
    LOG_JSON = False
    LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5000,http://127.0.0.1:5000").split(",")


class ProductionConfig(_BaseConfig):
    """بيئة الإنتاج — أقصى حماية وأداء."""

    DEBUG = False
    TESTING = os.getenv("TESTING", "0") == "1"
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "1") == "1"
    LOG_JSON = os.getenv("LOG_JSON", "1") == "1"
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    SWAGGER_ENABLED = os.getenv("SWAGGER_ENABLED", "0") == "1"
    """بيئة الإنتاج — أقصى حماية وأداء."""

    DEBUG = False
    TESTING = False
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "1") == "1"
    LOG_JSON = os.getenv("LOG_JSON", "1") == "1"
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    SWAGGER_ENABLED = os.getenv("SWAGGER_ENABLED", "0") == "1"


class TestingConfig(_BaseConfig):
    """بيئة الاختبار — SQLite in-memory، أمان مخفّض."""

    DEBUG = True
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///:memory:")
    SQLALCHEMY_ENGINE_OPTIONS = {}
    SESSION_COOKIE_SECURE = False
    TALISMAN_ENABLED = False
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    EMAIL_ENABLED = False
    SWAGGER_ENABLED = False
    LOG_LEVEL = "WARNING"


config_by_name: dict[str, type] = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}

# backwards compatibility — التطبيقات القديمة تستورد Config مباشرة
_env = os.getenv("FLASK_ENV") or os.getenv("APP_ENV", "production")
Config = config_by_name.get(_env, ProductionConfig)
Config = config_by_name.get(os.getenv("FLASK_ENV", "production"), ProductionConfig)
