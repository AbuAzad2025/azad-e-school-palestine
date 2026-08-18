"""الرسائل المباشرة — تواصل بين المستخدمين."""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

from .mixins import PKMixin
from .user import User


class Message(PKMixin, db.Model):
    __tablename__ = "messages"

    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    parent_message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"))

    sender: Mapped[User] = relationship("User", foreign_keys=[sender_id])
    recipient: Mapped[User] = relationship("User", foreign_keys=[recipient_id])
    replies: Mapped[list[Message]] = relationship(
        "Message",
        foreign_keys=[parent_message_id],
        back_populates="parent",
    )
    parent: Mapped[Message | None] = relationship(
        "Message",
        foreign_keys=[parent_message_id],
        remote_side="Message.id",
        back_populates="replies",
    )
