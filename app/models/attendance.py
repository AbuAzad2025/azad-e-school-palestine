"""الحضور اليومي"""

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

from .mixins import PKMixin


class Attendance(PKMixin, db.Model):
    __tablename__ = "attendance"
    __table_args__ = (db.UniqueConstraint("class_id", "student_id", "date", name="uq_attendance_day"),)

    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    date: Mapped[object] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False)  # present/absent/late/excused
    note: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
