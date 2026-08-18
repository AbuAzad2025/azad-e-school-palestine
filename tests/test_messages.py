"""اختبارات الرسائل المباشرة — نموذج + خدمة + مسارات."""

from tests.conftest import make_school, make_user

# ═══════════════════════════════════════════════════════════════════
# نموذج + خدمة: send_message, inbox, mark_read, unread_count
# ═══════════════════════════════════════════════════════════════════


def test_send_message_success(app):
    from app.services.messages import inbox, send_message, unread_count

    school_id = make_school(app)
    sender_id = make_user(app, role="teacher", school_id=school_id)
    recv_id = make_user(app, role="student", school_id=school_id)
    with app.app_context():
        msg, err = send_message(sender_id, recv_id, "موضوع", "نص الرسالة")
        assert msg is not None
        assert err is None
        assert msg.sender_id == sender_id
        assert msg.recipient_id == recv_id
        assert msg.subject == "موضوع"
        assert msg.is_read is False
        assert unread_count(recv_id) == 1
        msgs = inbox(recv_id)
        assert len(msgs) == 1


def test_send_message_empty_subject(app):
    from app.services.messages import send_message

    school_id = make_school(app)
    sender_id = make_user(app, role="teacher", school_id=school_id)
    recv_id = make_user(app, role="student", school_id=school_id)
    with app.app_context():
        msg, err = send_message(sender_id, recv_id, "", "body")
        assert msg is None
        assert err is not None


def test_send_message_empty_body(app):
    from app.services.messages import send_message

    school_id = make_school(app)
    sender_id = make_user(app, role="teacher", school_id=school_id)
    recv_id = make_user(app, role="student", school_id=school_id)
    with app.app_context():
        msg, err = send_message(sender_id, recv_id, "subject", "  ")
        assert msg is None
        assert err is not None


def test_send_message_self_send(app):
    from app.services.messages import send_message

    school_id = make_school(app)
    uid = make_user(app, role="student", school_id=school_id)
    with app.app_context():
        msg, err = send_message(uid, uid, "subj", "body")
        assert msg is None
        assert err is not None


def test_send_message_nonexistent_recipient(app):
    from app.services.messages import send_message

    school_id = make_school(app)
    sender_id = make_user(app, role="teacher", school_id=school_id)
    with app.app_context():
        msg, err = send_message(sender_id, 99999, "subj", "body")
        assert msg is None
        assert err is not None


def test_send_reply(app):
    from app.services.messages import send_message

    school_id = make_school(app)
    sender_id = make_user(app, role="teacher", school_id=school_id)
    recv_id = make_user(app, role="student", school_id=school_id)
    with app.app_context():
        original, _ = send_message(sender_id, recv_id, "أصل", "مرحبا")
        reply, _ = send_message(recv_id, sender_id, "رد: أصل", "أهلا", parent_message_id=original.id)
        assert reply is not None
        assert reply.parent_message_id == original.id


def test_inbox_excludes_replies(app):
    from app.services.messages import inbox, send_message

    school_id = make_school(app)
    sender_id = make_user(app, role="teacher", school_id=school_id)
    recv_id = make_user(app, role="student", school_id=school_id)
    with app.app_context():
        original, _ = send_message(sender_id, recv_id, "أصل", "مرحبا")
        send_message(recv_id, sender_id, "رد", "أهلا", parent_message_id=original.id)
        msgs = inbox(recv_id)
        assert len(msgs) == 1


def test_mark_read(app):
    from app.services.messages import mark_read, send_message, unread_count

    school_id = make_school(app)
    sender_id = make_user(app, role="teacher", school_id=school_id)
    recv_id = make_user(app, role="student", school_id=school_id)
    with app.app_context():
        msg, _ = send_message(sender_id, recv_id, "subj", "body")
        assert unread_count(recv_id) == 1
        mark_read(msg.id, recv_id)
        assert unread_count(recv_id) == 0


def test_unread_count(app):
    from app.services.messages import send_message, unread_count

    school_id = make_school(app)
    sender_id = make_user(app, role="teacher", school_id=school_id)
    recv_id = make_user(app, role="student", school_id=school_id)
    with app.app_context():
        assert unread_count(recv_id) == 0
        send_message(sender_id, recv_id, "s1", "b1")
        send_message(sender_id, recv_id, "s2", "b2")
        assert unread_count(recv_id) == 2


# ═══════════════════════════════════════════════════════════════════
# مسارات الويب
# ═══════════════════════════════════════════════════════════════════


def test_inbox_view(client, app):
    school_id = make_school(app)
    uid = make_user(app, role="student", school_id=school_id)
    with client.session_transaction() as s:
        s["_user_id"] = str(uid)
    resp = client.get("/messages/inbox")
    assert resp.status_code == 200


def test_compose_page(client, app):
    school_id = make_school(app)
    uid = make_user(app, role="teacher", school_id=school_id)
    with client.session_transaction() as s:
        s["_user_id"] = str(uid)
    resp = client.get("/messages/send")
    assert resp.status_code == 200


def test_send_message_via_route(client, app):
    school_id = make_school(app)
    sender_id = make_user(app, role="teacher", school_id=school_id)
    recv_id = make_user(app, role="student", school_id=school_id)
    with client.session_transaction() as s:
        s["_user_id"] = str(sender_id)
    resp = client.post(
        "/messages/send",
        data={
            "recipient_id": str(recv_id),
            "subject": "اختبار",
            "body": "نص الاختبار",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (302, 200)


def test_thread_view(client, app):
    from app.services.messages import send_message

    school_id = make_school(app)
    sender_id = make_user(app, role="teacher", school_id=school_id)
    recv_id = make_user(app, role="student", school_id=school_id)
    with app.app_context():
        msg, _ = send_message(sender_id, recv_id, "موضوع", "نص")
        msg_id = msg.id
    with client.session_transaction() as s:
        s["_user_id"] = str(recv_id)
    resp = client.get(f"/messages/thread/{msg_id}")
    assert resp.status_code == 200


def test_mark_read_endpoint(client, app):
    from app.services.messages import send_message

    school_id = make_school(app)
    sender_id = make_user(app, role="teacher", school_id=school_id)
    recv_id = make_user(app, role="student", school_id=school_id)
    with app.app_context():
        msg, _ = send_message(sender_id, recv_id, "subj", "body")
        msg_id = msg.id
    with client.session_transaction() as s:
        s["_user_id"] = str(recv_id)
    resp = client.post(f"/messages/mark-read/{msg_id}", content_type="application/json")
    assert resp.status_code == 200
    assert resp.json["ok"] is True


def test_unread_count_endpoint(client, app):
    from app.services.messages import send_message

    school_id = make_school(app)
    sender_id = make_user(app, role="teacher", school_id=school_id)
    recv_id = make_user(app, role="student", school_id=school_id)
    with app.app_context():
        send_message(sender_id, recv_id, "subj", "body")
    with client.session_transaction() as s:
        s["_user_id"] = str(recv_id)
    resp = client.get("/messages/unread-count")
    assert resp.status_code == 200
    assert resp.json["count"] == 1
