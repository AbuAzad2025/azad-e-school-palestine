"""مسارات المصادقة: تسجيل، دخول، خروج، تفعيل بريد، إعادة تعيين كلمة مرور"""
from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.core.security import hash_password, verify_password
from app.core.tokens import make_activation_token, read_token
from app.extensions import db

from . import bp
from .forms import ForgotPasswordForm, LoginForm, RegisterForm, ResetPasswordForm
from app.models.user import User, UserRole


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
        email = form.email.data.strip().lower()
        if User.query.filter_by(email=email).first():
            flash("هذا البريد مسجّل مسبقاً.", "danger")
            return render_template("auth/register.html", form=form)
        role_value = form.role.data
        role = UserRole(role_value)
        user = User(
            email=email,
            name_ar=form.name_ar.data.strip(),
            role=role,
            password_hash=hash_password(form.password.data),
            is_verified=False,
        )
        db.session.add(user)
        db.session.commit()
        if request.host.startswith("127.0.0.1") or request.host.startswith("localhost"):
            current_app.logger.warning("[DEV] تفعيل الحساب: %s", _dev_activation_link(user))
        flash("تم إنشاء الحساب. فعّل بريدك الإلكتروني عبر الرابط (في وضع التطوير يُطبع في الطرفية).", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/register.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("auth.dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = User.query.filter_by(email=email).first()
        if user and verify_password(user.password_hash, form.password.data):
            if not user.is_active:
                flash("حسابك معطّل. تواصل مع الإدارة.", "danger")
            elif not user.is_verified:
                flash("فعّل بريدك الإلكتروني أولاً.", "warning")
            else:
                login_user(user)
                user.last_login_at = db.func.now()
                db.session.commit()
                return redirect(url_for("auth.dashboard"))
        else:
            flash("بريد أو كلمة مرور غير صحيحة.", "danger")
    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("تم تسجيل الخروج.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/confirm/<token>")
def confirm_email(token):
    uid, email = read_token(token)
    user = db.session.get(User, uid) if uid else None
    if user and user.email == email:
        user.is_verified = True
        db.session.commit()
        flash("تم تفعيل بريدك الإلكتروني. سجّل الدخول الآن.", "success")
    else:
        flash("رابط التفعيل غير صالح أو منتهي.", "danger")
    return redirect(url_for("auth.login"))


@bp.route("/forgot", methods=["GET", "POST"])
def forgot_password():
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            current_app.logger.warning("[DEV] إعادة تعيين كلمة المرور لـ %s", email)
        flash("إن كان البريد مسجلاً، ستصل رسالة إعادة التعيين.", "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot.html", form=form)


@bp.route("/reset", methods=["GET", "POST"])
def reset_password():
    form = ResetPasswordForm()
    if form.validate_on_submit():
        flash("في وضع التطوير، تُدار إعادة التعيين عبر رابط مؤمن. أرسلنا تفاصيل لاحقاً.", "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset.html", form=form)


@bp.route("/dashboard")
@login_required
def dashboard():
    return render_template("auth/dashboard.html")
