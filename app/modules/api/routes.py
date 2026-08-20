"""API v1 Routes — نقاط نهاية حقيقية تحت /api/v1/.

تُعرِّض بيانات المدرسة: الدروس، الملف الشخصي، الجلسات التعليمية.
كل الاستعلامات تستخدم scope_by_school للـ tenancy.
"""

from app.core.logging import get_correlation_id, get_logger
from app.core.permissions import role_required
from app.models.class_room import ClassMember, ClassRoom
from app.models.content import Lesson
from app.models.tutoring import TutoringSession
from app.models.user import UserRole
from flask import jsonify, request
from flask_login import current_user, login_required

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
