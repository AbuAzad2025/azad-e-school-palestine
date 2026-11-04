# -*- coding: utf-8 -*-
"""Round-8 coverage: remaining service + module route + __init__ gaps."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

PASSWORD = "TestPass123!"


def _email():
    return f"r8-{uuid.uuid4().hex[:10]}@test.com"


# ───────────────────────── services/payments.py ─────────────────────────


def test_validate_lesson_access_school_admin_other_school_covered2(app):
    from tests.conftest import make_class, make_grade, make_lesson, make_school, make_subject, make_user

    from app.services.video_service import validate_lesson_access

    sid_a = make_school(app)
    sid_b = make_school(app)
    gid = make_grade(app, sid_a, grade_level=1)
    subj = make_subject(app)
    cid = make_class(app, sid_a, gid, subj)
    lesson_id = make_lesson(app, cid)
    admin_b = make_user(app, role="school_admin", school_id=sid_b)

    with app.app_context():
        ok, err = validate_lesson_access(admin_b, sid_a, lesson_id)
    assert ok is False


# ───────────────────────── __init__.py ─────────────────────────


def test_talisman_enabled_csp_with_placeholder(app):
    """Talisman enabled with {CSP_NONCE} in CSP -> if branch (102-104)."""
    from config import ProductionConfig

    import app as app_module

    class _WithPlaceholder:
        TALISMAN_ENABLED = True
        TALISMAN_FORCE_HTTPS = False
        TALISMAN_STRICT_TRANSPORT_SECURITY = False
        TALISMAN_STRICT_TRANSPORT_SECURITY_MAX_AGE = 31536000
        WTF_CSRF_ENABLED = False
        SESSION_COOKIE_SECURE = False
        SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "postgresql://localhost:5432/azad_eschool_dev")
        TALISMAN_CONTENT_SECURITY_POLICY = {
            "default-src": "'self'",
            "script-src": "'self' 'nonce-{CSP_NONCE}'",
            "style-src": "'self' 'nonce-{CSP_NONCE}'",
            "frame-ancestors": "'none'",
        }

    a = app_module.create_app(_WithPlaceholder)
    client = a.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200


# ───────────────────────── core/errors.py ─────────────────────────


def test_make_http_handler_non_http_matching_status_covered3(app):
    from app.core import errors
    from app.core.db import TxError

    handler = None
    code_table = app.error_handler_spec[None][409]
    handler = list(code_table.values())[0]

    with app.app_context(), app.test_request_context("/", headers={"Accept": "application/json"}):
        result = handler(TxError("conflict"))
    if isinstance(result, tuple):
        assert result[1] == 409
    else:
        assert result.status_code == 409


# ───────────────────────── wallet_api.py ─────────────────────────


def test_wallet_balance_parent_without_school_covered2(app):
    from tests.conftest import make_school, make_user

    from app.extensions import db
    from app.models.user import User

    sid = make_school(app)
    parent = make_user(app, role="parent", school_id=None)
    email = None
    with app.app_context():
        email = db.session.get(User, parent).email

    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    resp = client.get("/api/v1/wallet/balance?user_id=999")
    assert resp.status_code in (400, 403)


# ───────────────────────── tutoring/routes.py ─────────────────────────


def test_pay_confirm_by_non_participant_403_covered(app):
    from tests.conftest import make_school, make_tutoring_session, make_user

    sid = make_school(app)
    tid = make_user(app, role="teacher", school_id=sid)
    stud_id = make_user(app, role="student", school_id=sid)
    other = make_user(app, role="student", school_id=sid)
    sess_id = make_tutoring_session(app, tid, stud_id, status="completed", price=100.0, payment_status="pending")

    other_email = None
    with app.app_context():
        from app.extensions import db
        from app.models.user import User

        other_email = db.session.get(User, other).email

    client = app.test_client()
    client.post("/auth/login", data={"email": other_email, "password": PASSWORD})
    resp = client.post(f"/tutoring/sessions/{sess_id}/pay-confirm", follow_redirects=False)
    assert resp.status_code == 403


def test_pay_reject_by_non_participant_403_covered(app):
    from tests.conftest import make_school, make_tutoring_session, make_user

    sid = make_school(app)
    tid = make_user(app, role="teacher", school_id=sid)
    stud_id = make_user(app, role="student", school_id=sid)
    other = make_user(app, role="student", school_id=sid)
    sess_id = make_tutoring_session(app, tid, stud_id, status="completed", price=100.0, payment_status="pending")

    other_email = None
    with app.app_context():
        from app.extensions import db
        from app.models.user import User

        other_email = db.session.get(User, other).email

    client = app.test_client()
    client.post("/auth/login", data={"email": other_email, "password": PASSWORD})
    resp = client.post(f"/tutoring/sessions/{sess_id}/pay-reject", follow_redirects=False)
    assert resp.status_code == 403


# ───────────────────────── services/tutoring.py ─────────────────────────


def test_confirm_payment_tutor_waiting_covered2(app):
    from tests.conftest import make_school, make_tutoring_session, make_user

    from app.services.tutoring import confirm_session_payment_by_tutor

    sid = make_school(app)
    tid = make_user(app, role="teacher", school_id=sid)
    stud_id = make_user(app, role="student", school_id=sid)
    sess_id = make_tutoring_session(app, tid, stud_id, status="completed", price=100.0, payment_status="pending")

    with app.app_context():
        status, err = confirm_session_payment_by_tutor(sess_id, tid)
    assert status == "waiting" and err is None
