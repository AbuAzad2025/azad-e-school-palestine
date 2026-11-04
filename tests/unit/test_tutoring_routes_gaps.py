"""Branch coverage for tutoring pay/book/rate/payout routes (AZ-P3-xx).

Auth model: real login via POST /auth/login (password ``TestPass123!``).
Service functions the routes import locally are monkeypatched at the
service module (``app.services.tutoring.*``); module-level imports are
patched at the route module (``app.modules.tutoring.routes.*``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import app.modules.tutoring.routes as tmod
import app.services.tutoring as tsvc
from tests.conftest import (
    make_class,
    make_grade,
    make_school,
    make_subject,
    make_tutor_profile,
    make_tutoring_session,
    make_user,
)

PASSWORD = "TestPass123!"


def _email() -> str:
    return f"tutgap-{uuid.uuid4().hex[:10]}@test.com"


def _login(app, role: str, school_id):
    email = _email()
    uid = make_user(app, role=role, school_id=school_id, email=email)
    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    return uid, client


def _tutor_with_profile(app, school_id, *, price_hour=100.0, price_session=None):
    tid = make_user(app, role="teacher", school_id=school_id)
    with app.app_context():
        make_tutor_profile(app, tid, subject="رياضيات", price_hour=price_hour)
        if price_session is not None:
            from app.extensions import db
            from app.models.tutoring import TutorProfile

            prof = TutorProfile.query.filter_by(tutor_id=tid).first()
            prof.price_session = price_session
            db.session.commit()
    return tid


def _school_with_class(app):
    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=1)
    subj = make_subject(app)
    return sid, make_class(app, sid, gid, subj)


def test_book_get_renders_form(app):
    sid, _ = _school_with_class(app)
    tid = _tutor_with_profile(app, sid)
    _, client = _login(app, "student", sid)
    resp = client.get(f"/tutoring/book/{tid}")
    assert resp.status_code == 200


def test_book_post_success_redirects_to_my(app):
    sid, _ = _school_with_class(app)
    tid = _tutor_with_profile(app, sid)
    _, client = _login(app, "student", sid)

    resp = client.post(
        f"/tutoring/book/{tid}",
        data={
            "subject": "رياضيات",
            "preferred_time": "2026-11-20T10:00",
            "mode": "online",
            "note": "ملاحظة",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302, resp.status_code
    assert "/tutoring/my" in (resp.headers.get("Location") or "")


def test_book_post_price_out_of_range_rerenders_200(app):
    sid, _ = _school_with_class(app)
    tid = _tutor_with_profile(app, sid, price_session=100.0)
    _, client = _login(app, "student", sid)

    resp = client.post(
        f"/tutoring/book/{tid}",
        data={
            "subject": "رياضيات",
            "preferred_time": "2026-11-20T10:00",
            "mode": "online",
            "price_quote": "10",
            "note": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200, resp.status_code


def test_book_post_service_error_rerenders_200(app, monkeypatch):
    sid, _ = _school_with_class(app)
    tid = _tutor_with_profile(app, sid)
    _, client = _login(app, "student", sid)
    monkeypatch.setattr(tmod, "create_request", lambda **kw: (None, "فشل إرسال الطلب"))

    resp = client.post(
        f"/tutoring/book/{tid}",
        data={
            "subject": "رياضيات",
            "preferred_time": "2026-11-20T10:00",
            "mode": "online",
            "note": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200, resp.status_code


def test_book_post_as_teacher_redirects_to_index(app):
    sid, _ = _school_with_class(app)
    tid = _tutor_with_profile(app, sid)
    _, client = _login(app, "teacher", sid)

    resp = client.post(
        f"/tutoring/book/{tid}",
        data={
            "subject": "رياضيات",
            "preferred_time": "2026-11-20T10:00",
            "mode": "online",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302


def _seed_session(app, *, status="completed", payment_status="pending"):
    """Create school + tutor + student with KNOWN emails; return (sid, tid, stud_id, sess_id, t_email, s_email)."""
    sid = make_school(app)
    t_email = _email()
    s_email = _email()
    tid = make_user(app, role="teacher", school_id=sid, email=t_email)
    stud_id = make_user(app, role="student", school_id=sid, email=s_email)
    sess_id = make_tutoring_session(
        app,
        tid,
        stud_id,
        status=status,
        price=100.0,
        payment_status=payment_status,
    )
    return sid, tid, stud_id, sess_id, t_email, s_email


def _client_as(app, email):
    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    return client


def test_student_pay_waiting_confirmation_redirects(app, monkeypatch):
    sid, _, _, sess_id, _, s_email = _seed_session(app)
    client = _client_as(app, s_email)
    monkeypatch.setattr(tsvc, "confirm_session_payment_by_student", lambda *a, **kw: ("waiting", None))

    resp = client.post(f"/tutoring/sessions/{sess_id}/pay", follow_redirects=False)
    assert resp.status_code == 302


def test_student_pay_paid_redirects(app, monkeypatch):
    sid, _, _, sess_id, _, s_email = _seed_session(app)
    client = _client_as(app, s_email)
    monkeypatch.setattr(tsvc, "confirm_session_payment_by_student", lambda *a, **kw: ("paid", None))

    resp = client.post(f"/tutoring/sessions/{sess_id}/pay", follow_redirects=False)
    assert resp.status_code == 302


def test_student_pay_error_redirects(app, monkeypatch):
    sid, _, _, sess_id, _, s_email = _seed_session(app)
    client = _client_as(app, s_email)
    monkeypatch.setattr(tsvc, "confirm_session_payment_by_student", lambda *a, **kw: (None, "خطأ"))

    resp = client.post(f"/tutoring/sessions/{sess_id}/pay", follow_redirects=False)
    assert resp.status_code == 302


def test_tutor_pay_confirm_waiting_redirects(app, monkeypatch):
    sid, _, _, sess_id, t_email, _ = _seed_session(app)
    client = _client_as(app, t_email)
    monkeypatch.setattr(tsvc, "confirm_session_payment_by_tutor", lambda *a, **kw: ("waiting", None))

    resp = client.post(f"/tutoring/sessions/{sess_id}/pay-confirm", follow_redirects=False)
    assert resp.status_code == 302


def test_tutor_pay_confirm_paid_redirects(app, monkeypatch):
    sid, _, _, sess_id, t_email, _ = _seed_session(app)
    client = _client_as(app, t_email)
    monkeypatch.setattr(tsvc, "confirm_session_payment_by_tutor", lambda *a, **kw: ("paid", None))

    resp = client.post(f"/tutoring/sessions/{sess_id}/pay-confirm", follow_redirects=False)
    assert resp.status_code == 302


def test_tutor_pay_confirm_error_redirects(app, monkeypatch):
    sid, _, _, sess_id, t_email, _ = _seed_session(app)
    client = _client_as(app, t_email)
    monkeypatch.setattr(tsvc, "confirm_session_payment_by_tutor", lambda *a, **kw: (None, "خطأ"))

    resp = client.post(f"/tutoring/sessions/{sess_id}/pay-confirm", follow_redirects=False)
    assert resp.status_code == 302


def test_tutor_pay_reject_pending_redirects(app, monkeypatch):
    sid, _, _, sess_id, t_email, _ = _seed_session(app)
    client = _client_as(app, t_email)
    monkeypatch.setattr(tsvc, "reject_session_payment_by_tutor", lambda *a, **kw: ("pending", None))

    resp = client.post(f"/tutoring/sessions/{sess_id}/pay-reject", follow_redirects=False)
    assert resp.status_code == 302


def test_tutor_pay_reject_error_redirects(app, monkeypatch):
    sid, _, _, sess_id, t_email, _ = _seed_session(app)
    client = _client_as(app, t_email)
    monkeypatch.setattr(tsvc, "reject_session_payment_by_tutor", lambda *a, **kw: (None, "خطأ"))

    resp = client.post(f"/tutoring/sessions/{sess_id}/pay-reject", follow_redirects=False)
    assert resp.status_code == 302


def test_student_pay_by_tutor_is_forbidden(app):
    sid, _, _, sess_id, t_email, _ = _seed_session(app)
    client = _client_as(app, t_email)

    resp = client.post(f"/tutoring/sessions/{sess_id}/pay")
    assert resp.status_code == 403


def test_tutor_pay_confirm_by_student_is_forbidden(app):
    sid, _, _, sess_id, _, s_email = _seed_session(app)
    client = _client_as(app, s_email)

    resp = client.post(f"/tutoring/sessions/{sess_id}/pay-confirm")
    assert resp.status_code == 403


def test_tutor_pay_reject_by_student_is_forbidden(app):
    sid, _, _, sess_id, _, s_email = _seed_session(app)
    client = _client_as(app, s_email)

    resp = client.post(f"/tutoring/sessions/{sess_id}/pay-reject")
    assert resp.status_code == 403


def test_rate_session_success_redirects(app, monkeypatch):
    sid, _, _, sess_id, _, s_email = _seed_session(app, payment_status="paid")
    client = _client_as(app, s_email)
    monkeypatch.setattr(tmod, "rate_session", lambda *a, **kw: (object(), None))

    resp = client.post(
        f"/tutoring/rate/{sess_id}",
        data={"rating": "4", "comment": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 302, resp.status_code


def test_rate_session_service_error_rerenders_200(app, monkeypatch):
    sid, _, _, sess_id, _, s_email = _seed_session(app, payment_status="paid")
    client = _client_as(app, s_email)
    monkeypatch.setattr(tmod, "rate_session", lambda *a, **kw: (None, "لا يمكن التقييم الآن"))

    resp = client.post(
        f"/tutoring/rate/{sess_id}",
        data={"rating": "3", "comment": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 200, resp.status_code


def test_rate_session_invalid_rating_rerenders_200(app):
    sid, _, _, sess_id, _, s_email = _seed_session(app, payment_status="paid")
    client = _client_as(app, s_email)

    resp = client.post(
        f"/tutoring/rate/{sess_id}",
        data={"rating": "9", "comment": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 200, resp.status_code


def test_rate_session_too_late_redirects_with_danger(app):
    sid = make_school(app)
    tid = make_user(app, role="teacher", school_id=sid)
    stud_email = _email()
    stud_id = make_user(app, role="student", school_id=sid, email=stud_email)
    old = datetime.now(UTC) - timedelta(days=3)
    sess_id = make_tutoring_session(
        app,
        tid,
        stud_id,
        status="completed",
        price=100.0,
        payment_status="paid",
        end_time=old,
    )
    client = app.test_client()
    client.post("/auth/login", data={"email": stud_email, "password": PASSWORD})

    resp = client.post(
        f"/tutoring/rate/{sess_id}",
        data={"rating": "5", "comment": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 302


def test_payout_request_success_redirects(app, monkeypatch):
    sid = make_school(app)
    t_email = _email()
    make_user(app, role="teacher", school_id=sid, email=t_email)
    from app.config.constants import TUTOR_MIN_PAYOUT

    client = app.test_client()
    client.post("/auth/login", data={"email": t_email, "password": PASSWORD})
    monkeypatch.setattr(tmod, "request_payout", lambda *a, **kw: (object(), None))

    resp = client.post(
        "/tutoring/payout-request",
        data={"amount": str(float(TUTOR_MIN_PAYOUT) + 10.0)},
        follow_redirects=False,
    )
    assert resp.status_code == 302


def test_payout_request_service_error_redirects(app, monkeypatch):
    sid = make_school(app)
    t_email = _email()
    make_user(app, role="teacher", school_id=sid, email=t_email)
    from app.config.constants import TUTOR_MIN_PAYOUT

    client = app.test_client()
    client.post("/auth/login", data={"email": t_email, "password": PASSWORD})
    monkeypatch.setattr(tmod, "request_payout", lambda *a, **kw: (None, "لا يوجد رصيد قابل للسحب"))

    resp = client.post(
        "/tutoring/payout-request",
        data={"amount": str(float(TUTOR_MIN_PAYOUT) + 10.0)},
        follow_redirects=False,
    )
    assert resp.status_code == 302


def test_payout_request_below_minimum_no_service_call(app, monkeypatch):
    sid = make_school(app)
    t_email = _email()
    make_user(app, role="teacher", school_id=sid, email=t_email)
    called = []

    def _spy(*a, **kw):
        called.append((a, kw))
        return (object(), None)

    client = app.test_client()
    client.post("/auth/login", data={"email": t_email, "password": PASSWORD})
    monkeypatch.setattr(tmod, "request_payout", _spy)

    resp = client.post(
        "/tutoring/payout-request",
        data={"amount": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert called == []  # لم تُستدعَ الخدمة لأن النموذج رفض القيمة
