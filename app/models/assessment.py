"""التقييم: اختبارات، أسئلة، محاولات، إجابات"""

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .mixins import PKMixin


class Quiz(PKMixin, db.Model):
    __tablename__ = "quizzes"

    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    duration_min: Mapped[int | None] = mapped_column(Integer)  # مؤقّت عدّ تنازلي
    attempts_allowed: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    open_at = db.Column(db.DateTime(timezone=True))
    close_at = db.Column(db.DateTime(timezone=True))
    shuffle: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    show_answers_after: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    total_mark: Mapped[float | None] = mapped_column(Numeric(6, 2))
    status: Mapped[str] = mapped_column(String(10), default="draft", nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    questions: Mapped[list["Question"]] = relationship(back_populates="quiz", cascade="all, delete-orphan")


class Question(PKMixin, db.Model):
    __tablename__ = "questions"

    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(15), nullable=False)  # mcq/true_false/essay/matching
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[dict | None] = mapped_column(JSONB)  # خيارات MCQ
    correct_answer: Mapped[dict | None] = mapped_column(JSONB)  # صيغة مرنة للتوصيل/مقالي
    mark: Mapped[float | None] = mapped_column(Numeric(5, 2))
    sort_order: Mapped[int | None] = mapped_column(SmallInteger)

    quiz: Mapped[Quiz] = relationship(back_populates="questions")


class QuizAttempt(PKMixin, db.Model):
    __tablename__ = "quiz_attempts"
    __table_args__ = (db.UniqueConstraint("quiz_id", "student_id", "attempt_no", name="uq_quiz_attempt"),)

    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    attempt_no: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    started_at = db.Column(db.DateTime(timezone=True))
    submitted_at = db.Column(db.DateTime(timezone=True))
    score: Mapped[float | None] = mapped_column(Numeric(6, 2))
    status: Mapped[str] = mapped_column(String(12), default="in_progress", nullable=False)

    answers: Mapped[list["Answer"]] = relationship(back_populates="attempt", cascade="all, delete-orphan")


class Answer(PKMixin, db.Model):
    __tablename__ = "answers"

    attempt_id: Mapped[int] = mapped_column(ForeignKey("quiz_attempts.id"), nullable=False)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), nullable=False)
    answer: Mapped[dict | None] = mapped_column(JSONB)
    is_correct: Mapped[bool | None] = mapped_column(Boolean)  # يملؤه المعلم للمقالي
    awarded_mark: Mapped[float | None] = mapped_column(Numeric(5, 2))

    attempt: Mapped[QuizAttempt] = relationship(back_populates="answers")
