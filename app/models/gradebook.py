"""الواجبات والتسليمات والدرجات ودفتر الدرجات"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .mixins import PKMixin
from .user import User


class Assignment(PKMixin, db.Model):
    __tablename__ = "assignments"

    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    due_at = db.Column(db.DateTime(timezone=True))
    max_mark: Mapped[float | None] = mapped_column(Numeric(5, 2))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    submissions: Mapped[list[Submission]] = relationship(back_populates="assignment", cascade="all, delete-orphan")


class Submission(PKMixin, db.Model):
    __tablename__ = "submissions"
    __table_args__ = (db.UniqueConstraint("assignment_id", "student_id", name="uq_assignment_student"),)

    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    file: Mapped[str | None] = mapped_column(Text)  # stored_name
    submitted_at = db.Column(db.DateTime(timezone=True))
    mark: Mapped[float | None] = mapped_column(Numeric(5, 2))
    feedback: Mapped[str | None] = mapped_column(Text)
    graded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    graded_at = db.Column(db.DateTime(timezone=True))

    assignment: Mapped[Assignment] = relationship(back_populates="submissions")
    student: Mapped[User] = relationship("User", foreign_keys=[student_id])


class GradeCategory(PKMixin, db.Model):
    """قسم دفتر درجات (فصل أول/ثاني، شهري، نهائي) بوزن."""

    __tablename__ = "grade_categories"
    __table_args__ = (db.UniqueConstraint("class_id", "name", name="uq_grade_category"),)

    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[float | None] = mapped_column(Numeric(3, 2))  # نسبي

    items: Mapped[list[GradeItem]] = relationship(back_populates="category", cascade="all, delete-orphan")


class GradeItem(PKMixin, db.Model):
    """بند تقييم (اختبار/واجب/حضور) تحت قسم."""

    __tablename__ = "grade_items"

    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False, index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("grade_categories.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    max_mark: Mapped[float | None] = mapped_column(Numeric(5, 2))
    due_at = db.Column(db.DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(15), default="exam", nullable=False)  # quiz/assignment/exam/project

    category: Mapped[GradeCategory] = relationship(back_populates="items")
    entries: Mapped[list[GradeEntry]] = relationship(back_populates="item", cascade="all, delete-orphan")


class GradeEntry(PKMixin, db.Model):
    """درجة الطالب في بند واحد — لا تتكرر."""

    __tablename__ = "grade_entries"
    __table_args__ = (db.UniqueConstraint("student_id", "grade_item_id", name="uq_grade_entry"),)

    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    grade_item_id: Mapped[int] = mapped_column(ForeignKey("grade_items.id"), nullable=False)
    mark: Mapped[float | None] = mapped_column(Numeric(5, 2))
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(Text)

    item: Mapped[GradeItem] = relationship(back_populates="entries")
