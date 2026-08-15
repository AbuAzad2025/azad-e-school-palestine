"""ذرّية المعاملات — النقطة المركزية الوحيدة لكل commit/rollback.

كل عملية كتابة في services تمر عبر tx():
1. commit واحد عند النجاح.
2. rollback كامل عند أي خطأ (لا حالة نصف مكتوبة).
3. تسجيل الخطأ في سجل التطبيق.
"""
from collections.abc import Callable
from typing import Any, TypeVar

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db

T = TypeVar("T")


class TxError(Exception):
    """خطأ منطقي في العملية — يُترجَم لرسالة مستخدم دون rollback مزدوج."""


def tx(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """ينفّذ func داخل معاملة واحدة. يعيد النتيجة أو يرفع الخطأ مع rollback."""
    try:
        result = func(*args, **kwargs)
        db.session.commit()
        return result
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("فشل المعاملة")
        raise
    except Exception:
        db.session.rollback()
        raise
