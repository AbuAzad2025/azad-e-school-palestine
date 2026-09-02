"""Bulk notification dispatch — async tasks for high-volume notifications.

P4-04: Bulk notification dispatching via Celery for thousands of recipients.
P4-05: Each recipient processed independently — partial failures don't block others.
P4-06: Tenancy-scoped: bulk ops filter by school_id to prevent cross-tenant leaks.
"""

from __future__ import annotations

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
    from app.models.notification import Notification
    from app.models.user import User

    logger = get_logger("celery.notifications")

    try:
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
        db.session.commit()

        logger.info("notification_dispatched", user_id=user_id, type=type)
        return {"success": True, "notification_id": notification.id, "error": None}

    except Exception as exc:
        db.session.rollback()
        logger.exception("notification_dispatch_failed", user_id=user_id)
        raise self.retry(exc=exc) from None


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
    from app.models.notification import Notification
    from app.models.user import User, UserRoleLink

    logger = get_logger("celery.notifications")
    errors: list[str] = []

    try:
        # Query users in this school
        query = User.query.join(UserRoleLink).filter(
            UserRoleLink.school_id == school_id,
            UserRoleLink.is_active == True,  # noqa: E712
        )

        if recipient_role:
            query = query.filter(UserRoleLink.role == recipient_role)

        users = query.all()
        sent_count = 0

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
                sent_count += 1
            except Exception as exc:
                errors.append(f"User {user.id}: {str(exc)}")

        db.session.commit()

        logger.info(
            "bulk_announcement_sent",
            school_id=school_id,
            sent_count=sent_count,
            error_count=len(errors),
        )
        return {"success": True, "sent_count": sent_count, "errors": errors}

    except Exception as exc:
        db.session.rollback()
        logger.exception("bulk_announcement_failed", school_id=school_id)
        raise self.retry(exc=exc) from None


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
