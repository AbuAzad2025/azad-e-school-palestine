"""المحتوى: الوحدات والدروس والمرفقات"""
from sqlalchemy import BigInteger, ForeignKey, Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from .mixins import PKMixin, SoftDeleteMixin


class Unit(PKMixin, db.Model):
    __tablename__ = "units"

    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int | None] = mapped_column(SmallInteger)


class Lesson(PKMixin, SoftDeleteMixin, db.Model):
    __tablename__ = "lessons"

    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False, index=True)
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("units.id"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[str | None] = mapped_column(Text)  # النص المنسّق
    sort_order: Mapped[int | None] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(10), default="draft", nullable=False)  # draft/published/archived
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    published_at = db.Column(db.DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    attachments: Mapped[list["LessonAttachment"]] = relationship(back_populates="lesson", cascade="all, delete-orphan")


class LessonAttachment(PKMixin, db.Model):
    __tablename__ = "lesson_attachments"

    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # video/pdf/image/graph/audio
    title: Mapped[str | None] = mapped_column(Text)
    stored_name: Mapped[str] = mapped_column(Text, nullable=False)  # اسم عشوائي (D7)
    original_name: Mapped[str | None] = mapped_column(Text)
    mime: Mapped[str | None] = mapped_column(String(120))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    youtube_url: Mapped[str | None] = mapped_column(Text)  # فيديو خارجي
    position: Mapped[int | None] = mapped_column(SmallInteger)

    lesson: Mapped[Lesson] = relationship(back_populates="attachments")
