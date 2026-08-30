"""الذكاء الاصطناعي: جلسات معلم افتراضي + رسائل + سجلات الاستخدام"""

from sqlalchemy import Float, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .mixins import PKMixin


class AiSession(PKMixin, db.Model):
    __tablename__ = "ai_sessions"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    class_id: Mapped[int | None] = mapped_column(ForeignKey("classes.id"))
    lesson_id: Mapped[int | None] = mapped_column(ForeignKey("lessons.id"))
    session_type: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict | None] = mapped_column(JSONB)

    messages: Mapped[list["AiMessage"]] = relationship(
        "AiMessage", back_populates="session", cascade="all, delete-orphan"
    )


class AiMessage(PKMixin, db.Model):
    __tablename__ = "ai_messages"

    session_id: Mapped[int] = mapped_column(ForeignKey("ai_sessions.id"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(Text)
    tokens: Mapped[int | None] = mapped_column(Integer)

    session: Mapped[AiSession] = relationship(back_populates="messages")


class AiUsageLog(PKMixin, db.Model):
    """سجل استخدام AI للتتبع والتكلفة"""

    __tablename__ = "ai_usage_logs"

    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict | None] = mapped_column(JSONB)
