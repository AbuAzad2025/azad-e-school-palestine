"""مسارات المصادقة: تسجيل، دخول، خروج، تفعيل بريد، إعادة تعيين كلمة مرور"""

from app.core.tokens import make_activation_token, read_token
from app.models.user import User
from app.services.auth import authenticate, mark_login, register_user
from app.services.auth import confirm_email as confirm_user_email
from flask import current_app, flash, redirect, render_template, request, url_for
from flask_babel import _
from flask_login import current_user, login_required, login_user, logout_user

from . import bp
from .forms import ForgotPasswordForm, LoginForm, RegisterForm, ResetPasswordForm


def _dev_activation_link(user):
    """بدون خادم بريد فعلي (M1): يعيد رابط التفعيل للفحص في الطرفية."""
    token = make_activation_token(user.id, user.email)
    return url_for("auth.confirm_email", token=token, _external=True)


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("auth.dashboard"))
    form = RegisterForm()
    if form.validate_on_submit():
        user, error = register_user(
            email=form.email.data,
            name_ar=form.name_ar.data,
            role=form.role.data,
            password=form.password.data,
        )
        if error:
            flash(_(error), "danger")
            return render_template("auth/register.html", form=form)
        if request.host.startswith("127.0.0.1") or request.host.startswith("localhost"):
            current_app.logger.warning("[DEV] تفعيل الحساب: %s", _dev_activation_link(user))
        flash(_("تم إنشاء الحساب. فعّل بريدك الإلكتروني عبر الرابط (يُطبع في الطرفية بوضع التطوير)."), "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/register.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("auth.dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        user, error = authenticate(form.email.data, form.password.data)
        if error:
            flash(_(error), "danger")
        elif user is not None:
            login_user(user)
            mark_login(user)
            return redirect(url_for("auth.dashboard"))
    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash(_("تم تسجيل الخروج."), "info")
    return redirect(url_for("auth.login"))


@bp.route("/confirm/<token>")
def confirm_email(token):
    uid, email = read_token(token)
    if uid and email and confirm_user_email(uid, email):
        flash(_("تم تفعيل بريدك الإلكتروني. سجّل الدخول الآن."), "success")
    else:
        flash(_("رابط التفعيل غير صالح أو منتهي."), "danger")
    return redirect(url_for("auth.login"))


@bp.route("/forgot", methods=["GET", "POST"])
def forgot_password():
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            current_app.logger.warning("[DEV] إعادة تعيين كلمة المرور لـ %s", email)
        flash(_("إن كان البريد مسجلاً، ستصل رسالة إعادة التعيين."), "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot.html", form=form)


@bp.route("/reset", methods=["GET", "POST"])
def reset_password():
    form = ResetPasswordForm()
    if form.validate_on_submit():
        flash(_("في وضع التطوير، تُدار إعادة التعيين عبر رابط مؤمن. أرسلنا تفاصيل لاحقاً."), "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset.html", form=form)


@bp.route("/dashboard")
@login_required
def dashboard():
    return render_template("auth/dashboard.html")
