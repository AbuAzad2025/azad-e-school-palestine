"""مسارات لوحة المشرف — إدارة كاملة للمنصة"""

from datetime import datetime, timedelta
from decimal import Decimal

from app.core.permissions import _has_any
from app.extensions import db
from app.models.ai import AiUsageLog
from app.models.billing import ManualPayment, Subscription
from app.models.class_room import ClassRoom
from app.models.content import Lesson
from app.models.gradebook import Assignment
from app.models.school import School
from app.models.user import User, UserApprovalStatus, UserRole, UserRoleLink
from flask import abort, flash, redirect, render_template, request, url_for
from flask_babel import _
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.orm import joinedload, selectinload

from . import bp


@bp.app_context_processor
def admin_nav_context():
    """عدّادات شريط التنقل في لوحة المشرف (تُحقن لصفحات اللوحة فقط)."""
    from app.models.billing import ManualPayment, Subscription

    return {
        "subs_pending": Subscription.query.filter_by(status="pending").count(),
        "pending_payments": ManualPayment.query.filter_by(status="pending").count(),
    }


@bp.before_request
def require_admin():
    if request.endpoint == "admin.impersonate_exit":
        return None  # جلسة الانتحال ليست سوبر أدمن — مسار الخروج مفتوح لها
    if request.endpoint == "admin.school_admin_dashboard":
        if not current_user.is_authenticated:
            abort(401)
        if not _has_any(UserRole.super_admin, UserRole.school_admin):
            abort(403)
        return None  # لا يطبّق قبل_request السوبر أدمن فقط
    if not current_user.is_authenticated:
        abort(401)
    if not _has_any(UserRole.super_admin):
        abort(403)


@bp.get("/")
@login_required
def dashboard():
    """لوحة المشرف الرئيسية — إحصائيات شاملة"""
    # إحصائيات عامة
    stats = {
        "schools_total": School.query.filter_by(is_active=True).count(),
        "users_total": User.query.filter_by(is_active=True).count(),
        "teachers_total": User.query.filter_by(role=UserRole.teacher, is_active=True).count(),
        "students_total": User.query.filter_by(role=UserRole.student, is_active=True).count(),
        "classes_total": ClassRoom.query.filter_by(is_active=True).count(),
        "lessons_total": Lesson.query.filter_by(deleted_at=None).count(),
        "assignments_total": Assignment.query.count(),
    }

    # إحصائيات الاشتراكات
    subs_active = Subscription.query.filter_by(status="active").count()
    subs_pending = Subscription.query.filter_by(status="pending").count()
    subs_expired = Subscription.query.filter_by(status="expired").count()
    revenue_total = db.session.query(func.sum(Subscription.price)).filter(
        Subscription.status.in_(["active", "expired"])
    ).scalar() or Decimal("0")

    # إحصائيات AI
    ai_requests_30d = AiUsageLog.query.filter(AiUsageLog.created_at >= datetime.utcnow() - timedelta(days=30)).count()
    ai_cost_30d = db.session.query(func.sum(AiUsageLog.estimated_cost_usd)).filter(
        AiUsageLog.created_at >= datetime.utcnow() - timedelta(days=30)
    ).scalar() or Decimal("0")

    # مدفوعات معلقة
    pending_payments = ManualPayment.query.filter_by(status="pending").count()

    # نشاط حديث
    recent_users = User.query.filter_by(is_active=True).order_by(User.created_at.desc()).limit(10).all()
    recent_schools = School.query.filter_by(is_active=True).order_by(School.created_at.desc()).limit(5).all()

    return render_template(
        "admin/dashboard.html",
        stats=stats,
        subs_active=subs_active,
        subs_pending=subs_pending,
        subs_expired=subs_expired,
        revenue_total=revenue_total,
        ai_requests_30d=ai_requests_30d,
        ai_cost_30d=ai_cost_30d,
        pending_payments=pending_payments,
        recent_users=recent_users,
        recent_schools=recent_schools,
    )


# ======================================================================
# إدارة المستخدمين
# ======================================================================
@bp.get("/users")
@login_required
def users_list():
    page = request.args.get("page", 1, type=int)
    role_filter = request.args.get("role", "")
    search = request.args.get("search", "")

    query = User.query.filter_by(is_active=True)

    if role_filter:
        query = query.filter_by(role=UserRole(role_filter))
    if search:
        query = query.filter((User.name_ar.ilike(f"%{search}%")) | (User.email.ilike(f"%{search}%")))

    pagination = query.order_by(User.created_at.desc()).paginate(page=page, per_page=25, error_out=False)

    return render_template(
        "admin/users_list.html",
        pagination=pagination,
        role_filter=role_filter,
        search=search,
        roles=UserRole,
    )


@bp.get("/users/<int:user_id>")
@login_required
def user_detail(user_id):
    user = User.query.options(selectinload(User.role_links).joinedload(UserRoleLink.school)).get_or_404(user_id)
    memberships = user.role_links
    return render_template("admin/user_detail.html", user=user, memberships=memberships)


@bp.post("/users/<int:user_id>/toggle")
@login_required
def user_toggle(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash(_("لا يمكنك تعطيل حسابك الخاص"), "warning")
    else:
        user.is_active = not user.is_active
        db.session.commit()
        flash(_("تم تحديث حالة المستخدم"), "success")
    return redirect(url_for("admin.user_detail", user_id=user_id))


# ======================================================================
# انتحال الصفة (سوبر أدمن → الأدوار الأدنى)
# ======================================================================
@bp.post("/users/<int:user_id>/impersonate")
@login_required
def user_impersonate(user_id):
    from app.services.impersonation import start_impersonation

    target = User.query.get_or_404(user_id)
    error = start_impersonation(target)
    if error:
        flash(_(error), "danger")
        return redirect(url_for("admin.user_detail", user_id=user_id))
    flash(
        _(
            "وضع انتحال الصفة: أنت تتصفح الآن كـ %(name)s — استخدم شريط الانتحال للعودة.",
            name=target.name_ar or target.email,
        ),
        "warning",
    )
    return redirect(url_for("auth.dashboard"))


@bp.post("/impersonate/exit")
@login_required
def impersonate_exit():
    from app.services.impersonation import stop_impersonation

    error = stop_impersonation()
    if error:
        flash(_(error), "danger")
        return redirect(url_for("auth.dashboard"))
    flash(_("عدت إلى حسابك الأصلي."), "success")
    return redirect(url_for("admin.dashboard"))


# ======================================================================
# إدارة المدارس
# ======================================================================
@bp.get("/schools")
@login_required
def schools_list():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("search", "")

    query = School.query.filter_by(is_active=True)
    if search:
        query = query.filter(School.name_ar.ilike(f"%{search}%"))

    pagination = query.order_by(School.created_at.desc()).paginate(page=page, per_page=25, error_out=False)

    return render_template("admin/schools_list.html", pagination=pagination, search=search)


@bp.get("/schools/<int:school_id>")
@login_required
def school_detail(school_id):
    school = School.query.get_or_404(school_id)
    classes = ClassRoom.query.filter_by(school_id=school_id, is_active=True).all()
    teachers = (
        User.query.join(User.role_links).filter(User.role_links.any(school_id=school_id, role=UserRole.teacher)).all()
    )
    return render_template("admin/school_detail.html", school=school, classes=classes, teachers=teachers)


# ======================================================================
# إدارة الاشتراكات والفوترة
# ======================================================================
@bp.get("/subscriptions")
@login_required
def subscriptions_list():
    page = request.args.get("page", 1, type=int)
    status_filter = request.args.get("status", "")

    query = Subscription.query
    if status_filter:
        query = query.filter_by(status=status_filter)

    pagination = (
        query.options(
            joinedload(Subscription.user),
            joinedload(Subscription.plan),
        )
        .order_by(Subscription.created_at.desc())
        .paginate(page=page, per_page=25, error_out=False)
    )

    return render_template(
        "admin/subscriptions_list.html",
        pagination=pagination,
        status_filter=status_filter,
    )


@bp.post("/subscriptions/<int:sub_id>/cancel")
@login_required
def subscription_cancel(sub_id):
    sub = Subscription.query.get_or_404(sub_id)
    sub.status = "cancelled"
    db.session.commit()
    flash(_("تم إلغاء الاشتراك"), "success")
    return redirect(url_for("admin.subscriptions_list"))


@bp.get("/payments/pending")
@login_required
def pending_payments():
    payments = (
        ManualPayment.query.filter_by(status="pending")
        .options(
            joinedload(ManualPayment.subscription).joinedload(Subscription.user),
            joinedload(ManualPayment.subscription).joinedload(Subscription.plan),
            joinedload(ManualPayment.receipts),
        )
        .order_by(ManualPayment.created_at.desc())
        .all()
    )
    return render_template("admin/pending_payments.html", payments=payments)


@bp.post("/payments/<int:payment_id>/approve")
@login_required
def payment_approve(payment_id):
    payment = ManualPayment.query.get_or_404(payment_id)
    from app.services.billing import approve_payment

    approve_payment(payment, reviewer_id=current_user.id)
    from app.services.email import send_payment_approved_email

    send_payment_approved_email(payment)
    flash(_("تم اعتماد الدفع وتفعيل الاشتراك"), "success")
    return redirect(url_for("admin.pending_payments"))


@bp.post("/payments/<int:payment_id>/reject")
@login_required
def payment_reject(payment_id):
    payment = ManualPayment.query.get_or_404(payment_id)
    from app.services.billing import reject_payment

    reject_payment(payment, reviewer_id=current_user.id)
    from app.services.email import send_payment_rejected_email

    send_payment_rejected_email(payment)
    flash(_("تم رفض الدفع"), "warning")
    return redirect(url_for("admin.pending_payments"))


# ======================================================================
# إدارة AI
# ======================================================================
@bp.get("/ai/usage")
@login_required
def ai_usage():
    days = request.args.get("days", 30, type=int)
    from app.services.ai import get_ai_service

    ai_service = get_ai_service()
    stats = ai_service.get_usage_stats(days=days)
    return render_template("admin/ai_usage.html", stats=stats, days=days)


# ======================================================================
# النسخ الاحتياطي
# ======================================================================
@bp.get("/backups")
@login_required
def backups_list():
    import os

    backup_dir = os.getenv("BACKUP_DIR", "backups")
    backups = []
    if os.path.exists(backup_dir):
        for f in sorted(os.listdir(backup_dir), reverse=True):
            if f.endswith(".sql") or f.endswith(".sql.gz"):
                path = os.path.join(backup_dir, f)
                stat = os.stat(path)
                backups.append(
                    {
                        "name": f,
                        "size": stat.st_size,
                        "created": datetime.fromtimestamp(stat.st_mtime),
                    }
                )
    return render_template("admin/backups.html", backups=backups)


@bp.post("/backups/create")
@login_required
def backup_create():
    """إنشاء نسخة احتياطية يدوية"""
    import os
    import subprocess

    backup_dir = os.getenv("BACKUP_DIR", "backups")
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{timestamp}.sql"
    filepath = os.path.join(backup_dir, filename)

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        flash(_("DATABASE_URL غير مضبوط"), "danger")
        return redirect(url_for("admin.backups_list"))

    try:
        result = subprocess.run(["pg_dump", db_url, "-f", filepath], capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            flash(_("تم إنشاء النسخة الاحتياطية بنجاح"), "success")
        else:
            flash(f"فشل النسخ الاحتياطي: {result.stderr}", "danger")
    except Exception as e:
        flash(f"خطأ: {e}", "danger")

    return redirect(url_for("admin.backups_list"))


@bp.post("/backups/<path:filename>/restore")
@login_required
def backup_restore(filename):
    """استعادة نسخة احتياطية — يتطلب تأكيد"""
    import os
    import subprocess

    backup_dir = os.getenv("BACKUP_DIR", "backups")
    filepath = os.path.join(backup_dir, filename)

    if not os.path.exists(filepath):
        flash(_("الملف غير موجود"), "danger")
        return redirect(url_for("admin.backups_list"))

    # تأكيد مزدوج
    if request.form.get("confirm") != "yes":
        flash(_("يجب كتابة 'yes' للتأكيد"), "danger")
        return redirect(url_for("admin.backups_list"))

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        flash(_("DATABASE_URL غير مضبوط"), "danger")
        return redirect(url_for("admin.backups_list"))
    try:
        result = subprocess.run(["psql", db_url, "-f", filepath], capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            flash(_("تمت الاستعادة بنجاح"), "success")
        else:
            flash(f"فشل الاستعادة: {result.stderr}", "danger")
    except Exception as e:
        flash(f"خطأ: {e}", "danger")

    return redirect(url_for("admin.backups_list"))


# ======================================================================
# إعدادات النظام
# ======================================================================
@bp.get("/settings")
@login_required
def settings():
    from app.models.system import Setting

    settings = {s.key: s for s in Setting.query.all()}
    return render_template("admin/settings.html", settings=settings)


# ======================================================================
# لوحة مشرف المدرسة — عرض مخصص
# ======================================================================
@bp.get("/school-admin")
@login_required
def school_admin_dashboard():
    from app.core.tenancy import current_school_id
    from app.models.class_room import ClassMember, ClassRoom
    from app.models.content import Lesson
    from app.models.gradebook import Assignment
    from app.services.finance import school_revenue_summary

    school_id = current_school_id()
    if not school_id:
        return redirect(url_for("admin.dashboard"))

    class_count = ClassRoom.query.filter_by(school_id=school_id, deleted_at=None, is_active=True).count()
    student_count = (
        db.session.query(func.count(User.id))
        .join(ClassMember, User.id == ClassMember.user_id)
        .join(ClassRoom, ClassMember.class_id == ClassRoom.id)
        .filter(ClassRoom.school_id == school_id, ClassMember.status == "active", User.role == UserRole.student)
        .scalar()
        or 0
    )
    teacher_count = (
        User.query.join(UserRoleLink, User.id == UserRoleLink.user_id)
        .filter(UserRoleLink.school_id == school_id, UserRoleLink.is_active, User.role == UserRole.teacher)
        .count()
    )
    lesson_count = (
        Lesson.query.join(ClassRoom, Lesson.class_id == ClassRoom.id)
        .filter(ClassRoom.school_id == school_id)
        .filter(Lesson.deleted_at.is_(None))
        .count()
    )
    assignment_count = (
        Assignment.query.join(ClassRoom, Assignment.class_id == ClassRoom.id)
        .filter(ClassRoom.school_id == school_id)
        .count()
    )
    revenue = school_revenue_summary(school_id)

    return render_template(
        "admin/school_admin_dashboard.html",
        school_id=school_id,
        class_count=class_count,
        student_count=student_count,
        teacher_count=teacher_count,
        lesson_count=lesson_count,
        assignment_count=assignment_count,
        revenue=revenue,
    )


@bp.post("/settings")
@login_required
def settings_save():
    from app.models.system import Setting

    for key, value in request.form.items():
        if key == "csrf_token":
            continue
        setting = Setting.query.filter_by(key=key).first()
        if setting:
            setting.value = value
        else:
            setting = Setting(key=key, value=value)
            db.session.add(setting)
    db.session.commit()
    flash(_("تم حفظ الإعدادات"), "success")
    return redirect(url_for("admin.settings"))


# ======================================================================
# إدارة تسجيلات المستخدمين المعلقة (موافقة السوبر أدمن)
# ======================================================================
@bp.get("/registrations/pending")
@login_required
def pending_registrations():
    """عرض قائمة التسجيلات المعلقة موافقة السوبر أدمن"""
    page = request.args.get("page", 1, type=int)
    search = request.args.get("search", "")

    query = User.query.filter_by(approval_status=UserApprovalStatus.pending, is_active=True)
    if search:
        query = query.filter((User.name_ar.ilike(f"%{search}%")) | (User.email.ilike(f"%{search}%")))

    pagination = query.order_by(User.created_at.desc()).paginate(page=page, per_page=25, error_out=False)

    return render_template(
        "admin/pending_registrations.html",
        pagination=pagination,
        search=search,
    )


@bp.post("/registrations/<int:user_id>/approve")
@login_required
def registration_approve(user_id):
    """قبول تسجيل مستخدم"""
    user = User.query.get_or_404(user_id)
    if user.approval_status != UserApprovalStatus.pending:
        flash(_("هذا المستخدم ليس في حالة انتظار"), "warning")
        return redirect(url_for("admin.pending_registrations"))

    user.approval_status = UserApprovalStatus.approved
    db.session.commit()
    from app.services.email import send_welcome_email

    send_welcome_email(user)
    flash(_("تم قبول المستخدم بنجاح. يمكنه الآن تسجيل الدخول."), "success")
    return redirect(url_for("admin.pending_registrations"))


@bp.post("/registrations/<int:user_id>/reject")
@login_required
def registration_reject(user_id):
    """رفض تسجيل مستخدم"""
    user = User.query.get_or_404(user_id)
    if user.approval_status != UserApprovalStatus.pending:
        flash(_("هذا المستخدم ليس في حالة انتظار"), "warning")
        return redirect(url_for("admin.pending_registrations"))

    user.approval_status = UserApprovalStatus.rejected
    db.session.commit()
    flash(_("تم رفض تسجيل المستخدم."), "warning")
    return redirect(url_for("admin.pending_registrations"))
