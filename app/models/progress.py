"""تتبع تقدم الطالب — الحضور والإنتاج في المنصة الإلكترونية"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .mixins import PKMixin
from .user import User

if TYPE_CHECKING:
    from .content import Lesson


class StudentProgress(PKMixin, db.Model):
    """تقدم الطالب في درس واحد — تتبع وقت المشاهدة والتقدم."""

    __tablename__ = "student_progress"
    __table_args__ = (UniqueConstraint("student_id", "lesson_id", name="uq_student_lesson_progress"),)

    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id"), nullable=False, index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), default="not_started", nullable=False
    )  # not_started/in_progress/completed
    started_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    seconds_spent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    progress_pct: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)  # 0-100

    student: Mapped[User] = relationship("User", foreign_keys=[student_id])
    lesson: Mapped[Lesson] = relationship("Lesson", foreign_keys=[lesson_id])


class VideoProgress(PKMixin, db.Model):
    """تقدم الطالب في فيديو واحد — تتبع الموضع والإكمال."""

    __tablename__ = "video_progress"
    __table_args__ = (UniqueConstraint("student_id", "attachment_id", name="uq_student_video_progress"),)

    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    attachment_id: Mapped[int] = mapped_column(ForeignKey("lesson_attachments.id"), nullable=False, index=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id"), nullable=False, index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False, index=True)
    seconds_watched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_watched_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))

    student: Mapped[User] = relationship("User", foreign_keys=[student_id])
