"""معيار استجابات API الموحّد — تنسيق JSON واحد لكل نقاط النهاية.

التنسيق:
    {
        "data": {...} | [...],
        "meta": {
            "version": "v1",
            "request_id": "abc123",
            ...
        }
    }

الأخطاء:
    {
        "error": {
            "code": "ERR_NOT_FOUND",
            "message": "...",
            "details": {}
        },
        "meta": {...}
    }
"""

from __future__ import annotations

from typing import Any

from flask import jsonify

from app.core.errors import API_VERSION, error_payload
from app.core.logging import get_correlation_id

__all__ = ["API_VERSION", "api_error", "api_paginated", "api_response"]


def api_response(data: Any, status: int = 200, meta: dict[str, Any] | None = None) -> tuple[Any, int]:
    """بناء استجابة API ناجحة بتنسيق موحّد."""
    body = {
        "data": data,
        "meta": {
            "version": API_VERSION,
            "request_id": get_correlation_id(),
            **(meta or {}),
        },
    }
    return jsonify(body), status


def api_error(
    message: str,
    status: int = 400,
    code: str | None = None,
    details: dict[str, Any] | None = None,
) -> tuple[Any, int]:
    """بناء استجابة خطأ API بتنسيق موحّد.

    الشكل يُبنى في ``app/core/errors.error_payload`` — المصدر الوحيد له،
    فيصل المعالج العام هنا على نفس الشكل الذي يُنتجه أي مسار آخر.

    الرمز الافتراضي يبقى ``ERR_{status}`` كما كان: مسارات الـ API تمرّر رموزها
    الصريحة، وعقد الشكل الموحّد قائم عليه اختبار — الجديد هنا هو التنقية ومعرّف
    المتابعة، لا تغيير الرموز.
    """
    return jsonify(error_payload(status, message=message, code=code or f"ERR_{status}", details=details)), status


def api_paginated(
    items: list[dict[str, Any]],
    page: int,
    per_page: int,
    total: int,
    status: int = 200,
) -> tuple[Any, int]:
    """بناء استجابة مُرقّمة موحّدة."""
    pages = (total + per_page - 1) // per_page if per_page > 0 else 0
    return api_response(
        items,
        status=status,
        meta={
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": pages,
        },
    )
