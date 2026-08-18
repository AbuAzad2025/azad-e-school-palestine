"""بنك الأسئلة — مكتبة مشاركة الأسئلة بين المعلمين."""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

from .mixins import PKMixin


class QuestionBank(PKMixin, db.Model):
    __tablename__ = "question_bank"

    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False, index=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id"))
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(String(15), nullable=False)  # mcq/true_false/essay
    options: Mapped[dict | None] = mapped_column(JSONB)
    correct_answer: Mapped[dict | None] = mapped_column(JSONB)
    difficulty: Mapped[int] = mapped_column(SmallInteger, default=3, nullable=False)  # 1-5
    tags: Mapped[list | None] = mapped_column(JSONB)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
