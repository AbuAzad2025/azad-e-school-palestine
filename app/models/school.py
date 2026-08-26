"""المدارس، السنوات، المستويات الدراسية، المواد"""

from sqlalchemy import Boolean, ForeignKey, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .mixins import PKMixin


class School(PKMixin, db.Model):
    __tablename__ = "schools"

    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(CITEXT, unique=True)
    join_code: Mapped[str | None] = mapped_column(CITEXT, unique=True)
    academic_year: Mapped[str | None] = mapped_column(String(20))
    stages: Mapped[list | None] = mapped_column(JSONB)  # ["primary","prep","secondary"]
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    @property
    def display_name(self):
        return self.name_ar or self.name_en or "مدرسة"

    @property
    def is_individual_school(self) -> bool:
        return bool(self.is_system)


class SchoolSetting(PKMixin, db.Model):
    """إعدادات ديناميكية مفتاح/قيمة — مرونة دون هجرات."""

    __tablename__ = "school_settings"
    __table_args__ = (UniqueConstraint("school_id", "key", name="uq_school_setting_key"),)

    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[dict] = mapped_column(JSONB)


class Grade(PKMixin, db.Model):
    """مستوى دراسي 1..12 داخل مدرسة."""

    __tablename__ = "grades"
    __table_args__ = (UniqueConstraint("school_id", "grade_level", name="uq_school_grade_level"),)

    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False)
    grade_level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    stage: Mapped[str | None] = mapped_column(String(20))  # primary/prep/secondary
    name_ar: Mapped[str | None] = mapped_column(Text)
    name_en: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int | None] = mapped_column(SmallInteger)

    subjects: Mapped[list["SubjectGradeLink"]] = relationship(back_populates="grade")


class Subject(PKMixin, db.Model):
    """مادة (رياضيات/علوم/عربي...) — قابلة للمشاركة بين المدارس."""

    __tablename__ = "subjects"

    code: Mapped[str | None] = mapped_column(String(20), unique=True)
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str | None] = mapped_column(Text)
    is_elective: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # مادة اختيارية
    icon: Mapped[str | None] = mapped_column(Text)
    moe_code: Mapped[str | None] = mapped_column(String(50))
    moe_curriculum_version: Mapped[str | None] = mapped_column(String(50))

    grade_links: Mapped[list["SubjectGradeLink"]] = relationship(back_populates="subject")


class SubjectGradeLink(PKMixin, db.Model):
    """أي مادة تُدرس لأي صف (كل المواد لكل الصفوف + الاختياري)."""

    __tablename__ = "subject_grade_links"
    __table_args__ = (UniqueConstraint("subject_id", "grade_id", name="uq_subject_grade"),)

    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    grade_id: Mapped[int] = mapped_column(ForeignKey("grades.id"), nullable=False)

    subject: Mapped[Subject] = relationship(back_populates="grade_links")
    grade: Mapped[Grade] = relationship(back_populates="subjects")
