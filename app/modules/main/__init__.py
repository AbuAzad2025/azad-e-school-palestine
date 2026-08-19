from flask import Blueprint, current_app, redirect, render_template, request, url_for
from flask_babel import _
from flask_login import current_user

bp = Blueprint("main", __name__)


@bp.get("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("auth.dashboard"))
    stats = {"student_count": 0, "lesson_count": 150, "school_count": 0}
    try:
        from app.models.school import School
        from app.models.user import User

        stats["student_count"] = User.query.filter_by(role="student", is_active=True).count()
        stats["school_count"] = School.query.filter_by(is_active=True).count()
    except Exception:
        pass
    return render_template("landing.html", stats=stats)


@bp.get("/pricing")
def pricing():
    """صفحة الأسعار العامة — لا تحتاج تسجيل دخول."""
    plans = [
        {
            "name": _("الفرد الأساسي"),
            "price": "29",
            "currency": "₪",
            "period": "/شهر",
            "features": [
                _("دورة واحدة"),
                _("اختبارات أساسية"),
                _("دعم عبر البريد"),
            ],
            "cta_text": _("سجّل الآن"),
            "cta_url": url_for("auth.register_individual"),
            "popular": False,
        },
        {
            "name": _("الفرد Pro"),
            "price": "59",
            "currency": "₪",
            "period": "/شهر",
            "features": [
                _("5 دورات"),
                _("اختبارات متقدمة"),
                _("دروس خصوصية"),
                _("شهادات إتمام"),
            ],
            "cta_text": _("سجّل الآن"),
            "cta_url": url_for("auth.register_individual"),
            "popular": True,
        },
        {
            "name": _("المدرسة Pro"),
            "price": "499",
            "currency": "₪",
            "period": "/شهر",
            "features": [
                _("50 طالب"),
                _("إدارة الدرجات"),
                _("تقارير أولياء الأمور"),
                _("تصدير Excel"),
            ],
            "cta_text": _("تواصل معنا"),
            "cta_url": url_for("auth.register"),
            "popular": False,
        },
        {
            "name": _("المدرسة Premium"),
            "price": "999",
            "currency": "₪",
            "period": "/شهر",
            "features": [
                _("طلاب غير محدود"),
                _("ذكاء اصطناعي"),
                _("CRM مدمج"),
                _("Zoom مدمج"),
                _("Backup S3"),
            ],
            "cta_text": _("تواصل معنا"),
            "cta_url": url_for("auth.register"),
            "popular": False,
        },
    ]
    return render_template("pricing.html", plans=plans)


@bp.post("/set-locale/<lang>")
def set_locale(lang):
    available = current_app.config.get("LANGUAGES", ["ar"])
    if lang not in available:
        lang = current_app.config.get("DEFAULT_LOCALE", "ar")
    resp = redirect(request.referrer or url_for("main.index"))
    resp.set_cookie("locale", lang, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return resp
