"""سياق مشترك للقوالب — نقطة واحدة تُحقن في كل صفحة (لا تكرار في القوالب)."""

from datetime import datetime

from flask import request, url_for
from flask_babel import get_locale
from flask_login import current_user
from markupsafe import Markup, escape

from app.models.user import UserRole

ICON_NAMES = {
    "menu",
    "x",
    "home",
    "dashboard",
    "school",
    "book",
    "book-open",
    "books",
    "pen",
    "video",
    "chart",
    "bell",
    "folder",
    "play",
    "logout",
    "login",
    "globe",
    "check",
    "alert",
    "moon",
    "sun",
    "clock",
    "calendar",
    "cash",
    "card",
    "star",
    "target",
    "settings",
    "search",
    "file",
    "user",
    "users",
    "teacher",
    "note",
    "quiz",
    "sparkles",
    "refresh",
    "download",
    "upload",
    "plus",
    "trash",
    "lock",
    "eye",
    "link",
    "arrow-left",
    "arrow-right",
    "chevron-down",
    "copy",
    "envelope",
    "shield",
    "attendance",
    "calendar-check",
    "grade",
    "payment",
    "trophy",
    "message-square",
    "help-circle",
    "shield-check",
    "key",
    "unlock",
    "archive",
    "download-cloud",
    "upload-cloud",
}


def icon(name: str, cls: str = "") -> Markup:
    """يُنتج وسم <use> لأيقونة SVG من الرمز sprite (رسم متناسق stroke)."""
    if name not in ICON_NAMES:
        name = "check"
    classes = " ".join(filter(None, ("icon", f"icon-{name}", cls)))
    href = f"{url_for('static', filename='img/icons.svg')}#i-{name}"
    return Markup(
        f'<svg class="{escape(classes)}" aria-hidden="true" focusable="false"><use href="{escape(href)}"></use></svg>'
    )  # nosec B704


def has_role(role: str | UserRole) -> bool:
    """تحقق مما إذا كان المستخدم الحالي يملك الدور المحدد."""
    if not current_user.is_authenticated:
        return False
    if isinstance(role, UserRole):
        return current_user.role == role
    return current_user.role.value == role


def has_any_role(*roles: str | UserRole) -> bool:
    """تحقق مما إذا كان المستخدم يملك أياً من الأدوار المحددة."""
    if not current_user.is_authenticated:
        return False
    user_role_val = current_user.role.value
    for role in roles:
        if isinstance(role, UserRole):
            if user_role_val == role.value:
                return True
        elif user_role_val == role:
            return True
    return False


def is_super_admin() -> bool:
    """تحقق من كون المستخدم سوبر أدمن."""
    return current_user.is_authenticated and current_user.role == UserRole.super_admin


def is_school_admin() -> bool:
    """تحقق من كون المستخدم مشرف مدرسة."""
    return current_user.is_authenticated and current_user.role == UserRole.school_admin


def is_teacher() -> bool:
    """تحقق من كون المستخدم معلماً."""
    return current_user.is_authenticated and current_user.role == UserRole.teacher


def is_student() -> bool:
    """تحقق من كون المستخدم طالباً."""
    return current_user.is_authenticated and current_user.role == UserRole.student


def is_parent() -> bool:
    """تحقق من كون المستخدم ولي أمر."""
    return current_user.is_authenticated and current_user.role == UserRole.parent


def can_access_admin() -> bool:
    """تحقق من صلاحية الوصول للوحة الإدارة."""
    return current_user.is_authenticated and current_user.role in (UserRole.super_admin, UserRole.school_admin)


def can_manage_schools() -> bool:
    """تحقق من صلاحية إدارة المدارس."""
    return current_user.is_authenticated and current_user.role == UserRole.super_admin


def can_teach_class(class_room) -> bool:
    """تحقق من صلاحية تدريس صف (معلّم الصف أو مشرف مدرسته أو سوبر أدمن)."""
    if not current_user.is_authenticated:
        return False
    if current_user.role == UserRole.super_admin:
        return True
    if current_user.role == UserRole.school_admin:
        from app.core.tenancy import current_school_id

        return current_school_id() == class_room.school_id
    return class_room.teacher_id == current_user.id


def can_view_class(class_room) -> bool:
    """تحقق من صلاحية عرض صف (أعضاء + معلم/مشرف مدرسته + سوبر أدمن)."""
    if not current_user.is_authenticated:
        return False
    if current_user.role == UserRole.super_admin:
        return True
    from app.core.tenancy import current_school_id

    if current_school_id() == class_room.school_id and current_user.role in (UserRole.school_admin, UserRole.teacher):
        return True
    from app.services.schools import is_member

    return is_member(class_room, current_user)


def register(app):
    app.jinja_env.globals["icon"] = icon
    app.jinja_env.globals["has_role"] = has_role
    app.jinja_env.globals["has_any_role"] = has_any_role
    app.jinja_env.globals["is_super_admin"] = is_super_admin
    app.jinja_env.globals["is_school_admin"] = is_school_admin
    app.jinja_env.globals["is_teacher"] = is_teacher
    app.jinja_env.globals["is_student"] = is_student
    app.jinja_env.globals["is_parent"] = is_parent
    app.jinja_env.globals["can_access_admin"] = can_access_admin
    app.jinja_env.globals["can_manage_schools"] = can_manage_schools
    app.jinja_env.globals["can_teach_class"] = can_teach_class
    app.jinja_env.globals["can_view_class"] = can_view_class

    @app.context_processor
    def inject_app_context():
        unread = 0
        msg_unread = 0
        impersonator = None
        if current_user.is_authenticated:
            from app.services.communication import unread_count

            unread = unread_count(current_user.id)
            from app.services.messages import unread_count as msg_unread_count

            msg_unread = msg_unread_count(current_user.id)
            from app.services.impersonation import impersonator_user

            impersonator = impersonator_user()
        return {
            "now": datetime.now(),
            "app_name": "مدرسة أزاد الإلكترونية",
            "is_admin": current_user.is_authenticated
            and current_user.role in (UserRole.super_admin, UserRole.school_admin),
            "is_impersonating": impersonator is not None,
            "impersonator": impersonator,
            "current_user": current_user,
            "current_locale": str(get_locale()),
            "current_path": request.path,
            "unread_count": unread,
            "message_unread_count": msg_unread,
        }
