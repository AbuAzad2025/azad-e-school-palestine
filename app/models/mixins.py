"""Mixins مشتركة لكل الجداول — اتساق كامل (توقيت + حذف ناعم)"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class PKMixin:
    """id تزايدي + created_at/updated_at تلقائيان."""

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SoftDeleteMixin:
    """حذف ناعم: deleted_at NOT NULL يعني الكيان محذوف (لا حذف فيزيائي للدرجات/المحاضر)."""

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
