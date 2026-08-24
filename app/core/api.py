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

from app.core.logging import get_correlation_id

API_VERSION = "v1"


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
    """بناء استجابة خطأ API بتنسيق موحّد."""
    body = {
        "error": {
            "code": code or f"ERR_{status}",
            "message": message,
            "details": details or {},
        },
        "meta": {
            "version": API_VERSION,
            "request_id": get_correlation_id(),
        },
    }
    return jsonify(body), status


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
