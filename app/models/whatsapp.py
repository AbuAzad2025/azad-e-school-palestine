"""ربط أرقام واتساب بالحسابات — بوابة الأوامر الصادرة/الواردة.

لماذا جدول مستقل بدل عمود ``phone`` على ``users``:
    * الرقم **معرّف هوية خارجي** يحتاج تدقيقاً (مَن ربطه، متى، هل ما زال
      صالحاً) لا حقلاً على صف المستخدم.
    * الربط يجب أن يكون **مؤكَّداً**: رسالة واردة من رقم غير مربوط لا تُعطي
      أي بيانات (fail-closed)، والمرسل هو من يبدأ الربط بكود لمرة واحدة.
    * فكّ الربط (سحب) يجب ألا يمسّ المستخدم نفسه.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

from .mixins import PKMixin


class WhatsAppLink(PKMixin, db.Model):
    __tablename__ = "whatsapp_links"
    __table_args__ = (
        # رقم واحد = حساب واحد. فريد على الرقم وحده لأنWebhook لا يعرف
        # المدرسة مسبقاً؛ البحث بالرقم يحتاج فقط (phone) ⇒ O(1).
        UniqueConstraint("phone", name="uq_whatsapp_link_phone"),
        Index("ix_whatsapp_links_user_active", "user_id", "is_active"),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id])
    school = db.relationship("School", foreign_keys=[school_id])
