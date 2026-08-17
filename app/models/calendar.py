"""التقويم الأكاديمي — فترات دراسية، امتحانات، إجازات"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

from .mixins import PKMixin


class AcademicEvent(PKMixin, db.Model):
    """حدث أكاديمي: بداية فصل، نهاية فصل، فترة امتحانات، إجازة."""

    __tablename__ = "academic_events"

    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # term_start/term_end/exam_period/enrollment/holiday
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
