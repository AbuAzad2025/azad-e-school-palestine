"""Unit tests for additional services: gamification, messages, health."""

from tests.conftest import (
    make_school,
    make_user,
)


class TestMessages:
    def test_send_message_basic(self, app):
        from app.services.messages import send_message

        with app.app_context():
            sid = make_school(app)
            sender = make_user(app, "student", school_id=sid)
            recipient = make_user(app, "student", school_id=sid)
            msg, err = send_message(sender, recipient, "Subject", "Body")
            assert msg is not None
            assert err is None
            assert msg.subject == "Subject"

    def test_send_message_empty_subject(self, app):
        from app.services.messages import send_message

        with app.app_context():
            sid = make_school(app)
            sender = make_user(app, "student", school_id=sid)
            recipient = make_user(app, "student", school_id=sid)
            msg, err = send_message(sender, recipient, "", "Body")
            assert msg is None
            assert "الموضوع" in err

    def test_send_message_empty_body(self, app):
        from app.services.messages import send_message

        with app.app_context():
            sid = make_school(app)
            sender = make_user(app, "student", school_id=sid)
            recipient = make_user(app, "student", school_id=sid)
            msg, err = send_message(sender, recipient, "Subj", "")
            assert msg is None
            assert "نص" in err

    def test_send_message_self_send(self, app):
        from app.services.messages import send_message

        with app.app_context():
            sid = make_school(app)
            user = make_user(app, "student", school_id=sid)
            msg, err = send_message(user, user, "Subj", "Body")
            assert msg is None
            assert "نفسك" in err

    def test_send_message_nonexistent_recipient(self, app):
        from app.services.messages import send_message

        with app.app_context():
            sid = make_school(app)
            sender = make_user(app, "student", school_id=sid)
            msg, err = send_message(sender, 999999, "Subj", "Body")
            assert msg is None
            assert "المستلم" in err

    def test_inbox(self, app):
        from app.services.messages import inbox, send_message

        with app.app_context():
            sid = make_school(app)
            sender = make_user(app, "student", school_id=sid)
            recipient = make_user(app, "student", school_id=sid)
            send_message(sender, recipient, "Subj", "Body")
            messages = inbox(recipient)
            assert len(messages) >= 1

    def test_sent(self, app):
        from app.services.messages import send_message, sent

        with app.app_context():
            sid = make_school(app)
            sender = make_user(app, "student", school_id=sid)
            recipient = make_user(app, "student", school_id=sid)
            send_message(sender, recipient, "Subj", "Body")
            messages = sent(sender)
            assert len(messages) >= 1

    def test_mark_read(self, app):
        from app.services.messages import get_thread, mark_read, send_message

        with app.app_context():
            sid = make_school(app)
            sender = make_user(app, "student", school_id=sid)
            recipient = make_user(app, "student", school_id=sid)
            msg, _ = send_message(sender, recipient, "Subj", "Body")
            assert msg is not None
            mark_read(msg.id, recipient)
            thread = get_thread(msg.id)
            assert thread.is_read is True

    def test_unread_count(self, app):
        from app.services.messages import send_message, unread_count

        with app.app_context():
            sid = make_school(app)
            sender = make_user(app, "student", school_id=sid)
            recipient = make_user(app, "student", school_id=sid)
            send_message(sender, recipient, "Subj", "Body")
            count = unread_count(recipient)
            assert count >= 1


class TestFamilyLinkCode:
    def test_generate_and_link(self, app):
        from app.services.family import generate_link_code, link_parent

        with app.app_context():
            sid = make_school(app)
            student = make_user(app, "student", school_id=sid)
            parent = make_user(app, "parent", school_id=sid)
            code_str, err = generate_link_code(student)
            assert code_str is not None
            assert err is None
            link, err = link_parent(parent, code_str)
            assert link is not None

    def test_generate_code_creates_code(self, app):
        from app.services.family import generate_link_code

        with app.app_context():
            sid = make_school(app)
            student = make_user(app, "student", school_id=sid)
            code_str, err = generate_link_code(student)
            assert code_str is not None
            assert len(code_str) > 0
            assert err is None


class TestHealth:
    def test_record_health(self, app):
        from app.services.health import record_health

        with app.app_context():
            result = record_health({
                "component": "database",
                "status": "healthy",
                "message": "OK",
                "latency_ms": 5,
            })
            assert result.id is not None
            assert result.status == "healthy"

    def test_run_all_checks(self, app):
        from app.services.health import run_all_checks

        with app.app_context():
            results = run_all_checks()
            assert isinstance(results, list)
            assert len(results) >= 1
