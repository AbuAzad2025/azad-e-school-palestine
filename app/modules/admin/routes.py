"""مسارات لوحة المشرف — إدارة كاملة للمنصة"""

import os
import shutil
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.db import tx
from app.core.permissions import _has_any, role_required
from app.extensions import db
from app.models.ai import AiUsageLog
from app.models.billing import ManualPayment, Subscription
from app.models.class_room import ClassRoom
from app.models.content import Lesson
from app.models.gradebook import Assignment
from app.models.school import School
from app.models.user import User, UserApprovalStatus, UserRole, UserRoleLink
from app.services.revenue import get_revenue_dashboard_data
from flask import abort, flash, redirect, render_template, request, url_for
from flask_babel import _
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.orm import joinedload, selectinload

from . import bp


def _find_pg_tool(name: str) -> str:
    """Find pg_dump / psql: PATH first, then common Windows locations."""
    on_path = shutil.which(name)
    if on_path:
        return on_path
    for base in (
        os.path.expandvars(r"%ProgramFiles%\PostgreSQL"),
        os.path.expandvars(r"%ProgramFiles(x86)%\PostgreSQL"),
    ):
        if not os.path.isdir(base):
            continue
        for version_dir in sorted(os.listdir(base), reverse=True):
            candidate = os.path.join(base, version_dir, "bin", f"{name}.exe")
            if os.path.isfile(candidate):
                return candidate
    return name


PG_DUMP = _find_pg_tool("pg_dump")
PSQL = _find_pg_tool("psql")


@bp.app_context_processor
def admin_nav_context():
    """عدّادات شريط التنقل في لوحة المشرف (تُحقن لصفحات اللوحة فقط)."""
    from app.models.billing import ManualPayment, Subscription

    return {
        "subs_pending": Subscription.query.filter_by(status="pending").count(),
        "pending_payments": ManualPayment.query.filter_by(status="pending").count(),
        "pending_reg_count": User.query.filter_by(approval_status=UserApprovalStatus.pending, is_active=True).count(),
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

    # بيانات الرسوم البيانية
    months = []
    now = datetime.utcnow()
    for i in range(5, -1, -1):
        d = now - timedelta(days=i * 30)
        months.append(d.strftime("%Y-%m"))
    signup_counts = Counter(
        u.created_at.strftime("%Y-%m")
        for u in User.query.filter(User.created_at >= now - timedelta(days=180)).all()
        if u.created_at
    )
    chart_signups = [{"month": m, "count": signup_counts.get(m, 0)} for m in months]

    subs_by_status: dict[str, int] = {
        status: count
        for status, count in db.session.query(Subscription.status, func.count(Subscription.id))
        .group_by(Subscription.status)
        .all()
    }
    chart_subscriptions = [
        {"status": status, "count": subs_by_status.get(status, 0)}
        for status in ("active", "pending", "expired", "pending_review")
    ]

    revenue_by_month: dict[str, float] = {}
    for sub in Subscription.query.filter(Subscription.created_at >= now - timedelta(days=180)).all():
        if sub.created_at:
            key = sub.created_at.strftime("%Y-%m")
            revenue_by_month[key] = revenue_by_month.get(key, 0.0) + float(sub.price or 0)
    chart_revenue = [{"month": m, "amount": round(revenue_by_month.get(m, 0.0), 2)} for m in months]

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
        chart_signups=chart_signups,
        chart_subscriptions=chart_subscriptions,
        chart_revenue=chart_revenue,
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


@bp.post("/bulk-action")
@login_required
def bulk_action():
    """تنفيذ إجراء جماعي على الكيانات المختارة."""
    data = request.get_json(silent=True) or {}
    entity = data.get("entity")
    action = data.get("action")
    ids = [int(i) for i in data.get("ids", []) if str(i).isdigit()]

    if not entity or not action or not ids:
        return {"success": False, "message": _("بيانات غير كافية")}, 400

    allowed = {
        "users": {"activate", "deactivate", "delete"},
        "schools": {"delete"},
    }
    if entity not in allowed or action not in allowed[entity]:
        return {"success": False, "message": _("إجراء غير مسموح")}, 400

    def _apply():
        if entity == "users":
            for user_id in ids:
                user = User.query.get(user_id)
                if not user or user.id == current_user.id:
                    continue
                if action == "activate":
                    user.is_active = True
                elif action == "deactivate":
                    user.is_active = False
                elif action == "delete":
                    user.is_active = False
                    user.deleted_at = datetime.utcnow()

        elif entity == "schools":
            for school_id in ids:
                school = School.query.get(school_id)
                if not school:
                    continue
                if action == "delete":
                    school.is_active = False

    tx(_apply)
    return {"success": True, "message": _("تم تنفيذ الإجراء")}


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


@bp.get("/subscriptions/<int:sub_id>")
@login_required
def subscription_detail(sub_id):
    sub = Subscription.query.options(
        joinedload(Subscription.user),
        joinedload(Subscription.plan),
        joinedload(Subscription.payments).joinedload(ManualPayment.receipts),
    ).get_or_404(sub_id)
    now = datetime.now(UTC)
    steps = [
        {
            "label": _("مُرسل"),
            "date": sub.created_at,
            "actor": sub.user.name_ar if sub.user else "",
            "done": True,
            "active": False,
        }
    ]
    if sub.status in ("pending", "pending_review"):
        steps.append(
            {
                "label": _("بانتظار المراجعة"),
                "date": sub.updated_at,
                "actor": "",
                "done": False,
                "active": True,
            }
        )
    elif sub.status in ("active", "expired", "cancelled"):
        steps.append(
            {
                "label": _("بانتظار المراجعة"),
                "date": sub.updated_at,
                "actor": "",
                "done": True,
                "active": False,
            }
        )
    else:
        steps.append(
            {
                "label": _("بانتظار المراجعة"),
                "date": None,
                "actor": "",
                "done": False,
                "active": False,
            }
        )

    if sub.status == "active":
        steps.append(
            {
                "label": _("مُعتمد / نشط"),
                "date": sub.start_at,
                "actor": _("المشرف"),
                "done": True,
                "active": True,
            }
        )
    elif sub.status in ("expired", "cancelled"):
        steps.append(
            {
                "label": _("مُعتمد / نشط"),
                "date": sub.start_at,
                "actor": _("المشرف"),
                "done": True,
                "active": False,
            }
        )
    else:
        steps.append(
            {
                "label": _("مُعتمد / نشط"),
                "date": None,
                "actor": "",
                "done": False,
                "active": False,
            }
        )

    if sub.status == "expired" or (sub.end_at and sub.end_at < now):
        steps.append(
            {
                "label": _("منتهي الصلاحية"),
                "date": sub.end_at,
                "actor": "",
                "done": True,
                "active": False,
            }
        )
    else:
        steps.append(
            {
                "label": _("منتهي الصلاحية"),
                "date": None,
                "actor": "",
                "done": False,
                "active": False,
            }
        )
    return render_template("admin/subscription_detail.html", sub=sub, timeline_steps=steps)


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
        result = subprocess.run([PG_DUMP, db_url, "-f", filepath], capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            flash(_("تم إنشاء النسخة الاحتياطية بنجاح"), "success")
        else:
            flash(f"فشل النسخ الاحتياطي: {result.stderr}", "danger")
    except FileNotFoundError:
        flash(_("لم يتم العثور على pg_dump — تأكد من تثبيت PostgreSQL"), "danger")
    except Exception as e:
        flash(f"خطأ: {e}", "danger")

    return redirect(url_for("admin.backups_list"))


@bp.post("/backups/<path:filename>/restore")
@login_required
def backup_restore(filename):
    """استعادة نسخة احتياطية — يتطلب تأكيد"""
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
        result = subprocess.run([PSQL, db_url, "-f", filepath], capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            flash(_("تمت الاستعادة بنجاح"), "success")
        else:
            flash(f"فشل الاستعادة: {result.stderr}", "danger")
    except FileNotFoundError:
        flash(_("لم يتم العثور على psql — تأكد من تثبيت PostgreSQL"), "danger")
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

    # بيانات الرسوم البيانية لمشرف المدرسة
    now = datetime.utcnow()
    months = []
    for i in range(5, -1, -1):
        d = now - timedelta(days=i * 30)
        months.append(d.strftime("%Y-%m"))

    class_ids = [c.id for c in ClassRoom.query.filter_by(school_id=school_id).all()]
    students_by_class = (
        db.session.query(ClassRoom.name, func.count(User.id))
        .join(ClassMember, ClassRoom.id == ClassMember.class_id)
        .join(User, ClassMember.user_id == User.id)
        .filter(ClassRoom.school_id == school_id, ClassMember.status == "active", User.role == UserRole.student)
        .group_by(ClassRoom.name)
        .all()
    )
    chart_students_by_class = [{"name": name or _("غير مسماً"), "count": count} for name, count in students_by_class]

    recent_subscriptions = Subscription.query.filter(
        Subscription.class_id.in_(class_ids), Subscription.created_at >= now - timedelta(days=180)
    ).all()
    revenue_by_month: dict[str, float] = {}
    for sub in recent_subscriptions:
        if sub.created_at:
            key = sub.created_at.strftime("%Y-%m")
            revenue_by_month[key] = revenue_by_month.get(key, 0.0) + float(sub.price or 0)
    chart_revenue = [{"month": m, "amount": round(revenue_by_month.get(m, 0.0), 2)} for m in months]

    subs_by_status: dict[str, int] = {
        status: count
        for status, count in db.session.query(Subscription.status, func.count(Subscription.id))
        .filter(Subscription.class_id.in_(class_ids))
        .group_by(Subscription.status)
        .all()
    }
    chart_subscriptions = [
        {"status": status, "count": subs_by_status.get(status, 0)}
        for status in ("active", "pending", "expired", "pending_review")
    ]

    return render_template(
        "admin/school_admin_dashboard.html",
        school_id=school_id,
        class_count=class_count,
        student_count=student_count,
        teacher_count=teacher_count,
        lesson_count=lesson_count,
        assignment_count=assignment_count,
        revenue=revenue,
        chart_students_by_class=chart_students_by_class,
        chart_revenue=chart_revenue,
        chart_subscriptions=chart_subscriptions,
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


# ======================================================================
# تتبع الإيرادات (السوبر أدمن)
# ======================================================================
@bp.get("/revenue")
@login_required
@role_required(UserRole.super_admin)
def revenue_dashboard():
    """لوحة تحكم الإيرادات للسوبر أدمن."""
    days = request.args.get("days", 30, type=int)
    if days not in [7, 30, 90, 365]:
        days = 30

    data = get_revenue_dashboard_data(days=days)
    return render_template("admin/revenue.html", data=data, days=days)


@bp.get("/health")
@login_required
@role_required(UserRole.super_admin)
def system_health():
    from app.services.health import get_recent_checks, get_system_status, run_all_checks

    run_all_checks()
    checks = get_recent_checks(hours=24)
    status = get_system_status()
    return render_template("admin/health.html", checks=checks, status=status)


# ======================================================================
# لوحة التحليلات (السوبر أدمن)
# ======================================================================
@bp.get("/analytics")
@login_required
@role_required(UserRole.super_admin)
def analytics():
    """لوحة التحليلات — DAU، تسجيلات، تفاعل، توظيف."""
    days = request.args.get("days", 30, type=int)
    if days not in [7, 30, 90]:
        days = 30
    from app.services.analytics import get_analytics_data

    data = get_analytics_data(days=days)
    return render_template("admin/analytics.html", data=data, days=days)


@bp.get("/moe-export")
@login_required
@role_required(UserRole.super_admin)
def moe_export():
    schools = School.query.filter_by(is_active=True).order_by(School.name_ar).all()
    return render_template("admin/moe_export.html", schools=schools)


@bp.post("/moe-export")
@login_required
@role_required(UserRole.super_admin)
def moe_export_download():
    import io as _io

    from flask import send_file

    school_id = request.form.get("school_id", type=int)
    academic_year = request.form.get("academic_year", "").strip() or None
    term = request.app.config.get("term") if hasattr(request, "app") else None
    from app.services.export import export_moe_format

    data = export_moe_format(school_id=school_id, academic_year=academic_year, term=term)
    buf = _io.BytesIO(data)
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="moe_export.xlsx",
    )


@bp.get("/certificates")
@login_required
@role_required(UserRole.super_admin)
def certificates_list():
    from app.models.system import CertificateTemplate

    templates = CertificateTemplate.query.order_by(CertificateTemplate.id.desc()).all()
    return render_template("admin/certificates.html", templates=templates)


# ======================================================================
# إدارة رسائل التواصل (السوبر أدمن)
# ======================================================================
@bp.get("/contact")
@login_required
@role_required(UserRole.super_admin)
def contact_inbox():
    """صندوق وارد رسائل التواصل"""
    from app.models.communication import ContactMessage

    messages = ContactMessage.query.order_by(ContactMessage.created_at.desc()).all()
    return render_template("admin/contact_inbox.html", messages=messages)


@bp.post("/contact/<int:message_id>/read")
@login_required
@role_required(UserRole.super_admin)
def contact_mark_read(message_id):
    """تمييز رسالة كمقروءة"""
    from app.models.communication import ContactMessage

    msg = ContactMessage.query.get_or_404(message_id)
    if msg.status == "new":
        msg.status = "read"
        db.session.commit()
    return redirect(url_for("admin.contact_inbox"))


@bp.post("/contact/<int:message_id>/reply")
@login_required
@role_required(UserRole.super_admin)
def contact_reply(message_id):
    """الرد على رسالة تواصل"""
    from app.models.communication import ContactMessage
    from app.services.email import send_contact_reply_email

    msg = ContactMessage.query.get_or_404(message_id)
    reply_text = request.form.get("reply_text", "").strip()
    if not reply_text:
        flash(_("نص الرد مطلوب"), "danger")
        return redirect(url_for("admin.contact_inbox"))

    if send_contact_reply_email(msg, reply_text):
        msg.status = "replied"
        msg.replied_at = db.func.now()
        db.session.commit()
        flash(_("تم إرسال الرد بنجاح"), "success")
    else:
        flash(_("فشل إرسال الرد"), "danger")
    return redirect(url_for("admin.contact_inbox"))


# ======================================================================
# إدارة طلبات سحب أرباح المعلمين (السوبر أدمن)
# ======================================================================
@bp.get("/payouts")
@login_required
@role_required(UserRole.super_admin)
def payouts_queue():
    """قائمة طلبات سحب أرباح المعلمين المعلقة"""
    from app.models.tutoring import TutorPayout

    payouts = (
        TutorPayout.query.filter_by(status="pending")
        .options(selectinload(TutorPayout.tutor))
        .order_by(TutorPayout.created_at.desc())
        .all()
    )
    return render_template("admin/payouts.html", payouts=payouts)


@bp.post("/payouts/<int:payout_id>/<result>")
@login_required
@role_required(UserRole.super_admin)
def review_payout(payout_id, result):
    """اعتماد أو رفض طلب سحب"""
    from app.models.tutoring import TutorCommission, TutorPayout

    payout = TutorPayout.query.get_or_404(payout_id)
    if result == "approve":
        payout.status = "approved"
        payout.reviewed_by = current_user.id
        payout.reviewed_at = db.func.now()
        # Mark corresponding commissions as withdrawn
        commissions = TutorCommission.query.filter_by(tutor_id=payout.tutor_id, status="pending").all()
        for c in commissions:
            c.status = "withdrawn"
        db.session.commit()
        flash(_("تم اعتماد طلب السحب."), "success")
    elif result == "reject":
        payout.status = "rejected"
        payout.reviewed_by = current_user.id
        payout.reviewed_at = db.func.now()
        payout.note = request.form.get("note", "")
        db.session.commit()
        flash(_("تم رفض طلب السحب."), "warning")
    else:
        abort(404)
    return redirect(url_for("admin.payouts_queue"))
