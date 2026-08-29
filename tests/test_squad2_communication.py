"""Squad 2 — Agent 7: Communication & Messaging.

Tests message delivery flows, failed channels, template rendering errors,
and notification dispatch.
"""

from app.extensions import db
from app.models.communication import Notification, NotificationPreference
from app.services.communication import audit, mark_all_read, notify, unread_count
from app.services.messages import (
    get_thread,
    inbox,
    mark_read,
    send_message,
    sent,
)
from app.services.messages import (
    unread_count as msg_unread_count,
)
from tests.conftest import make_school, make_user


# ---------------------------------------------------------------------------
# Notification: notify()
# ---------------------------------------------------------------------------
class TestNotify:
    def test_creates_notification(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            notify(uid, "result", "Exam Result", "You scored 85")
            notifs = Notification.query.filter_by(user_id=uid).all()
            assert len(notifs) == 1
            assert notifs[0].title == "Exam Result"

    def test_respects_in_app_disabled(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            # Disable in-app notifications
            pref = NotificationPreference(user_id=uid, notif_type="result", email_enabled=True, in_app_enabled=False)
            db.session.add(pref)
            db.session.commit()

            notify(uid, "result", "Test", "Body")
            notifs = Notification.query.filter_by(user_id=uid).all()
            assert len(notifs) == 0

    def test_no_preference_allows(self, app):
        """Without preference, notifications should be enabled by default."""
        with app.app_context():
            uid = make_user(app, "student")
            notify(uid, "badge", "New Badge", "You earned a badge")
            notifs = Notification.query.filter_by(user_id=uid, type="badge").all()
            assert len(notifs) == 1


# ---------------------------------------------------------------------------
# unread_count
# ---------------------------------------------------------------------------
class TestUnreadCount:
    def test_count_unread(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            db.session.add(Notification(user_id=uid, type="result", title="T1"))
            db.session.add(Notification(user_id=uid, type="result", title="T2", is_read=True))
            db.session.commit()
            assert unread_count(uid) == 1

    def test_count_zero(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            assert unread_count(uid) == 0


# ---------------------------------------------------------------------------
# mark_all_read
# ---------------------------------------------------------------------------
class TestMarkAllRead:
    def test_marks_all_read(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            db.session.add(Notification(user_id=uid, type="result", title="T1"))
            db.session.add(Notification(user_id=uid, type="result", title="T2"))
            db.session.commit()
            mark_all_read(uid)
            notifs = Notification.query.filter_by(user_id=uid, is_read=False).all()
            assert len(notifs) == 0


# ---------------------------------------------------------------------------
# audit()
# ---------------------------------------------------------------------------
class TestAudit:
    def test_creates_audit_log(self, app):
        with app.app_context():
            from unittest.mock import patch as _patch

            from app.models.system import AuditLog

            with _patch("app.services.communication.current_user") as mock_cu:
                mock_cu.is_authenticated = False
                audit("test_action", entity="users", entity_id=1, detail={"key": "value"})
            logs = AuditLog.query.filter_by(action="test_action").all()
            assert len(logs) == 1

    def test_with_financial_detail(self, app):
        with app.app_context():
            from unittest.mock import patch as _patch

            from app.models.system import AuditLog

            with _patch("app.services.communication.current_user") as mock_cu:
                mock_cu.is_authenticated = False
                audit(
                    "payment",
                    entity="subscriptions",
                    entity_id=1,
                    amount=100.50,
                    currency="ILS",
                    gateway="stripe",
                    subscription_id=1,
                )
            logs = AuditLog.query.filter_by(action="payment").all()
            assert len(logs) == 1

    def test_with_changes(self, app):
        with app.app_context():
            from unittest.mock import patch as _patch

            from app.models.system import AuditLog

            with _patch("app.services.communication.current_user") as mock_cu:
                mock_cu.is_authenticated = False
                audit(
                    "update",
                    entity="users",
                    entity_id=1,
                    changes={"name": {"old": "old", "new": "new"}},
                )
            logs = AuditLog.query.filter_by(action="update").all()
            assert len(logs) == 1


# ---------------------------------------------------------------------------
# send_message
# ---------------------------------------------------------------------------
class TestSendMessage:
    def test_send_success(self, app):
        with app.app_context():
            sid = make_school(app)
            sender = make_user(app, "student", school_id=sid)
            recipient = make_user(app, "teacher", school_id=sid)
            msg, error = send_message(sender, recipient, "Hello", "Body text")
            assert error is None
            assert msg is not None

    def test_send_empty_subject(self, app):
        with app.app_context():
            sid = make_school(app)
            sender = make_user(app, "student", school_id=sid)
            recipient = make_user(app, "teacher", school_id=sid)
            msg, error = send_message(sender, recipient, "", "Body")
            assert msg is None
            assert error is not None

    def test_send_empty_body(self, app):
        with app.app_context():
            sid = make_school(app)
            sender = make_user(app, "student", school_id=sid)
            recipient = make_user(app, "teacher", school_id=sid)
            msg, error = send_message(sender, recipient, "Subject", "")
            assert msg is None
            assert error is not None

    def test_send_to_self(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            msg, error = send_message(uid, uid, "Subject", "Body")
            assert msg is None
            assert "نفسك" in error

    def test_send_to_nonexistent_recipient(self, app):
        with app.app_context():
            sid = make_school(app)
            sender = make_user(app, "student", school_id=sid)
            msg, error = send_message(sender, 99999, "Subject", "Body")
            assert msg is None
            assert error is not None

    def test_send_reply(self, app):
        with app.app_context():
            sid = make_school(app)
            sender = make_user(app, "student", school_id=sid)
            recipient = make_user(app, "teacher", school_id=sid)
            msg1, _ = send_message(sender, recipient, "Original", "Body")
            msg2, error = send_message(recipient, sender, "Re:", "Reply body", parent_message_id=msg1.id)
            assert error is None

    def test_send_reply_to_nonexistent(self, app):
        with app.app_context():
            sid = make_school(app)
            sender = make_user(app, "student", school_id=sid)
            recipient = make_user(app, "teacher", school_id=sid)
            msg, error = send_message(sender, recipient, "Reply", "Body", parent_message_id=99999)
            assert msg is None
            assert error is not None


# ---------------------------------------------------------------------------
# inbox / sent
# ---------------------------------------------------------------------------
class TestInboxSent:
    def test_inbox(self, app):
        with app.app_context():
            sid = make_school(app)
            sender = make_user(app, "student", school_id=sid)
            recipient = make_user(app, "teacher", school_id=sid)
            send_message(sender, recipient, "Msg1", "Body1")
            result = inbox(recipient)
            assert len(result) == 1

    def test_sent(self, app):
        with app.app_context():
            sid = make_school(app)
            sender = make_user(app, "student", school_id=sid)
            recipient = make_user(app, "teacher", school_id=sid)
            send_message(sender, recipient, "Msg1", "Body1")
            result = sent(sender)
            assert len(result) == 1

    def test_inbox_excludes_replies(self, app):
        with app.app_context():
            sid = make_school(app)
            sender = make_user(app, "student", school_id=sid)
            recipient = make_user(app, "teacher", school_id=sid)
            msg1, _ = send_message(sender, recipient, "Original", "Body")
            send_message(recipient, sender, "Reply", "Reply body", parent_message_id=msg1.id)
            result = inbox(recipient)
            # Only the original message should be in inbox (not the reply)
            assert len(result) == 1


# ---------------------------------------------------------------------------
# get_thread
# ---------------------------------------------------------------------------
class TestGetThread:
    def test_get_existing_message(self, app):
        with app.app_context():
            sid = make_school(app)
            sender = make_user(app, "student", school_id=sid)
            recipient = make_user(app, "teacher", school_id=sid)
            msg, _ = send_message(sender, recipient, "Subject", "Body")
            result = get_thread(msg.id)
            assert result is not None
            assert result.id == msg.id

    def test_get_nonexistent(self, app):
        with app.app_context():
            result = get_thread(99999)
            assert result is None


# ---------------------------------------------------------------------------
# mark_read (messages)
# ---------------------------------------------------------------------------
class TestMessageMarkRead:
    def test_marks_read(self, app):
        with app.app_context():
            sid = make_school(app)
            sender = make_user(app, "student", school_id=sid)
            recipient = make_user(app, "teacher", school_id=sid)
            msg, _ = send_message(sender, recipient, "Subject", "Body")
            mark_read(msg.id, recipient)
            db.session.refresh(msg)
            assert msg.is_read is True

    def test_wrong_user_no_effect(self, app):
        with app.app_context():
            sid = make_school(app)
            sender = make_user(app, "student", school_id=sid)
            recipient = make_user(app, "teacher", school_id=sid)
            msg, _ = send_message(sender, recipient, "Subject", "Body")
            mark_read(msg.id, sender)
            db.session.refresh(msg)
            assert msg.is_read is False

    def test_nonexistent_message(self, app):
        with app.app_context():
            uid = make_user(app, "student")
            # Should not raise
            mark_read(99999, uid)


# ---------------------------------------------------------------------------
# unread_count (messages)
# ---------------------------------------------------------------------------
class TestMessageUnreadCount:
    def test_count(self, app):
        with app.app_context():
            sid = make_school(app)
            sender = make_user(app, "student", school_id=sid)
            recipient = make_user(app, "teacher", school_id=sid)
            send_message(sender, recipient, "Msg1", "Body1")
            send_message(sender, recipient, "Msg2", "Body2")
            assert msg_unread_count(recipient) == 2
