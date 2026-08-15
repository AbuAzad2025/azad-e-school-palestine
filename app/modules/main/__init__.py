"""Blueprint الرئيسي — الصفحة الافتتاحية + مبدّل اللغة"""

from flask import Blueprint, current_app, redirect, render_template, request, url_for

bp = Blueprint("main", __name__)


@bp.get("/")
def index():
    return render_template("main/index.html")


@bp.post("/set-locale/<lang>")
def set_locale(lang):
    """يحوّل اللغة (ar/en) عبر كوكي ويُعيد للمصدر. كلاسيكي وبدون DB."""
    available = current_app.config.get("LANGUAGES", ["ar"])
    if lang not in available:
        lang = current_app.config.get("DEFAULT_LOCALE", "ar")
    resp = redirect(request.referrer or url_for("main.index"))
    resp.set_cookie("locale", lang, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return resp
