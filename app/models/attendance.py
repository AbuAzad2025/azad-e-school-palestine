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


class AbsenceAlertLog(PKMixin, db.Model):
    """AZ-P2-12 — سجل تنبيهات الغياب لوليّ الأمر — يمنع الإرسال المكرر.

    سجل واحد لكل (طالب، يوم غياب): المهمة اليومية تشغّل وقد يغيب الطالب
    في صفوف متعددة بنفس اليوم، ووجود السجل يقطع دورة إعادة الإرسال
    في أي تشغيل لاحق (على نمط ReminderLog في الاشتراكات).
    """

    __tablename__ = "absence_alert_logs"
    __table_args__ = (db.UniqueConstraint("student_id", "date", name="uq_absence_alert_day"),)

    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    date: Mapped[object] = mapped_column(Date, nullable=False, index=True)
    sent_at = db.Column(db.DateTime(timezone=True))
