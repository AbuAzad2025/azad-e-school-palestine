"""الذكاء الاصطناعي: جلسات معلم افتراضي + رسائل (F27-F30 — مُخطَّط مسبقاً)"""

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .mixins import PKMixin


class AiSession(PKMixin, db.Model):
    __tablename__ = "ai_sessions"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)
    lesson_id: Mapped[int | None] = mapped_column(ForeignKey("lessons.id"))  # سياق الشرح
    session_type: Mapped[str] = mapped_column(Text, nullable=False)  # tutor/question_generator/grading_assist
    meta: Mapped[dict | None] = mapped_column(JSONB)

    messages: Mapped[list["AiMessage"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class AiMessage(PKMixin, db.Model):
    __tablename__ = "ai_messages"

    session_id: Mapped[int] = mapped_column(ForeignKey("ai_sessions.id"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)  # user/assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(Text)
    tokens: Mapped[int | None] = mapped_column(Integer)

    session: Mapped[AiSession] = relationship(back_populates="messages")
