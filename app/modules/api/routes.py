"""API v1 Routes — نقاط نهاية موجهة حسب الموارد (Resource-oriented).

كل مورد يتبع النمط:
    GET    /api/v1/<resource>       → list (paginated)
    GET    /api/v1/<resource>/<id>  → get one
    POST   /api/v1/<resource>       → create
    PATCH  /api/v1/<resource>/<id>  → update
    DELETE /api/v1/<resource>/<id>  → delete (soft)
"""

from __future__ import annotations

from typing import Any

from app.core.api import api_error, api_paginated, api_response
from app.core.api_auth import api_auth_required
from app.core.logging import get_logger
from app.core.permissions import role_required
from app.models.billing import Subscription, SubscriptionPlan
from app.models.class_room import ClassMember, ClassRoom
from app.models.content import Lesson
from app.models.school import School
from app.models.tutoring import TutoringSession
from app.models.user import User, UserRole, UserRoleLink
from flask import request
from flask_login import current_user
from sqlalchemy import or_

from . import bp

logger = get_logger(__name__)


def _parse_pagination() -> tuple[int, int]:
    """استخراج page و per_page من query parameters مع validation."""
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)
    return max(page, 1), max(per_page, 1)


# ═══════════════════════════════════════════════════════════════════════════
# Auth / User
# ═══════════════════════════════════════════════════════════════════════════


@bp.get("/me")
@api_auth_required
def api_me():
    """الملف الشخصي للمستخدم الحالي."""
    log = logger.bind(user_id=current_user.id)
    log.info("api_me_called")
    user = current_user
    return api_response(
        {
            "id": user.id,
            "email": user.email,
            "name_ar": user.name_ar,
            "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        }
    )


# ═══════════════════════════════════════════════════════════════════════════
# Schools
# ═══════════════════════════════════════════════════════════════════════════


@bp.get("/schools")
@api_auth_required
def api_schools_list():
    """قائمة المدارس المتاحة للمستخدم."""
    page, per_page = _parse_pagination()
    role = current_user.role
    school_id = getattr(current_user, "school_id", None)

    query = School.query.filter(School.is_active.is_(True))
    if role != UserRole.super_admin and school_id:
        query = query.filter(School.id == school_id)

    total = query.count()
    items = query.limit(per_page).offset((page - 1) * per_page).all()

    data = [
        {
            "id": s.id,
            "name_ar": s.name_ar,
            "domain": s.domain,
            "display_name": s.display_name,
            "is_active": s.is_active,
        }
        for s in items
    ]
    return api_paginated(data, page=page, per_page=per_page, total=total)


@bp.get("/schools/<int:school_id>")
@api_auth_required
def api_schools_get(school_id: int):
    """جلب مدرسة محددة."""
    school = School.query.filter_by(id=school_id, is_active=True).first()
    if not school:
        return api_error("المدرسة غير موجودة", 404, "NOT_FOUND")

    # tenancy check
    user_school_id = getattr(current_user, "school_id", None)
    if current_user.role != UserRole.super_admin and user_school_id != school_id:
        return api_error("غير مصرح بالوصول", 403, "FORBIDDEN")

    return api_response(
        {
            "id": school.id,
            "name_ar": school.name_ar,
            "domain": school.domain,
            "display_name": school.display_name,
            "is_active": school.is_active,
        }
    )


# ═══════════════════════════════════════════════════════════════════════════
# Lessons (Content)
# ═══════════════════════════════════════════════════════════════════════════


@bp.get("/lessons")
@api_auth_required
@role_required(UserRole.super_admin, UserRole.school_admin, UserRole.teacher, UserRole.student, UserRole.parent)
def api_lessons_list():
    """قائمة الدروس المتاحة للمستخدم."""
    log = logger.bind(user_id=current_user.id)
    log.info("api_lessons_called")

    page, per_page = _parse_pagination()

    query = Lesson.query
    if hasattr(current_user, "school_id") and current_user.school_id:
        if current_user.role not in (UserRole.super_admin, UserRole.school_admin):
            joined_class_ids = (
                ClassRoom.query.join(ClassMember, ClassMember.class_room_id == ClassRoom.id)
                .filter(ClassMember.user_id == current_user.id)
                .with_entities(ClassRoom.id)
                .all()
            )
            class_ids = [c.id for c in joined_class_ids]
            query = query.filter(Lesson.class_id.in_(class_ids)) if class_ids else query.filter(Lesson.id == -1)

    query = query.order_by(Lesson.created_at.desc())
    total = query.count()
    items = query.limit(per_page).offset((page - 1) * per_page).all()

    data = [
        {
            "id": lesson.id,
            "title": lesson.title,
            "class_id": lesson.class_id,
            "sort_order": lesson.sort_order,
            "is_offline_available": getattr(lesson, "is_offline_available", False),
            "created_at": lesson.created_at.isoformat() if lesson.created_at else None,
        }
        for lesson in items
    ]
    return api_paginated(data, page=page, per_page=per_page, total=total)


@bp.get("/lessons/<int:lesson_id>")
@api_auth_required
def api_lessons_get(lesson_id: int):
    """جلب درس محدد."""
    lesson = Lesson.query.get(lesson_id)
    if not lesson:
        return api_error("الدرس غير موجود", 404, "NOT_FOUND")

    # authorization: must be a member of the class or admin
    if current_user.role not in (UserRole.super_admin, UserRole.school_admin):
        is_member = (
            ClassMember.query.filter_by(class_id=lesson.class_id, user_id=current_user.id, status="active").first()
            is not None
        )
        if not is_member:
            return api_error("غير مصرح بالوصول", 403, "FORBIDDEN")

    return api_response(
        {
            "id": lesson.id,
            "title": lesson.title,
            "class_id": lesson.class_id,
            "sort_order": lesson.sort_order,
            "is_offline_available": getattr(lesson, "is_offline_available", False),
            "created_at": lesson.created_at.isoformat() if lesson.created_at else None,
        }
    )


# ═══════════════════════════════════════════════════════════════════════════
# Tutoring Sessions
# ═══════════════════════════════════════════════════════════════════════════


@bp.get("/tutoring/sessions")
@api_auth_required
@role_required(UserRole.super_admin, UserRole.school_admin, UserRole.teacher, UserRole.student)
def api_tutoring_sessions_list():
    """الجلسات التعليمية للمستخدم."""
    log = logger.bind(user_id=current_user.id)
    log.info("api_tutoring_sessions_called")

    page, per_page = _parse_pagination()

    query = TutoringSession.query
    if current_user.role == UserRole.student:
        query = query.filter_by(student_id=current_user.id)
    elif current_user.role == UserRole.teacher:
        query = query.filter_by(tutor_id=current_user.id)

    total = query.count()
    items = query.order_by(TutoringSession.created_at.desc()).limit(per_page).offset((page - 1) * per_page).all()

    data = [
        {
            "id": s.id,
            "student_id": s.student_id,
            "tutor_id": s.tutor_id,
            "subject": s.subject,
            "status": s.status,
            "price": float(s.price) if s.price else None,
            "currency": s.currency,
            "scheduled_at": s.scheduled_at.isoformat() if s.scheduled_at else None,
            "duration_min": s.duration_min,
        }
        for s in items
    ]
    return api_paginated(data, page=page, per_page=per_page, total=total)


@bp.get("/tutoring/sessions/<int:session_id>")
@api_auth_required
def api_tutoring_sessions_get(session_id: int):
    """جلب جلسة تعليمية محددة."""
    session = TutoringSession.query.get(session_id)
    if not session:
        return api_error("الجلسة غير موجودة", 404, "NOT_FOUND")

    # authorization: must be the student, tutor, or admin
    if current_user.role not in (UserRole.super_admin, UserRole.school_admin):
        if session.student_id != current_user.id and session.tutor_id != current_user.id:
            return api_error("غير مصرح بالوصول", 403, "FORBIDDEN")

    return api_response(
        {
            "id": session.id,
            "student_id": session.student_id,
            "tutor_id": session.tutor_id,
            "subject": session.subject,
            "status": session.status,
            "price": float(session.price) if session.price else None,
            "currency": session.currency,
            "scheduled_at": session.scheduled_at.isoformat() if session.scheduled_at else None,
            "duration_min": session.duration_min,
        }
    )


# ═══════════════════════════════════════════════════════════════════════════
# Users
# ═══════════════════════════════════════════════════════════════════════════


@bp.get("/users")
@api_auth_required
@role_required(UserRole.super_admin, UserRole.school_admin)
def api_users_list():
    """قائمة المستخدمين (للمشرفين فقط)."""
    page, per_page = _parse_pagination()
    role = current_user.role
    school_id = getattr(current_user, "school_id", None)

    query = User.query.filter(User.is_active.is_(True))
    if role != UserRole.super_admin and school_id:
        user_ids_in_school = (
            UserRoleLink.query.filter(UserRoleLink.school_id == school_id, UserRoleLink.is_active.is_(True))
            .with_entities(UserRoleLink.user_id)
            .subquery()
        )
        query = query.filter(User.id.in_(user_ids_in_school))

    total = query.count()
    items = query.limit(per_page).offset((page - 1) * per_page).all()

    data = [
        {
            "id": u.id,
            "name_ar": u.name_ar,
            "email": u.email,
            "role": u.role.value if hasattr(u.role, "value") else str(u.role),
        }
        for u in items
    ]
    return api_paginated(data, page=page, per_page=per_page, total=total)


@bp.get("/users/<int:user_id>")
@api_auth_required
def api_users_get(user_id: int):
    """جلب مستخدم محدد."""
    user = User.query.filter_by(id=user_id, is_active=True).first()
    if not user:
        return api_error("المستخدم غير موجود", 404, "NOT_FOUND")

    # tenancy check: same school or admin
    if current_user.role != UserRole.super_admin:
        current_school_ids = {link.school_id for link in current_user.role_links if link.is_active}
        user_school_ids = {link.school_id for link in user.role_links if link.is_active}
        if not (current_school_ids & user_school_ids):
            return api_error("غير مصرح بالوصول", 403, "FORBIDDEN")

    return api_response(
        {
            "id": user.id,
            "name_ar": user.name_ar,
            "email": user.email,
            "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        }
    )


# ═══════════════════════════════════════════════════════════════════════════
# Classes
# ═══════════════════════════════════════════════════════════════════════════


@bp.get("/classes")
@api_auth_required
def api_classes_list():
    """قائمة الصفوف المتاحة للمستخدم."""
    page, per_page = _parse_pagination()
    role = current_user.role
    school_id = getattr(current_user, "school_id", None)

    query = ClassRoom.query.filter(ClassRoom.is_active.is_(True))
    if role == UserRole.super_admin:
        pass
    elif school_id:
        query = query.filter(ClassRoom.school_id == school_id)
    else:
        member_class_ids = (
            ClassMember.query.filter(ClassMember.user_id == current_user.id, ClassMember.status == "active")
            .with_entities(ClassMember.class_id)
            .subquery()
        )
        query = query.filter(ClassRoom.id.in_(member_class_ids))

    total = query.count()
    items = query.limit(per_page).offset((page - 1) * per_page).all()

    data = [
        {
            "id": c.id,
            "name": c.name,
            "school_id": c.school_id,
            "subject_id": getattr(c, "subject_id", None),
            "grade_id": getattr(c, "grade_id", None),
        }
        for c in items
    ]
    return api_paginated(data, page=page, per_page=per_page, total=total)


@bp.get("/classes/<int:class_id>")
@api_auth_required
def api_classes_get(class_id: int):
    """جلب صف محدد."""
    class_room = ClassRoom.query.filter_by(id=class_id, is_active=True).first()
    if not class_room:
        return api_error("الصف غير موجود", 404, "NOT_FOUND")

    # authorization: school admin, member, or super admin
    if current_user.role not in (UserRole.super_admin, UserRole.school_admin):
        is_member = (
            ClassMember.query.filter_by(class_id=class_id, user_id=current_user.id, status="active").first() is not None
        )
        if not is_member:
            return api_error("غير مصرح بالوصول", 403, "FORBIDDEN")

    return api_response(
        {
            "id": class_room.id,
            "name": class_room.name,
            "school_id": class_room.school_id,
            "subject_id": getattr(class_room, "subject_id", None),
            "grade_id": getattr(class_room, "grade_id", None),
        }
    )


# ═══════════════════════════════════════════════════════════════════════════
# Global Search
# ═══════════════════════════════════════════════════════════════════════════


@bp.get("/search")
@api_auth_required
def api_search():
    """بحث عالمي عبر الكيانات الرئيسية."""
    query = (request.args.get("q") or "").strip()
    if not query or len(query) < 2:
        return api_error("يجب إدخال حرفين على الأقل", 400, "QUERY_TOO_SHORT")

    limit = min(request.args.get("limit", 5, type=int), 20)
    like = f"%{query}%"
    role = current_user.role
    school_id = getattr(current_user, "school_id", None)
    is_admin = role in (UserRole.super_admin, UserRole.school_admin)

    results: dict[str, list[dict[str, Any]]] = {}

    # Schools
    school_q = School.query.filter(School.is_active.is_(True))
    if role != UserRole.super_admin:
        if school_id:
            school_q = school_q.filter(School.id == school_id)
        else:
            school_q = school_q.filter(False)
    schools = school_q.filter(or_(School.name_ar.ilike(like), School.domain.ilike(like))).limit(limit).all()
    results["schools"] = [
        {
            "id": s.id,
            "title": s.display_name,
            "subtitle": s.domain or "",
            "url": f"/admin/schools/{s.id}" if role == UserRole.super_admin else f"/schools/{s.id}",
            "icon": "school",
        }
        for s in schools
    ]

    # Users
    user_q = User.query.filter(User.is_active.is_(True))
    if role == UserRole.super_admin:
        pass
    elif school_id:
        user_ids_in_school = (
            UserRoleLink.query.filter(UserRoleLink.school_id == school_id, UserRoleLink.is_active.is_(True))
            .with_entities(UserRoleLink.user_id)
            .subquery()
        )
        user_q = user_q.filter(User.id.in_(user_ids_in_school))
    elif role in (UserRole.student, UserRole.parent, UserRole.teacher):
        class_ids = (
            ClassMember.query.filter(ClassMember.user_id == current_user.id, ClassMember.status == "active")
            .with_entities(ClassMember.class_id)
            .subquery()
        )
        member_user_ids = (
            ClassMember.query.filter(ClassMember.class_id.in_(class_ids), ClassMember.status == "active")
            .with_entities(ClassMember.user_id)
            .subquery()
        )
        user_q = user_q.filter(User.id.in_(member_user_ids))
    else:
        user_q = user_q.filter(False)

    users = user_q.filter(or_(User.name_ar.ilike(like), User.email.ilike(like))).limit(limit).all()
    results["users"] = [
        {
            "id": u.id,
            "title": u.name_ar or u.email,
            "subtitle": u.email,
            "url": f"/admin/users/{u.id}" if is_admin else f"/users/{u.id}",
            "icon": "user",
        }
        for u in users
    ]

    # Classes
    class_q = ClassRoom.query.filter(ClassRoom.is_active.is_(True))
    if role == UserRole.super_admin:
        pass
    elif school_id:
        class_q = class_q.filter(ClassRoom.school_id == school_id)
    else:
        member_class_ids = (
            ClassMember.query.filter(ClassMember.user_id == current_user.id, ClassMember.status == "active")
            .with_entities(ClassMember.class_id)
            .subquery()
        )
        class_q = class_q.filter(ClassRoom.id.in_(member_class_ids))

    classes = class_q.filter(or_(ClassRoom.name.ilike(like), ClassRoom.join_code.ilike(like))).limit(limit).all()
    results["classes"] = [
        {
            "id": c.id,
            "title": c.name or (c.subject.name_ar if hasattr(c, "subject") else ""),
            "subtitle": "",
            "url": f"/schools/classes/{c.id}",
            "icon": "book-open",
        }
        for c in classes
    ]

    # Subscriptions
    sub_q = Subscription.query.join(SubscriptionPlan).join(User).join(ClassRoom)
    if role == UserRole.super_admin:
        pass
    elif school_id:
        sub_q = sub_q.filter(ClassRoom.school_id == school_id)
    elif role == UserRole.student:
        sub_q = sub_q.filter(Subscription.user_id == current_user.id)
    else:
        sub_q = sub_q.filter(False)

    subscriptions = (
        sub_q.filter(
            or_(
                SubscriptionPlan.name.ilike(like),
                User.name_ar.ilike(like),
                User.email.ilike(like),
                ClassRoom.name.ilike(like),
            )
        )
        .limit(limit)
        .all()
    )
    results["subscriptions"] = [
        {
            "id": sub.id,
            "title": f"{sub.plan.name} — {sub.user.name_ar or sub.user.email}",
            "subtitle": f"{sub.status} — {sub.price} {sub.currency}",
            "url": f"/admin/subscriptions/{sub.id}" if is_admin else f"/billing/subscriptions/{sub.id}",
            "icon": "credit-card",
        }
        for sub in subscriptions
    ]

    return api_response(results)


# ═══════════════════════════════════════════════════════════════════════════
# Error handlers
# ═══════════════════════════════════════════════════════════════════════════


@bp.errorhandler(404)
def api_404(e):
    return api_error("المورد غير موجود", 404, "NOT_FOUND")


@bp.errorhandler(403)
def api_403(e):
    return api_error("غير مصرح بالوصول", 403, "FORBIDDEN")


@bp.errorhandler(401)
def api_401(e):
    return api_error("غير مصادق عليه", 401, "UNAUTHORIZED")


@bp.errorhandler(429)
def api_429(e):
    return api_error("تم تجاوز الحد المسموح", 429, "RATE_LIMITED")


@bp.errorhandler(500)
def api_500(e):
    return api_error("خطأ داخلي في الخادم", 500, "INTERNAL_ERROR")
