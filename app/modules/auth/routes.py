"""مسارات المصادقة: تسجيل، دخول، خروج، إعادة تعيين كلمة مرور"""

from app.services.auth import authenticate, mark_login, register_user, request_password_reset
from app.services.auth import reset_password as reset_user_password
from flask import current_app, flash, make_response, redirect, render_template, url_for
from flask_babel import _
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload, selectinload

from . import bp
from .forms import ForgotPasswordForm, IndividualRegisterForm, LoginForm, RegisterForm, ResetPasswordForm


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
            school_join_code=form.school_join_code.data.strip().upper() if form.school_join_code.data else None,
        )
        if error:
            flash(_(error), "danger")
            return render_template("auth/register.html", form=form)
        flash(_("تم إنشاء الحساب بنجاح. حسابك في انتظار موافقة الإدارة. سيتم إشعارك عند القبول."), "success")
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
            is_first_login = user.last_login_at is None
            mark_login(user)
            resp = make_response(redirect(url_for("auth.dashboard")))
            if is_first_login:
                resp.set_cookie("azad_show_tour", "1", max_age=300, path="/")
            return resp
    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    from app.services.impersonation import clear_impersonation

    clear_impersonation()
    logout_user()
    flash(_("تم تسجيل الخروج."), "info")
    return redirect(url_for("auth.login"))


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password_alias():
    """Alias for /forgot — E2E compatibility."""
    return redirect(url_for("auth.forgot_password"), code=307)


@bp.route("/forgot", methods=["GET", "POST"])
def forgot_password():
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        token = request_password_reset(email)
        if token:
            reset_link = url_for("auth.reset_password", token=token, _external=True)
            current_app.logger.warning("[DEV] رابط إعادة التعيين: %s", reset_link)
        flash(_("إن كان البريد مسجلاً، ستصل رسالة إعادة التعيين."), "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot.html", form=form)


@bp.route("/reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    form = ResetPasswordForm()
    if form.validate_on_submit():
        error = reset_user_password(token, form.password.data)
        if error:
            flash(_(error), "danger")
            return redirect(url_for("auth.forgot_password"))
        flash(_("تم تحديث كلمة المرور. سجّل الدخول الآن."), "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset.html", form=form, token=token)


@bp.route("/register-individual", methods=["GET", "POST"])
def register_individual():
    from app.services.auth import register_individual as do_register_individual

    if current_user.is_authenticated:
        return redirect(url_for("auth.dashboard"))
    form = IndividualRegisterForm()
    if form.validate_on_submit():
        user, error = do_register_individual(
            email=form.email.data,
            name_ar=form.name_ar.data,
            password=form.password.data,
            grade_level=form.grade_level.data if form.grade_level.data else None,
        )
        if error:
            flash(_(error), "danger")
            return render_template("auth/register_individual.html", form=form)
        flash(_("تم إنشاء حسابك بنجاح! يمكنك تسجيل الدخول الآن."), "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/register_individual.html", form=form)


@bp.route("/dashboard")
@login_required
def dashboard():
    from app.extensions import db
    from app.models.billing import Subscription
    from app.models.class_room import ClassMember, ClassRoom
    from app.models.school import School
    from app.models.user import User, UserRole

    # Common data
    memberships = (
        ClassMember.query.filter_by(user_id=current_user.id, status="active")
        .options(
            selectinload(ClassMember.class_room).joinedload(ClassRoom.subject),
            selectinload(ClassMember.class_room).joinedload(ClassRoom.grade),
        )
        .all()
    )

    # Role-specific data
    school_count = 0
    user_count = 0
    class_count = 0
    subscription_count = 0
    my_school_class_count = 0
    my_school_student_count = 0
    my_school_teacher_count = 0
    my_school_subscription_count = 0

    if current_user.role == UserRole.super_admin:
        school_count = School.query.count()
        user_count = User.query.count()
        class_count = ClassRoom.query.count()
        subscription_count = Subscription.query.filter_by(status="active").count()

    elif current_user.role == UserRole.school_admin:
        from app.core.tenancy import current_school_id

        school_id = current_school_id()
        if school_id:
            from app.models.user import UserRole, UserRoleLink

            my_school_class_count = ClassRoom.query.filter_by(school_id=school_id, deleted_at=None).count()
            my_school_student_count = (
                db.session.query(func.count(User.id))
                .join(ClassMember, User.id == ClassMember.user_id)
                .join(ClassRoom, ClassMember.class_id == ClassRoom.id)
                .filter(ClassRoom.school_id == school_id, ClassMember.status == "active", User.role == UserRole.student)
                .scalar()
                or 0
            )
            my_school_teacher_count = (
                User.query.join(UserRoleLink, User.id == UserRoleLink.user_id)
                .filter(
                    UserRoleLink.school_id == current_school_id(), UserRoleLink.is_active, User.role == UserRole.teacher
                )
                .count()
            )
            my_school_subscription_count = Subscription.query.filter_by(
                school_id=current_school_id(), status="active"
            ).count()

    return render_template(
        "auth/dashboard.html",
        school_count=school_count,
        user_count=user_count,
        class_count=class_count,
        subscription_count=subscription_count,
        memberships=memberships,
        my_classes=(
            ClassRoom.query.filter_by(teacher_id=current_user.id, deleted_at=None)
            .options(
                joinedload(ClassRoom.subject),
                joinedload(ClassRoom.grade),
            )
            .all()
            if current_user.role == UserRole.teacher
            else []
        ),
        my_school_class_count=my_school_class_count,
        my_school_student_count=my_school_student_count,
        my_school_teacher_count=my_school_teacher_count,
        my_school_subscription_count=my_school_subscription_count,
        children_memberships={},
    )
