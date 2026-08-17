"""حدود التينانتس (SaaS) — حدود الموارد لكل مدرسة حسب الباقة."""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

from .mixins import PKMixin


class TenantQuota(PKMixin, db.Model):
    """حدود الموارد لكل مدرسة."""

    __tablename__ = "tenant_quotas"

    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), unique=True, nullable=False, index=True)
    tier: Mapped[str] = mapped_column(String(20), default="free", nullable=False)  # free/basic/pro/enterprise
    max_students: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    max_teachers: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    max_classes: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    max_storage_mb: Mapped[int] = mapped_column(Integer, default=1024, nullable=False)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_ai_tokens_monthly: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
