"""Bulk notification dispatch — async tasks for high-volume notifications.

P4-04: Bulk notification dispatching via Celery for thousands of recipients.
P4-05: Each recipient processed independently — partial failures don't block others.
P4-06: Tenancy-scoped: bulk ops filter by school_id to prevent cross-tenant leaks.
"""

from __future__ import annotations

from app.core.db import tx
from app.tasks import _HAS_CELERY, ContextTask, celery_app

if not _HAS_CELERY:
    # Module is a no-op when Celery is not installed
    raise ImportError("Celery is required for app.tasks.notifications")


@celery_app.task(base=ContextTask, bind=True, max_retries=3, default_retry_delay=60)
def dispatch_notification(
    self,
    user_id: int,
    type: str,
    title: str,
    body: str = "",
    link: str = "",
) -> dict:
    """Dispatch a single notification to a user.

    Args:
        user_id: Target user.
        type: Notification type (grade, message, alert, etc.).
        title: Notification title.
        body: Notification body text.
        link: Optional URL to navigate to.

    Returns:
        {success: bool, notification_id: int | None, error: str | None}
    """
    from app.core.logging import get_logger
    from app.extensions import db
    from app.models.communication import Notification
    from app.models.user import User

    logger = get_logger("celery.notifications")

    def _dispatch():
        user = db.session.get(User, user_id)
        if not user:
            return {"success": False, "notification_id": None, "error": "User not found"}

        notification = Notification(
            user_id=user_id,
            type=type,
            title=title,
            body=body,
            link=link,
            is_read=False,
        )
        db.session.add(notification)
        # الدالة تُرجع id الإشعار للمُنادي — يتولد عند الـ flush (ليس عند الإنشاء)،
        # لذا نُجري flush داخل نفس tx() ليُعيَّن المعرف قبل الالتزام (بدون commit مبكر).
        db.session.flush()
        return {"success": True, "notification_id": notification.id, "error": None}

    try:
        result = tx(_dispatch)
    except Exception as exc:
        logger.exception("notification_dispatch_failed", user_id=user_id)
        raise self.retry(exc=exc) from None

    logger.info("notification_dispatched", user_id=user_id, type=type)
    return result


@celery_app.task(base=ContextTask, bind=True, max_retries=2)
def bulk_dispatch_school_announcement(
    self,
    school_id: int,
    title: str,
    body: str,
    link: str = "",
    recipient_role: str | None = None,
) -> dict:
    """Send announcement to all users in a school.

    Args:
        school_id: Target school (tenant isolation).
        title: Announcement title.
        body: Announcement body.
        link: Optional URL.
        recipient_role: If set, only send to users with this role.

    Returns:
        {success: bool, sent_count: int, errors: list[str]}
    """
    from app.core.logging import get_logger
    from app.extensions import db
    from app.models.communication import Notification
    from app.models.user import User, UserRoleLink

    logger = get_logger("celery.notifications")

    def _dispatch():
        # Query users in this school
        # explicit onclause — users↔user_role_links have two FKs (user_id, approved_by)
        query = User.query.join(UserRoleLink, UserRoleLink.user_id == User.id).filter(
            UserRoleLink.school_id == school_id,
            UserRoleLink.is_active == True,  # noqa: E712
        )

        if recipient_role:
            query = query.filter(UserRoleLink.role == recipient_role)

        users = query.all()
        errors: list[str] = []

        for user in users:
            try:
                notification = Notification(
                    user_id=user.id,
                    type="announcement",
                    title=title,
                    body=body,
                    link=link,
                    is_read=False,
                )
                db.session.add(notification)
            except Exception as exc:
                errors.append(f"User {user.id}: {str(exc)}")

        return {"success": True, "sent_count": len(users) - len(errors), "errors": errors}

    try:
        result = tx(_dispatch)
    except Exception as exc:
        logger.exception("bulk_announcement_failed", school_id=school_id)
        raise self.retry(exc=exc) from None

    logger.info(
        "bulk_announcement_sent",
        school_id=school_id,
        sent_count=result["sent_count"],
        error_count=len(result["errors"]),
    )
    return result


@celery_app.task(base=ContextTask, bind=True, max_retries=2)
def dispatch_email_notification(
    self,
    user_id: int,
    subject: str,
    html_body: str,
    plain_body: str = "",
) -> dict:
    """Send email notification to a user.

    Args:
        user_id: Target user.
        subject: Email subject.
        html_body: HTML email body.
        plain_body: Plain text fallback.

    Returns:
        {success: bool, error: str | None}
    """
    from app.core.logging import get_logger
    from app.extensions import db
    from app.models.user import User
    from app.services.email import _send

    logger = get_logger("celery.notifications")

    try:
        user = db.session.get(User, user_id)
        if not user:
            return {"success": False, "error": "User not found"}

        _send(
            to=user.email,
            subject=subject,
            html_body=html_body,
        )

        logger.info("email_dispatched", user_id=user_id, subject=subject)
        return {"success": True, "error": None}

    except Exception as exc:
        logger.exception("email_dispatch_failed", user_id=user_id)
        raise self.retry(exc=exc) from None


@celery_app.task(base=ContextTask, bind=True, max_retries=3, default_retry_delay=30)
def send_whatsapp_task(self, to: str, body: str, idempotency_key: str = "") -> dict:
    """Send one outbound WhatsApp message via the Graph API.

    Referenced by ``app.services.whatsapp.dispatch_outbound`` as the fast path
    when Celery is installed; without Celery the service falls back to a
    worker thread, so the engine never depends on a broker.

    Args:
        to: Destination number in E.164 form.
        body: Message text (truncated to the platform limit by the service).
        idempotency_key: Provider message id, kept for log correlation.

    Returns:
        {success: bool, error: str | None}
    """
    from app.core.logging import get_logger
    from app.services.whatsapp import OutboundMessage, deliver_outbound

    logger = get_logger("celery.whatsapp")
    try:
        ok = deliver_outbound(OutboundMessage(to=to, body=body, idempotency_key=idempotency_key))
    except Exception as exc:
        logger.exception("whatsapp_dispatch_failed", idempotency_key=idempotency_key)
        raise self.retry(exc=exc) from None

    if not ok:
        return {"success": False, "error": "delivery_rejected"}
    return {"success": True, "error": None}
