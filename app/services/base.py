"""أساس الخدمات — BaseService generic مع CRUD، فلترة، وترقيم.

كل service يرث من BaseService[Model] ويضيف المنطق الخاص.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import asc, desc
from sqlalchemy.orm import Query

from app.core.db import TxError, tx, tx_on_commit
from app.extensions import db

T = TypeVar("T")


class PaginationMeta:
    """بيانات ترقيم النتائج الموحّدة."""

    def __init__(self, page: int, per_page: int, total: int) -> None:
        self.page = page
        self.per_page = per_page
        self.total = total
        self.pages = (total + per_page - 1) // per_page if per_page > 0 else 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "per_page": self.per_page,
            "total": self.total,
            "pages": self.pages,
        }


class PaginatedResult(Generic[T]):
    """نتيجة استعلام مُرقّم."""

    def __init__(self, items: Sequence[T], meta: PaginationMeta) -> None:
        self.items = items
        self.meta = meta

    def to_dict(self, serializer: Callable[[T], dict[str, Any]] | None = None) -> dict[str, Any]:
        items = [serializer(i) for i in self.items] if serializer else list(self.items)
        return {"items": items, "meta": self.meta.to_dict()}


class BaseService(Generic[T]):
    """خدمة أساسية generic — CRUD + query + pagination.

    الاستخدام:
        class UserService(BaseService[User]):
            model = User
    """

    model: type[T] | None = None

    @classmethod
    def _query(cls) -> Query:
        if cls.model is None:
            raise TxError("model غير محدد في Service.")
        return db.session.query(cls.model)

    @classmethod
    def get(cls, pk: int) -> T | None:
        """جلب كيان بواسطة المفتاح الأساسي."""
        if cls.model is None:
            raise TxError("model غير محدد في Service.")
        return db.session.get(cls.model, pk)

    @classmethod
    def get_or_404(cls, pk: int) -> T:
        """جلب كيان أو رفع 404."""
        obj = cls.get(pk)
        if obj is None:
            from flask import abort

            abort(404)
        return obj

    @classmethod
    def list(
        cls,
        *,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
        desc_order: bool = False,
        page: int = 1,
        per_page: int = 20,
    ) -> PaginatedResult[T]:
        """قائمة مُفلترة ومُرقّمة."""
        q = cls._query()

        if filters:
            for col, val in filters.items():
                if hasattr(cls.model, col) and val is not None:
                    q = q.filter(getattr(cls.model, col) == val)

        if order_by and hasattr(cls.model, order_by):
            col = getattr(cls.model, order_by)
            q = q.order_by(desc(col) if desc_order else asc(col))

        total = q.count()
        items = q.limit(per_page).offset((page - 1) * per_page).all()
        meta = PaginationMeta(page=page, per_page=per_page, total=total)
        return PaginatedResult(items=items, meta=meta)

    @classmethod
    def create(cls, **kwargs: Any) -> T:
        """إنشاء كيان جديد داخل معاملة ذرّية."""
        if cls.model is None:
            raise TxError("model غير محدد في Service.")

        model = cls.model

        def _create() -> T:
            obj = model(**kwargs)
            db.session.add(obj)
            return obj

        return tx(_create)

    @classmethod
    def update(cls, pk: int, **kwargs: Any) -> T | None:
        """تحديث كيان موجود."""
        obj = cls.get(pk)
        if obj is None:
            return None

        def _update() -> T:
            for k, v in kwargs.items():
                if hasattr(obj, k):
                    setattr(obj, k, v)
            return obj

        return tx(_update)

    @classmethod
    def delete(cls, pk: int) -> bool:
        """حذف ناعم (soft-delete) إذا كان متاحاً، وإلا حذف فيزيائي."""
        obj = cls.get(pk)
        if obj is None:
            return False

        def _delete() -> None:
            if hasattr(obj, "deleted_at"):
                from datetime import UTC, datetime

                obj.deleted_at = datetime.now(UTC)
            else:
                db.session.delete(obj)

        tx(_delete)
        return True

    @classmethod
    def count(cls, **filters: Any) -> int:
        """عدد الكيانات مطابقاً للفلاتر."""
        q = cls._query()
        for col, val in filters.items():
            if hasattr(cls.model, col) and val is not None:
                q = q.filter(getattr(cls.model, col) == val)
        return q.count()


# إعادة التصدير للتوافق مع الملفات القديمة
__all__ = ["BaseService", "PaginatedResult", "PaginationMeta", "TxError", "tx", "tx_on_commit"]
