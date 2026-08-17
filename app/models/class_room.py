"""الصفوف الدراسية والعضوية — قلب المنصة"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.school import Grade, Subject
from app.models.user import User

from .mixins import PKMixin, SoftDeleteMixin


class ClassRoom(PKMixin, SoftDeleteMixin, db.Model):
    __tablename__ = "classes"
    __table_args__ = (
        UniqueConstraint("school_id", "subject_id", "grade_id", "semester", name="uq_class_subject_grade_semester"),
    )

    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    grade_id: Mapped[int] = mapped_column(ForeignKey("grades.id"), nullable=False)
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    semester: Mapped[str | None] = mapped_column(String(10))  # first / second (السنوي من الفصلين)
    name: Mapped[str | None] = mapped_column(Text)
    join_code: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    price_first_term: Mapped[float | None] = mapped_column(Numeric(10, 2))
    price_second_term: Mapped[float | None] = mapped_column(Numeric(10, 2))
    price_annual: Mapped[float | None] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="ILS", nullable=False)

    members: Mapped[list[ClassMember]] = relationship(back_populates="class_room", cascade="all, delete-orphan")
    subject: Mapped[Subject] = relationship("Subject")
    grade: Mapped[Grade] = relationship("Grade")
    teacher: Mapped[User] = relationship("User")


class ClassMember(PKMixin, db.Model):
    __tablename__ = "class_members"
    __table_args__ = (UniqueConstraint("class_id", "user_id", name="uq_class_member"),)

    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="active", nullable=False)  # active/removed/pending
    joined_at = db.Column(db.DateTime(timezone=True))

    class_room: Mapped[ClassRoom] = relationship(back_populates="members")
    user: Mapped[User] = relationship("User")
