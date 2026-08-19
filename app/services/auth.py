"""خدمات المصادقة — منطق موحّد مُعاد الاستخدام من الويب والـ API"""

from flask import current_app
from flask_babel import _
from flask_login import current_user

from app.core.db import tx
from app.core.security import check_password_reuse, hash_password, validate_password_policy, verify_password
from app.core.tokens import make_reset_token, read_reset_token
from app.extensions import db
from app.models.school import School
from app.models.user import User, UserApprovalStatus, UserRole, UserRoleLink

from .communication import notify
from .school_approvals import get_school_admins


def register_user(
    email: str,
    name_ar: str,
    role: str,
    password: str,
    school_join_code: str | None = None,
) -> tuple[User | None, str | None]:
    """ينشئ حساباً بذرّية كاملة بحالة pending. يعيد (user, error)."""
    email = email.strip().lower()
    if User.query.filter_by(email=email).first():
        return None, "هذا البريد مسجّل مسبقاً."
    if role not in {r.value for r in UserRole}:
        return None, "دور غير صالح."

    # التحقق من سياسة كلمة المرور
    ok, msg = validate_password_policy(password)
    if not ok:
        return None, msg

    # التحقق من كود الانضمام للمدرسة (للمعلمين والطلاب وأولياء الأمور)
    school_id = None
    if school_join_code and role in {"teacher", "student", "parent"}:
        school = School.query.filter_by(join_code=school_join_code.strip().upper()).first()
        if not school:
            return None, "كود الانضمام للمدرسة غير صحيح."
        school_id = school.id

    def _create():
        user = User(
            email=email,
            name_ar=name_ar.strip(),
            role=UserRole(role),
            password_hash=hash_password(password),
            is_verified=False,
            approval_status=UserApprovalStatus.pending,
        )
        # إضافة الهاش للتاريخ
        user.add_password_to_history(user.password_hash)
        db.session.add(user)
        db.session.flush()

        # إنشاء رابط الدور للمدرسة
        if school_id:
            rl = UserRoleLink(user_id=user.id, school_id=school_id, role=UserRole(role))
            db.session.add(rl)

        # إشعار مشرفي المدرسة
        if school_id:
            admins = get_school_admins(school_id)
            for admin_link in admins:
                notify(
                    admin_link.user_id,
                    "registration",
                    _("طلب انضمام جديد"),
                    _("طلب مستخدم جديد ({}) الانضمام لمدرستك.").format(role),
                )

        return user

    return tx(_create), None


def authenticate(email: str, password: str) -> tuple[User | None, str | None]:
    """يعيد (user, error). النجاح: error None."""
    user = User.query.filter_by(email=email.strip().lower()).first()
    if not user:
        return None, "بريد أو كلمة مرور غير صحيحة."

    # التحقق من القفل
    if user.is_locked():
        return None, "الحساب مقفل مؤقتاً بسبب محاولات فاشلة متكررة. حاول لاحقاً."

    if not verify_password(user.password_hash, password):
        user.increment_failed_login(
            max_attempts=current_app.config.get("LOGIN_MAX_ATTEMPTS", 5),
            lockout_minutes=current_app.config.get("LOGIN_LOCKOUT_DURATION", 900) // 60,
        )
        db.session.commit()
        return None, "بريد أو كلمة مرور غير صحيحة."

    if not user.is_active:
        return None, "حسابك معطّل. تواصل مع الإدارة."

    # التحقق من موافقة السوبر أدمن (بدلاً من تفعيل البريد)
    if not user.is_approved:
        return None, "حسابك في انتظار موافقة الإدارة. سيتم إشعارك عند القبول."

    # نجاح: إعادة تعيين المحاولات الفاشلة
    user.reset_failed_login()
    return user, None


def mark_login(user: User) -> None:
    def _mark():
        user.last_login_at = db.func.now()
        user.reset_failed_login()

    tx(_mark)


def confirm_email(uid: int, email: str) -> bool:
    """يُفعّل البريد عند تطابق الرمز. يعيد نجاح/فشل (للـ API والويب معاً)."""
    user = db.session.get(User, uid)
    if not user or user.email != email:
        return False

    def _confirm():
        user.is_verified = True

    tx(_confirm)
    return True


def is_current(user: User) -> bool:
    return current_user.is_authenticated and current_user.id == user.id


def request_password_reset(email: str) -> str | None:
    """ينشئ رمز إعادة تعيين للمستخدم إن وُجد. يعيد الرمز أو None (لتجنب كشف وجود البريد)."""
    user = User.query.filter_by(email=email.strip().lower()).first()
    if not user:
        return None
    return make_reset_token(user.id, user.email)


def reset_password(token: str, new_password: str) -> str | None:
    """يغيّر كلمة المرور عبر رمز صالح. يعيد رسالة خطأ أو None عند النجاح."""
    uid, email = read_reset_token(token)
    if not uid or not email:
        return "رابط إعادة التعيين غير صالح أو منتهي."
    user = db.session.get(User, uid)
    if not user or user.email != email or not user.is_active:
        return "رابط إعادة التعيين غير صالح أو منتهي."

    # التحقق من سياسة كلمة المرور
    ok, msg = validate_password_policy(new_password)
    if not ok:
        return msg

    # التحقق من إعادة الاستخدام
    new_hash = hash_password(new_password)
    ok, msg = check_password_reuse(user, new_hash)
    if not ok:
        return msg

    def _reset():
        user.password_hash = new_hash
        user.add_password_to_history(new_hash)
        user.reset_failed_login()

    tx(_reset)
    return None
