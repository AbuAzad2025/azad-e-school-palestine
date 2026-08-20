"""Structured logging with correlation IDs (structlog)."""

import logging
import sys
import uuid
from collections.abc import Callable, MutableMapping
from contextvars import ContextVar
from typing import Any

import structlog

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> str:
    """الحصول على معرف الارتباط الحالي أو إنشاء واحد جديد."""
    cid = _correlation_id.get()
    if cid is None:
        cid = uuid.uuid4().hex[:16]
        _correlation_id.set(cid)
    return cid


def set_correlation_id(cid: str) -> None:
    """تعيين معرف الارتباط يدوياً."""
    _correlation_id.set(cid)


def clear_correlation_id() -> None:
    """مسح معرف الارتباط."""
    _correlation_id.set(None)


def correlation_id_middleware(app):
    """Middleware لإضافة correlation ID لكل request."""

    @app.before_request
    def _inject_correlation_id():
        # استخدام header موجود أو إنشاء جديد
        from flask import g, request

        cid = request.headers.get("X-Request-ID") or request.headers.get("X-Correlation-ID") or uuid.uuid4().hex[:16]
        set_correlation_id(cid)
        g.correlation_id = cid
        # إضافة للـ response headers
        request.correlation_id = cid  # type: ignore[attr-defined]

    @app.after_request
    def _add_correlation_header(response):
        from flask import g

        cid = getattr(g, "correlation_id", None)
        if cid:
            response.headers["X-Request-ID"] = cid
        return response


def configure_structlog(app) -> None:
    """تهيئة structlog مع إعدادات التطبيق."""

    from structlog.dev import ConsoleRenderer
    from structlog.processors import JSONRenderer

    shared_processors: list[Callable[[Any, str, MutableMapping], MutableMapping]] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.format_exc_info,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_correlation_id,
    ]

    if app.config.get("LOG_JSON", False):
        # Production: JSON output
        processors: list[
            Callable[[Any, str, MutableMapping], MutableMapping | str | bytes | bytearray | tuple[Any, ...]]
        ] = shared_processors + [JSONRenderer()]
    else:
        # Development: colored console
        processors = shared_processors + [ConsoleRenderer(colors=True)]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, app.config.get("LOG_LEVEL", "INFO"))),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # دمج مع stdlib logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, app.config.get("LOG_LEVEL", "INFO")),
    )

    # تقليل ضوضاء المكتبات
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _add_correlation_id(logger: Any, method_name: str, event_dict: MutableMapping) -> MutableMapping:
    """إضافة correlation ID لكل log entry."""
    cid = _correlation_id.get()
    if cid:
        event_dict["correlation_id"] = cid
    return event_dict


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """الحصول على logger مهيأ."""
    return structlog.get_logger(name)
