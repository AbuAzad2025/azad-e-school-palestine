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
from app.core.api_tenancy import (
    assert_school_access,
    assert_user_belongs_to_accessible_school,
    classes_query_for_current_user,
    current_user_school_id,
    lesson_access_query_for_current_user,
    schools_query_for_current_user,
    users_query_for_current_user,
)
from app.core.db import db
from app.core.logging import get_logger
from app.core.permissions import role_required
from app.models.billing import Subscription, SubscriptionPlan
from app.models.class_room import ClassMember, ClassRoom
from app.models.content import Lesson
from app.models.school import School
from app.models.tutoring import TutoringSession
from app.models.user import User, UserRole
from flask import request
from flask_babel import _
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

    query = schools_query_for_current_user()
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
    """جلب مدرسة محددة (404 أولاً للغير موجود، ثم 403 للعابر للتينانت)."""
    school = School.query.filter_by(id=school_id, is_active=True).first()
    if not school:
        return api_error(_("المدرسة غير موجودة"), 404, "NOT_FOUND")

    assert_school_access(school_id)

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

    query = lesson_access_query_for_current_user()
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
    lesson = db.session.get(Lesson, lesson_id)
    if not lesson:
        # RLS يخفي درس مدرسة أخرى؛ إن وُجد فعلاً فالرفض 403 لا 404.
        from app.core.rls import get_for_access_check

        if get_for_access_check(Lesson, lesson_id) is not None:
            return api_error(_("غير مصرح بالوصول"), 403, "FORBIDDEN")
        return api_error(_("الدرس غير موجود"), 404, "NOT_FOUND")

    if current_user.role == UserRole.super_admin:
        pass
    elif current_user.role == UserRole.school_admin:
        # Lesson.class_id غير قابل لـ NULL في المخطط — فحص not class_room يكفي
        # لأي حالة شاذة (صف محذوف مثلاً) فترجع 403 (لا فرع ميت لـ class_id=None).
        class_room = ClassRoom.query.filter_by(id=lesson.class_id).first()
        if not class_room or class_room.school_id != current_user_school_id():
            return api_error(_("غير مصرح بالوصول"), 403, "FORBIDDEN")
    else:
        is_member = (
            ClassMember.query.filter_by(class_id=lesson.class_id, user_id=current_user.id, status="active").first()
            is not None
        )
        if not is_member:
            return api_error(_("غير مصرح بالوصول"), 403, "FORBIDDEN")

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
    session = db.session.get(TutoringSession, session_id)
    if not session:
        return api_error(_("الجلسة غير موجودة"), 404, "NOT_FOUND")

    # authorization: must be the student, tutor, or admin
    if current_user.role not in (UserRole.super_admin, UserRole.school_admin):
        if session.student_id != current_user.id and session.tutor_id != current_user.id:
            return api_error(_("غير مصرح بالوصول"), 403, "FORBIDDEN")

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

    query = users_query_for_current_user()
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
        return api_error(_("المستخدم غير موجود"), 404, "NOT_FOUND")

    assert_user_belongs_to_accessible_school(user)

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

    query = classes_query_for_current_user()
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
        return api_error(_("الصف غير موجود"), 404, "NOT_FOUND")

    if current_user.role == UserRole.super_admin:
        pass
    elif current_user.role == UserRole.school_admin:
        if class_room.school_id != current_user_school_id():
            return api_error(_("غير مصرح بالوصول"), 403, "FORBIDDEN")
    else:
        is_member = (
            ClassMember.query.filter_by(class_id=class_id, user_id=current_user.id, status="active").first() is not None
        )
        if not is_member:
            return api_error(_("غير مصرح بالوصول"), 403, "FORBIDDEN")

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
        return api_error(_("يجب إدخال حرفين على الأقل"), 400, "QUERY_TOO_SHORT")

    limit = min(request.args.get("limit", 5, type=int), 20)
    like = f"%{query}%"
    role = current_user.role
    school_id = getattr(current_user, "school_id", None)
    is_admin = role in (UserRole.super_admin, UserRole.school_admin)

    results: dict[str, list[dict[str, Any]]] = {}

    # Schools
    school_q = schools_query_for_current_user()
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
    user_q = users_query_for_current_user()
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
    class_q = classes_query_for_current_user()
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
    # NOTE: explicit ON clause required — Subscription.class_id is nullable and
    # an implicit join(ClassRoom) resolves to a cartesian ON FALSE, matching zero rows.
    sub_q = Subscription.query.join(SubscriptionPlan).join(User).join(ClassRoom, ClassRoom.id == Subscription.class_id)

    if current_user.role == UserRole.super_admin:
        pass
    elif current_user.role == UserRole.student:
        sub_q = sub_q.filter(Subscription.user_id == current_user.id)
    else:
        school_id = current_user_school_id()
        if school_id:
            sub_q = sub_q.filter(ClassRoom.school_id == school_id)
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


@bp.post("/auth/token")
def api_auth_token():
    """إصدار Personal Access Token لتطبيق الجوال (Bearer).
    ---
    tags: [Auth]
    consumes:
      - application/x-www-form-urlencoded
      - application/json
    parameters:
      - name: email
        in: formData
        type: string
        required: true
        description: بريد المستخدم
      - name: password
        in: formData
        type: string
        required: true
        description: كلمة المرور
    responses:
      200:
        description: توكن صالح لـ 30 يوماً
        schema:
          type: object
          properties:
            data:
              type: object
              properties:
                token: {type: string}
                token_type: {type: string, example: Bearer}
                expires_in: {type: integer, example: 2592000}
      401:
        description: بيانات دخول خاطئة
    """
    from app.core.api_auth import make_api_token
    from app.services.auth import authenticate

    if request.is_json:
        body = request.get_json(silent=True) or {}
        email = (body.get("email") or "").strip().lower()
        password = body.get("password") or ""
    else:
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

    if not email or not password:
        return api_error(_("البريد وكلمة المرور مطلوبان"), 400, "VALIDATION_ERROR")

    user, err = authenticate(email, password)
    if user is None:
        return api_error(err or _("بيانات الدخول غير صحيحة"), 401, "UNAUTHORIZED")

    token = make_api_token(user.id)
    logger.info("api_token_issued", user_id=user.id)
    return api_response({"token": token, "token_type": "Bearer", "expires_in": 60 * 60 * 24 * 30})


@bp.errorhandler(404)
def api_404(e):
    return api_error(_("المورد غير موجود"), 404, "NOT_FOUND")


@bp.errorhandler(403)
def api_403(e):
    return api_error(_("غير مصرح بالوصول"), 403, "FORBIDDEN")


@bp.errorhandler(401)
def api_401(e):
    return api_error(_("غير مصادق عليه"), 401, "UNAUTHORIZED")


@bp.errorhandler(429)
def api_429(e):
    return api_error(_("تم تجاوز الحد المسموح"), 429, "RATE_LIMITED")


@bp.errorhandler(500)
def api_500(e):
    return api_error(_("خطأ داخلي في الخادم"), 500, "INTERNAL_ERROR")
