"""إعدادات التطبيق — مقروءة من .env فقط (D4)"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    DEFAULT_LOCALE = os.getenv("DEFAULT_LOCALE", "ar")
    LANGUAGES = ["ar", "en"]

    # المرفوعات (D7): خارج المجلد العام
    UPLOAD_FOLDER = BASE_DIR / "instance" / "uploads"
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024
    ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp", "gif", "mp4", "webm", "mp3", "docx", "pptx", "xlsx"}

    MAIL_SERVER = os.getenv("MAIL_SERVER", "")
    MAIL_PORT = int(os.getenv("MAIL_PORT", 587))
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "1") == "1"
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "")

    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")

    BACKUP_DIR = BASE_DIR / "backups"

    # === أمان ===
    # DEBUG من متغير بيئة (إيقاف في الإنتاج)
    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"
    TESTING = False

    # جلسة آمنة
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "1") == "1"  # HTTPS فقط
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 3600  # ساعة واحدة

    # CSRF
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600
    WTF_CSRF_SSL_STRICT = True

    # معدل الطلبات (Flask-Limiter)
    RATELIMIT_DEFAULT = "200 per minute"
    RATELIMIT_STORAGE_URL = os.getenv("RATELIMIT_STORAGE_URL", "memory://")
    RATELIMIT_STRATEGY = "fixed-window"

    # Talisman / CSP
    TALISMAN_ENABLED = os.getenv("TALISMAN_ENABLED", "1") == "1"
    TALISMAN_FORCE_HTTPS = os.getenv("TALISMAN_FORCE_HTTPS", "1") == "1"
    TALISMAN_STRICT_TRANSPORT_SECURITY = True
    TALISMAN_STRICT_TRANSPORT_SECURITY_MAX_AGE = 31536000
    TALISMAN_CONTENT_SECURITY_POLICY = {
        "default-src": "'self'",
        "script-src": "'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com",
        "style-src": "'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net",
        "font-src": "'self' https://fonts.gstatic.com https://cdn.jsdelivr.net",
        "img-src": "'self' data: https:",
        "connect-src": "'self' https://api.stripe.com",
        "frame-src": "'self' https://meet.jit.si https://meet.jit.si",
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

    # سياسة كلمات المرور
    PASSWORD_MIN_LENGTH = 10
    PASSWORD_REQUIRE_UPPER = True
    PASSWORD_REQUIRE_LOWER = True
    PASSWORD_REQUIRE_DIGIT = True
    PASSWORD_REQUIRE_SPECIAL = True
    PASSWORD_HISTORY_COUNT = 5

    # قفل الحساب
    LOGIN_MAX_ATTEMPTS = 5
    LOGIN_LOCKOUT_DURATION = 900  # 15 دقيقة

    # 2FA
    TOTP_ISSUER = "Azad E-School"
