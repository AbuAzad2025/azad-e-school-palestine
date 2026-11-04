# -*- coding: utf-8 -*-
"""Round-6 coverage: remaining service + module route gaps."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

PASSWORD = "TestPass123!"


def _email():
    return f"r6-{uuid.uuid4().hex[:10]}@test.com"


# ───────────────────────── billing.py ─────────────────────────


def test_expire_stale_pending_tx_failure_covered(app, monkeypatch):
    """Cover lines 221-222 (except in tx(_expire))."""
    from app.services import billing

    def _boom(*a, **kw):
        raise RuntimeError("tx broke")

    monkeypatch.setattr(billing, "tx", _boom)
    with app.app_context():
        result = billing.expire_stale_pending_subscriptions(hours=24)
    assert result == 0


def test_lazy_expire_returns_true_when_expired(app):
    """Cover line 243 (return True when expired)."""
    from tests.conftest import make_class, make_grade, make_school, make_subject, make_user

    from app.extensions import db
    from app.models.billing import Subscription, SubscriptionPlan
    from app.services import billing

    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=1)
    subj = make_subject(app)
    cid = make_class(app, sid, gid, subj)
    stud = make_user(app, role="student", school_id=sid)

    with app.app_context():
        plan = SubscriptionPlan(school_id=sid, class_id=cid, name="年", plan="annual", price=0.0, is_active=True)
        db.session.add(plan)
        db.session.flush()
        sub = Subscription(user_id=stud, plan_id=plan.id, class_id=cid, price=0.0, status="pending")
        db.session.add(sub)
        db.session.commit()
        # Backdate via SQL
        db.session.execute(
            __import__("sqlalchemy").text("UPDATE subscriptions SET created_at = :t WHERE id = :i"),
            {"t": datetime.now(UTC) - timedelta(days=10), "i": sub.id},
        )
        db.session.commit()

        result = billing.lazy_expire_pending_subscription(sub)
    assert result is True


def test_lazy_expire_tx_failure_covered(app, monkeypatch):
    """Cover lines 247-248 (except in tx(_expire_one))."""
    from tests.conftest import make_class, make_grade, make_school, make_subject, make_user

    from app.extensions import db
    from app.models.billing import Subscription, SubscriptionPlan
    from app.services import billing

    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=1)
    subj = make_subject(app)
    cid = make_class(app, sid, gid, subj)
    stud = make_user(app, role="student", school_id=sid)

    with app.app_context():
        plan = SubscriptionPlan(school_id=sid, class_id=cid, name="年", plan="annual", price=0.0, is_active=True)
        db.session.add(plan)
        db.session.flush()
        sub = Subscription(user_id=stud, plan_id=plan.id, class_id=cid, price=0.0, status="pending")
        db.session.add(sub)
        db.session.commit()
        db.session.execute(
            __import__("sqlalchemy").text("UPDATE subscriptions SET created_at = :t WHERE id = :i"),
            {"t": datetime.now(UTC) - timedelta(days=10), "i": sub.id},
        )
        db.session.commit()

        def _boom(*a, **kw):
            raise RuntimeError("tx broke")

        monkeypatch.setattr(billing, "tx", _boom)
        result = billing.lazy_expire_pending_subscription(sub)
    assert result is False


def test_subscription_balances_empty_covered(app):
    """Cover line 417 (return {} when subscription_ids is empty)."""
    from app.services import billing

    with app.app_context():
        result = billing.subscription_balances([])
    assert result == {}


# ───────────────────────── access.py ─────────────────────────


def test_can_pay_class_non_student_parent_returns_false_covered(app):
    """Cover line 159 (return False for non-student/parent)."""
    from tests.conftest import make_class, make_grade, make_school, make_subject, make_user

    from app.extensions import db
    from app.models.class_room import ClassRoom
    from app.services import access

    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=1)
    subj = make_subject(app)
    tid = make_user(app, role="teacher", school_id=sid)
    cid = make_class(app, sid, gid, subj, teacher_id=tid)
    with app.app_context():
        cls = db.session.get(ClassRoom, cid)
        teacher = db.session.get(__import__("app.models.user", fromlist=["User"]).User, tid)
        assert access.can_pay_class(cls, teacher) is False


# ───────────────────────── __init__.py ─────────────────────────


def test_talisman_enabled_csp_without_placeholder(app):
    """Cover lines 102-104 (Talisman enabled, CSP without {CSP_NONCE})."""
    from config import ProductionConfig

    import app as app_module

    class _NoPlaceholder:
        TALISMAN_ENABLED = True
        TALISMAN_FORCE_HTTPS = False
        TALISMAN_STRICT_TRANSPORT_SECURITY = False
        TALISMAN_STRICT_TRANSPORT_SECURITY_MAX_AGE = 31536000
        WTF_CSRF_ENABLED = False
        SESSION_COOKIE_SECURE = False
        SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "postgresql://localhost:5432/azad_eschool_dev")
        TALISMAN_CONTENT_SECURITY_POLICY = {
            "default-src": "'self'",
            "frame-ancestors": "'none'",
        }

    a = app_module.create_app(_NoPlaceholder)
    client = a.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200


# ───────────────────────── wallet_api.py ─────────────────────────


def test_wallet_balance_parent_without_school(app):
    """Cover lines 105,107-110 (parent without school_id -> 400)."""
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


def test_wallet_transactions_parent_nonlinked_child(app):
    """Cover lines 160-165 (parent requesting non-linked child's transactions -> 403)."""
    from tests.conftest import make_school, make_user

    from app.extensions import db
    from app.models.user import User

    sid_a = make_school(app)
    sid_b = make_school(app)
    parent = make_user(app, role="parent", school_id=sid_a)
    child_b = make_user(app, role="student", school_id=sid_b)
    email = None
    with app.app_context():
        email = db.session.get(User, parent).email

    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    resp = client.get(f"/api/v1/wallet/transactions?user_id={child_b}")
    assert resp.status_code == 403


# ───────────────────────── errors.py ─────────────────────────


def test_make_http_handler_non_http_matching_status_covered(app):
    """Cover lines 535,538 (non-HTTP exception with matching status -> json/template)."""
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


# ───────────────────────── tutoring.py ─────────────────────────


def test_confirm_payment_tutor_waiting(app):
    """Cover line 883 (return 'waiting' when student hasn't confirmed)."""
    from tests.conftest import make_school, make_tutoring_session, make_user

    from app.services.tutoring import confirm_session_payment_by_tutor

    sid = make_school(app)
    tid = make_user(app, role="teacher", school_id=sid)
    stud_id = make_user(app, role="student", school_id=sid)
    sess_id = make_tutoring_session(app, tid, stud_id, status="completed", price=100.0, payment_status="pending")

    with app.app_context():
        status, err = confirm_session_payment_by_tutor(sess_id, tid)
    assert status == "waiting" and err is None


# ───────────────────────── access.py ─────────────────────────


def test_parent_can_pay_with_subscription(app):
    """Cover lines 192-201 (has_subscription True -> return True)."""
    from tests.conftest import make_class, make_grade, make_school, make_subject, make_user

    from app.extensions import db
    from app.models.billing import Subscription, SubscriptionPlan
    from app.models.class_room import ClassRoom
    from app.models.family import FamilyLink
    from app.models.user import User
    from app.services import access

    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=1)
    subj = make_subject(app)
    tid = make_user(app, role="teacher", school_id=sid)
    cid = make_class(app, sid, gid, subj, teacher_id=tid)
    parent = make_user(app, role="parent", school_id=sid)
    student = make_user(app, role="student", school_id=sid)

    with app.app_context():
        link = FamilyLink(parent_id=parent, student_id=student, status="active")
        db.session.add(link)
        plan = SubscriptionPlan(school_id=sid, class_id=cid, name="年", plan="annual", price=0.0, is_active=True)
        db.session.add(plan)
        db.session.flush()
        sub = Subscription(user_id=student, plan_id=plan.id, class_id=cid, price=0.0, status="active")
        db.session.add(sub)
        db.session.commit()

        cls = db.session.get(ClassRoom, cid)
        user = db.session.get(User, parent)
        assert access.can_pay_class(cls, user) is True
