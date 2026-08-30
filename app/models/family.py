"""روابط الأسرة — ربط ولي الأمر بالطالب"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .mixins import PKMixin
from .user import User


class FamilyLink(PKMixin, db.Model):
    """ربط ولي أمر بطالب. الحالة: pending → active / removed."""

    __tablename__ = "family_links"
    __table_args__ = (UniqueConstraint("parent_id", "student_id", name="uq_family_link"),)

    parent_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(10), default="active", nullable=False)  # active/pending/removed
    linked_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), server_default=db.func.now())

    parent: Mapped[User] = relationship("User", foreign_keys=[parent_id])
    student: Mapped[User] = relationship("User", foreign_keys=[student_id])


class FamilyLinkCode(PKMixin, db.Model):
    """رمز ربط مؤقت — يُنشئه الطالب ويُرسله لولي الأمر."""

    __tablename__ = "family_link_codes"
    __table_args__ = (UniqueConstraint("student_id", "code", name="uq_student_link_code"),)

    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    used: Mapped[bool] = mapped_column(db.Boolean, default=False, nullable=False)
    used_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), server_default=db.func.now())

    student: Mapped[User] = relationship("User", foreign_keys=[student_id])
    user: Mapped[User] = relationship("User", foreign_keys=[used_by])
