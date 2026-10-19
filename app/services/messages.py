"""الرسائل المباشرة: إرسال، استلام، خيوط، غير مقروءة."""

from app.core.db import tx
from app.core.i18n import _
from app.extensions import db
from app.models.message import Message
from app.models.user import User, UserRole


def _boundary_error(sender: User, recipient: User) -> str | None:
    """حدّ التينانتس للرسائل: داخل المدرسة نفسها فقط.

    ``messages`` لا يحمل ``school_id`` (خيط بين مستخدمَين لا صفّ ملك لمدرسة)،
    فالحماية على مستوى RLS لا تغطيه. الحارس هنا هو ما يمنع رسالة من مدرسة
    إلى أخرى، ويُطبَّق في الخدمة لا في المسار وحده حتى لا يتجاوزه أي مستدعٍ
    جديد.

    * استثناء واحد فقط: طرف مشرف كلي (super_admin) — يرسل ويستقبل عبر
      المدارس لأنه فوق التينانتس في بقية المنصة.
    * حساب بلا مدرسة نشطة (لا رابط دور) لا يستطيع إثبات مشاركة المستلم
      للمدرسة، فيُرفض بدل أن يُعامَل كأنه يشارك الجميع.
    """
    if UserRole.super_admin in (sender.role, recipient.role):
        return None
    sender_schools = {link.school_id for link in sender.role_links if link.is_active}
    recipient_schools = {link.school_id for link in recipient.role_links if link.is_active}
    if not sender_schools or not recipient_schools:
        return _("لا يمكن إرسال الرسائل إلا بين أعضاء المدرسة نفسها.")
    if sender_schools.isdisjoint(recipient_schools):
        return _("لا يمكن إرسال رسائل إلى أعضاء مدرسة أخرى.")
    return None


def send_message(
    sender_id: int,
    recipient_id: int,
    subject: str,
    body: str,
    parent_message_id: int | None = None,
) -> tuple[Message | None, str | None]:
    subject = (subject or "").strip()
    body = (body or "").strip()
    if not subject:
        return None, _("الموضوع مطلوب.")
    if not body:
        return None, _("نص الرسالة مطلوب.")
    if sender_id == recipient_id:
        return None, _("لا يمكنك إرسال رسالة لنفسك.")
    sender = db.session.get(User, sender_id)
    if not sender:
        return None, _("المرسل غير موجود.")
    recipient = db.session.get(User, recipient_id)
    if not recipient:
        return None, _("المستلم غير موجود.")
    boundary_error = _boundary_error(sender, recipient)
    if boundary_error:
        return None, boundary_error
    if parent_message_id is not None:
        parent = db.session.get(Message, parent_message_id)
        if not parent:
            return None, _("الرسالة الأصلية غير موجودة.")

    def _send():
        msg = Message(
            sender_id=sender_id,
            recipient_id=recipient_id,
            subject=subject,
            body=body,
            parent_message_id=parent_message_id,
        )
        db.session.add(msg)
        return msg

    return tx(_send), None


def inbox(user_id: int) -> list[Message]:
    """الرسائل الواردة (أقدم خيط فقط)."""
    from sqlalchemy.orm import joinedload

    return (
        Message.query.filter_by(recipient_id=user_id, parent_message_id=None)
        .options(joinedload(Message.sender))
        .order_by(Message.is_read.asc(), Message.created_at.desc())
        .all()
    )


def sent(user_id: int) -> list[Message]:
    from sqlalchemy.orm import joinedload

    return (
        Message.query.filter_by(sender_id=user_id, parent_message_id=None)
        .options(joinedload(Message.recipient))
        .order_by(Message.created_at.desc())
        .all()
    )


def get_thread(message_id: int) -> Message | None:
    """جلب رسالة + ردودها مرتبة."""
    from sqlalchemy.orm import joinedload

    return (
        db.session.query(Message)
        .options(joinedload(Message.sender), joinedload(Message.recipient))
        .filter(Message.id == message_id)
        .first()
    )


def mark_read(message_id: int, user_id: int) -> None:
    msg = db.session.get(Message, message_id)
    if msg and msg.recipient_id == user_id and not msg.is_read:

        def _mark():
            msg.is_read = True

        tx(_mark)


def unread_count(user_id: int) -> int:
    return Message.query.filter_by(recipient_id=user_id, is_read=False).count()
