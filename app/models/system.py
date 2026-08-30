"""سجل التدقيق + إعدادات النظام"""

from sqlalchemy import BigInteger, Boolean, ForeignKey, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

from .mixins import PKMixin


class AuditLog(PKMixin, db.Model):
    __tablename__ = "audit_logs"

    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    entity: Mapped[str | None] = mapped_column(Text, index=True)
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    detail: Mapped[dict | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(INET)

    user = db.relationship("User", foreign_keys=[user_id])


class Setting(PKMixin, db.Model):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[dict] = mapped_column(JSONB)


class OnboardingProgress(PKMixin, db.Model):
    __tablename__ = "onboarding_progress"

    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False, unique=True)
    current_step: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    total_steps: Mapped[int] = mapped_column(SmallInteger, default=5, nullable=False)
    completed_steps: Mapped[dict | None] = mapped_column(JSONB)
    is_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True))


class HealthCheck(PKMixin, db.Model):
    __tablename__ = "health_checks"

    component: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(BigInteger)
    checked_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())


class CertificateTemplate(PKMixin, db.Model):
    __tablename__ = "certificate_templates"

    school_id: Mapped[int | None] = mapped_column(
        ForeignKey("schools.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    template_html: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
