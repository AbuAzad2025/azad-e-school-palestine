"""الدروس الخصوصية — سوق حر خارج عزل المدرسة (استثناء تينانتس مقصود، §3.15).

بلا school_id: الحاجز هو المنصة، والوصول بصلاحية: طرفا الجلسة فقط + super_admin.
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Numeric, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .mixins import PKMixin
from .user import User


class TutorProfile(PKMixin, db.Model):
    __tablename__ = "tutor_profiles"

    tutor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    grade_levels: Mapped[list | None] = mapped_column(JSONB)
    price_hour: Mapped[float | None] = mapped_column(Numeric(10, 2))
    price_session: Mapped[float | None] = mapped_column(Numeric(10, 2))
    mode: Mapped[str] = mapped_column(String(10), default="both", nullable=False)  # online/offline/both
    availability: Mapped[dict | None] = mapped_column(JSONB)
    bio: Mapped[str | None] = mapped_column(Text)
    invite_code: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    video_provider: Mapped[str] = mapped_column(String(10), default="jitsi", nullable=False)

    tutor: Mapped[User] = relationship("User")


class TutoringRequest(PKMixin, db.Model):
    __tablename__ = "tutoring_requests"
    __table_args__ = (UniqueConstraint("tutor_id", "student_id", "status", name="uq_tutoring_request_open"),)

    tutor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    subject: Mapped[str | None] = mapped_column(Text)
    preferred_time = db.Column(db.DateTime(timezone=True))
    mode: Mapped[str] = mapped_column(String(10), default="online", nullable=False)
    price_quote: Mapped[float | None] = mapped_column(Numeric(10, 2))
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="pending", nullable=False)

    tutor: Mapped[User] = relationship("User", foreign_keys=[tutor_id])
    student: Mapped[User] = relationship("User", foreign_keys=[student_id])


class TutoringSession(PKMixin, db.Model):
    __tablename__ = "tutoring_sessions"

    request_id: Mapped[int | None] = mapped_column(ForeignKey("tutoring_requests.id"))
    tutor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    scheduled_at = db.Column(db.DateTime(timezone=True))
    duration_min: Mapped[int | None] = mapped_column(db.Integer)
    price: Mapped[float | None] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="ILS", nullable=False)
    mode: Mapped[str] = mapped_column(String(10), default="online", nullable=False)
    online_link: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="requested", nullable=False)
    payment_status: Mapped[str] = mapped_column(String(10), default="pending", nullable=False)
    end_time = db.Column(db.DateTime(timezone=True))
    video_provider: Mapped[str] = mapped_column(String(10), default="jitsi", nullable=False)
    zoom_meeting_id: Mapped[str | None] = mapped_column(String(64))
    zoom_join_url: Mapped[str | None] = mapped_column(Text)
    zoom_start_url: Mapped[str | None] = mapped_column(Text)

    request: Mapped[TutoringRequest | None] = relationship()
    tutor: Mapped[User] = relationship("User", foreign_keys=[tutor_id])
    student: Mapped[User] = relationship("User", foreign_keys=[student_id])
    reviews: Mapped[list[TutorReview]] = relationship(back_populates="session", cascade="all, delete-orphan")


class TutorReview(PKMixin, db.Model):
    __tablename__ = "tutor_reviews"
    __table_args__ = (UniqueConstraint("session_id", "student_id", name="uq_tutor_review_per_session"),)

    session_id: Mapped[int] = mapped_column(ForeignKey("tutoring_sessions.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)

    session: Mapped[TutoringSession] = relationship(back_populates="reviews")
    student: Mapped[User] = relationship("User", foreign_keys=[student_id])
