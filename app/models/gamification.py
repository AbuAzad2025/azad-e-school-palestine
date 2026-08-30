"""نظام الشارات والتحفيز (Gamification) — شارات الإنجاز والجوائز."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Boolean, ForeignKey, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .mixins import PKMixin


class BadgeCriteriaType(StrEnum):
    """أنواع معايير كسب الشارة."""

    first_quiz = "first_quiz"  # أول اختبار
    perfect_score = "perfect_score"  # درجة مثالية
    streak_7_days = "streak_7_days"  # سلسلة 7 أيام
    course_complete = "course_complete"  # إكمال دورة
    early_bird = "early_bird"  # المبكر


class Badge(PKMixin, db.Model):
    """شارة إنجاز."""

    __tablename__ = "badges"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    icon_name: Mapped[str] = mapped_column(String(50), nullable=False)  # اسم الأيقونة من المجموعة
    criteria_type: Mapped[BadgeCriteriaType] = mapped_column(
        db.Enum(BadgeCriteriaType, name="badge_criteria_type"), nullable=False
    )
    criteria_value: Mapped[int | None] = mapped_column(SmallInteger)  # قيمة المعيار (مثلاً: 7 لـ streak_7_days)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    student_badges: Mapped[list[StudentBadge]] = relationship(back_populates="badge", cascade="all, delete-orphan")


class StudentBadge(PKMixin, db.Model):
    """شارة حصل عليها طالب."""

    __tablename__ = "student_badges"
    __table_args__ = (UniqueConstraint("student_id", "badge_id", name="uq_student_badge"),)

    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    badge_id: Mapped[int] = mapped_column(ForeignKey("badges.id"), nullable=False, index=True)
    earned_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())

    student: Mapped[User] = relationship("User", foreign_keys=[student_id])  # noqa: F821
    badge: Mapped[Badge] = relationship(back_populates="student_badges")
