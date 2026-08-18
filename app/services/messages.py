"""الرسائل المباشرة: إرسال، استلام، خيوط، غير مقروءة."""

from app.core.db import tx
from app.extensions import db
from app.models.message import Message
from app.models.user import User


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
        return None, "الموضوع مطلوب."
    if not body:
        return None, "نص الرسالة مطلوب."
    if sender_id == recipient_id:
        return None, "لا يمكنك إرسال رسالة لنفسك."
    recipient = db.session.get(User, recipient_id)
    if not recipient:
        return None, "المستلم غير موجود."
    if parent_message_id is not None:
        parent = db.session.get(Message, parent_message_id)
        if not parent:
            return None, "الرسالة الأصلية غير موجودة."

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
    return (
        Message.query.filter_by(recipient_id=user_id, parent_message_id=None)
        .order_by(Message.is_read.asc(), Message.created_at.desc())
        .all()
    )


def sent(user_id: int) -> list[Message]:
    return Message.query.filter_by(sender_id=user_id, parent_message_id=None).order_by(Message.created_at.desc()).all()


def get_thread(message_id: int) -> Message | None:
    """جلب رسالة + ردودها مرتبة."""
    return db.session.get(Message, message_id)


def mark_read(message_id: int, user_id: int) -> None:
    msg = db.session.get(Message, message_id)
    if msg and msg.recipient_id == user_id and not msg.is_read:

        def _mark():
            msg.is_read = True

        tx(_mark)


def unread_count(user_id: int) -> int:
    return Message.query.filter_by(recipient_id=user_id, is_read=False).count()
