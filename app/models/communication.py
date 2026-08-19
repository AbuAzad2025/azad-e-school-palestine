"""التواصل: إعلانات الصف + إشعارات داخلية"""

from sqlalchemy import Boolean, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

from .mixins import PKMixin


class Announcement(PKMixin, db.Model):
    __tablename__ = "announcements"

    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id"), nullable=False)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Notification(PKMixin, db.Model):
    __tablename__ = "notifications"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)  # result/new_assignment/subscription...
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class NotificationPreference(PKMixin, db.Model):
    """تفضيلات إشعارات المستخدم — يتحكم في أنواع الإشعارات المطلوبة."""

    __tablename__ = "notification_preferences"
    __table_args__ = (db.UniqueConstraint("user_id", "notif_type", name="uq_notif_pref"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    notif_type: Mapped[str] = mapped_column(Text, nullable=False)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
