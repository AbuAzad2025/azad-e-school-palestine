"""الواجبات والتسليمات والدرجات ودفتر الدرجات"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Numeric, SmallInteger, String, Text
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
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

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
    graded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    graded_at = db.Column(db.DateTime(timezone=True))

    assignment: Mapped[Assignment] = relationship(back_populates="submissions")
    student: Mapped[User] = relationship("User", foreign_keys=[student_id])


class GradeCategory(PKMixin, db.Model):
    """قسم دفتر درجات (فصل أول/ثاني، شهري، نهائي) بوزن."""

    __tablename__ = "grade_categories"
    __table_args__ = (db.UniqueConstraint("class_id", "name", name="uq_grade_category"),)

    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[float | None] = mapped_column(Numeric(5, 2))  # نسبي (0–100% أو كسر)

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
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(Text)

    item: Mapped[GradeItem] = relationship(back_populates="entries")


class RubricTemplate(PKMixin, db.Model):
    """قالب تقييم بالمعيار (Rubric) — يُعاد استخدامه في أكثر من بند."""

    __tablename__ = "rubric_templates"

    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    criteria: Mapped[list[RubricCriterion]] = relationship(back_populates="template", cascade="all, delete-orphan")


class RubricCriterion(PKMixin, db.Model):
    """معيار واحد ضمن قالب التقييم."""

    __tablename__ = "rubric_criteria"

    template_id: Mapped[int] = mapped_column(ForeignKey("rubric_templates.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    max_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    sort_order: Mapped[int | None] = mapped_column(SmallInteger)

    template: Mapped[RubricTemplate] = relationship(back_populates="criteria")


class RubricGrade(PKMixin, db.Model):
    """درجة الطالب في معيار محدد — يتكرر لكل معيار في كل تسليم."""

    __tablename__ = "rubric_grades"
    __table_args__ = (db.UniqueConstraint("submission_id", "criterion_id", name="uq_rubric_grade"),)

    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), nullable=False)
    criterion_id: Mapped[int] = mapped_column(ForeignKey("rubric_criteria.id"), nullable=False)
    score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    graded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    submission: Mapped[Submission] = relationship("Submission")
    criterion: Mapped[RubricCriterion] = relationship("RubricCriterion")


class GradeAppeal(PKMixin, db.Model):
    __tablename__ = "grade_appeals"
    __table_args__ = (db.UniqueConstraint("submission_id", "student_id", name="uq_grade_appeal"),)

    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(15), default="pending", nullable=False)
    teacher_response: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at = db.Column(db.DateTime(timezone=True))

    submission: Mapped[Submission] = relationship("Submission")
    student: Mapped[User] = relationship("User", foreign_keys=[student_id])
