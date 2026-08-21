"""API v1 Routes — نقاط نهاية حقيقية تحت /api/v1/.

تُعرِّض بيانات المدرسة: الدروس، الملف الشخصي، الجلسات التعليمية.
كل الاستعلامات تستخدم scope_by_school للـ tenancy.
"""

from app.core.logging import get_correlation_id, get_logger
from app.core.permissions import role_required
from app.models.billing import Subscription, SubscriptionPlan
from app.models.class_room import ClassMember, ClassRoom
from app.models.content import Lesson
from app.models.school import School
from app.models.tutoring import TutoringSession
from app.models.user import User, UserRole, UserRoleLink
from flask import jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import or_

from . import bp

logger = get_logger(__name__)


def api_response(data, status: int = 200, meta: dict | None = None):
    """oluştur一份 ApiResponse بتنسيق موحّد.

    {"data": ..., "meta": {"version": "v1", "request_id": "..."}}
    """
    body = {
        "data": data,
        "meta": {
            "version": "v1",
            "request_id": get_correlation_id(),
            **(meta or {}),
        },
    }
    return jsonify(body), status


def api_error(message: str, status: int = 400, code: str | None = None):
    """خطأ بتنسيق موحّد لـ API."""
    body = {
        "error": {
            "message": message,
            "code": code or f"ERR_{status}",
        },
        "meta": {
            "version": "v1",
            "request_id": get_correlation_id(),
        },
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------


@bp.get("/me")
@login_required
def api_me():
    """الملف الشخصي للمستخدم الحالي.
    ---
    tags: [Auth]
    security:
      - Bearer: []
    responses:
      200:
        description: بيانات المستخدم
        schema:
          type: object
          properties:
            data:
              $ref: '#/definitions/User'
            meta:
              type: object
        401:
          description: غير مصادق عليه
          schema:
            $ref: '#/definitions/Error'
    """
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


# ---------------------------------------------------------------------------
# Content endpoints
# ---------------------------------------------------------------------------


@bp.get("/lessons")
@login_required
@role_required(UserRole.super_admin, UserRole.school_admin, UserRole.teacher, UserRole.student, UserRole.parent)
def api_lessons():
    """قائمة الدروس المتاحة للمستخدم.
    ---
    tags: [Content]
    security:
      - Bearer: []
    parameters:
      - name: page
        in: query
        type: integer
        default: 1
      - name: per_page
        in: query
        type: integer
        default: 20
        maximum: 100
    responses:
      200:
        description: قائمة الدروس مع تفاصيل الصفحة
        schema:
          type: object
          properties:
            data:
              type: array
              items:
                $ref: '#/definitions/Lesson'
            meta:
              $ref: '#/definitions/PaginatedMeta'
    """
    log = logger.bind(user_id=current_user.id)
    log.info("api_lessons_called")

    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)

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
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    lessons = [
        {
            "id": lesson.id,
            "title": lesson.title,
            "class_id": lesson.class_id,
            "sort_order": lesson.sort_order,
            "is_offline_available": getattr(lesson, "is_offline_available", False),
            "created_at": lesson.created_at.isoformat() if lesson.created_at else None,
        }
        for lesson in pagination.items
    ]

    return api_response(
        lessons,
        meta={
            "page": page,
            "per_page": per_page,
            "total": pagination.total,
            "pages": pagination.pages,
        },
    )


# ---------------------------------------------------------------------------
# Tutoring endpoints
# ---------------------------------------------------------------------------


@bp.get("/tutoring/sessions")
@login_required
@role_required(UserRole.super_admin, UserRole.school_admin, UserRole.teacher, UserRole.student)
def api_tutoring_sessions():
    """الجلسات التعليمية للمستخدم.
    ---
    tags: [Tutoring]
    security:
      - Bearer: []
    responses:
      200:
        description: آخر 50 جلسة تعليمية
        schema:
          type: object
          properties:
            data:
              type: array
              items:
                $ref: '#/definitions/TutoringSession'
            meta:
              type: object
    """
    log = logger.bind(user_id=current_user.id)
    log.info("api_tutoring_sessions_called")

    query = TutoringSession.query
    if current_user.role == UserRole.student:
        query = query.filter_by(student_id=current_user.id)
    elif current_user.role == UserRole.teacher:
        query = query.filter_by(tutor_id=current_user.id)

    sessions = query.order_by(TutoringSession.created_at.desc()).limit(50).all()

    return api_response(
        [
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
            for s in sessions
        ]
    )


# ---------------------------------------------------------------------------
# Error handlers for API blueprint
# ---------------------------------------------------------------------------


@bp.get("/search")
@login_required
def api_search():
    """بحث عالمي عبر الكيانات الرئيسية للـ ERP.

    parameters:
      - name: q
        in: query
        type: string
        required: true
      - name: limit
        in: query
        type: integer
        default: 5
    responses:
      200:
        description: نتائج مجمعة حسب نوع الكيان
    """
    query = (request.args.get("q") or "").strip()
    if not query or len(query) < 2:
        return api_error("يجب إدخال حرفين على الأقل", 400, "QUERY_TOO_SHORT")

    limit = min(request.args.get("limit", 5, type=int), 20)
    like = f"%{query}%"
    role = current_user.role
    school_id = getattr(current_user, "school_id", None)

    results = {}

    # Schools
    school_q = School.query.filter(School.is_active == True)  # noqa: E712
    if role != UserRole.super_admin:
        if school_id:
            school_q = school_q.filter(School.id == school_id)
        else:
            school_q = school_q.filter(False)  # empty
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
    user_q = User.query.filter(User.is_active == True)  # noqa: E712
    if role == UserRole.super_admin:
        pass
    elif school_id:
        user_ids_in_school = (
            UserRoleLink.query.filter(UserRoleLink.school_id == school_id, UserRoleLink.is_active == True)  # noqa: E712
            .with_entities(UserRoleLink.user_id)
            .subquery()
        )
        user_q = user_q.filter(User.id.in_(user_ids_in_school))
    elif role in (UserRole.student, UserRole.parent, UserRole.teacher):
        # Classmates / teachers in shared classes
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

    is_admin = role in (UserRole.super_admin, UserRole.school_admin)
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
    class_q = ClassRoom.query.filter(ClassRoom.is_active == True)  # noqa: E712
    if role == UserRole.super_admin:
        pass
    elif school_id:
        class_q = class_q.filter(ClassRoom.school_id == school_id)
    else:
        # students / teachers / parents: only classes they belong to
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
            "title": c.name or c.subject.name_ar,
            "subtitle": f"{c.grade.name_ar or c.grade.grade_level} — {c.subject.name_ar}",
            "url": f"/schools/classes/{c.id}",
            "icon": "book-open",
        }
        for c in classes
    ]

    # Subscriptions (invoices)
    sub_q = Subscription.query.join(SubscriptionPlan).join(User).join(ClassRoom)
    if role == UserRole.super_admin:
        pass
    elif school_id:
        sub_q = sub_q.filter(ClassRoom.school_id == school_id)
    elif role == UserRole.student:
        sub_q = sub_q.filter(Subscription.user_id == current_user.id)
    elif role == UserRole.parent:
        # parent's children subscriptions would need family links; keep empty for now
        sub_q = sub_q.filter(False)
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
