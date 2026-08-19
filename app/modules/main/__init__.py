from flask import Blueprint, current_app, redirect, render_template, request, url_for
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


@bp.post("/set-locale/<lang>")
def set_locale(lang):
    available = current_app.config.get("LANGUAGES", ["ar"])
    if lang not in available:
        lang = current_app.config.get("DEFAULT_LOCALE", "ar")
    resp = redirect(request.referrer or url_for("main.index"))
    resp.set_cookie("locale", lang, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return resp
