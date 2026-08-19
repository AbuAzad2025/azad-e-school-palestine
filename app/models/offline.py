"""وضع عدم الاتصال — تنزيل المحتوى للمشاهدة بدون إنترنت."""

from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .content import Lesson, LessonAttachment
from .mixins import PKMixin
from .user import User


class OfflineDownload(PKMixin, db.Model):
    """طلب تنزيل محتوى لوضع عدم الاتصال."""

    __tablename__ = "offline_downloads"

    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    attachment_id: Mapped[int] = mapped_column(ForeignKey("lesson_attachments.id"), nullable=False)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(15), default="pending", nullable=False)
    downloaded_at = db.Column(db.DateTime(timezone=True))
    expires_at = db.Column(db.DateTime(timezone=True))

    student: Mapped[User] = relationship("User", foreign_keys=[student_id])
    attachment: Mapped[LessonAttachment] = relationship("LessonAttachment")
    lesson: Mapped[Lesson] = relationship("Lesson", foreign_keys=[lesson_id])
