# -*- coding: utf-8 -*-
"""Round-4 coverage: remaining gaps in access, attendance, __init__, wallet_api."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from sqlalchemy import text

PASSWORD = "TestPass123!"


def _email():
    return f"r4-{uuid.uuid4().hex[:10]}@test.com"


# ───────────────────────── access.py ─────────────────────────


def test_has_valid_subscription_tolerates_billing_failure(app, monkeypatch):
    from tests.conftest import make_class, make_grade, make_school, make_subject, make_user

    from app.services import access, billing

    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=1)
    subj = make_subject(app)
    tid = make_user(app, role="teacher", school_id=sid)
    cid = make_class(app, sid, gid, subj, teacher_id=tid)
    stud = make_user(app, role="student", school_id=sid)

    def _boom():
        raise RuntimeError("billing broke")

    monkeypatch.setattr(billing, "expire_stale_pending_subscriptions", _boom)
    with app.app_context():
        result = access._has_valid_subscription(stud, cid)
    assert result is False


def test_can_pay_class_non_student_parent_returns_false(app):
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


def test_can_pay_class_lazy_expire_failure_tolerated(app, monkeypatch):
    from tests.conftest import make_class, make_grade, make_school, make_subject, make_user

    from app.extensions import db
    from app.models.class_room import ClassRoom
    from app.models.user import User, UserRole
    from app.services import access, billing

    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=1)
    subj = make_subject(app)
    tid = make_user(app, role="teacher", school_id=sid)
    cid = make_class(app, sid, gid, subj, teacher_id=tid)
    stud = make_user(app, role="student", school_id=sid)

    from app.models.billing import Subscription, SubscriptionPlan
    with app.app_context():
        plan = SubscriptionPlan(school_id=sid, class_id=cid, name="年", plan="annual", price=0.0, is_active=True)
        db.session.add(plan)
        db.session.flush()
        sub = Subscription(user_id=stud, plan_id=plan.id, class_id=cid, price=0.0, status="pending")
        db.session.add(sub)
        db.session.commit()

    def _boom(_sub):
        raise RuntimeError("lazy expire broke")

    monkeypatch.setattr(billing, "lazy_expire_pending_subscription", _boom)
    with app.app_context():
        cls = db.session.get(ClassRoom, cid)
        user = db.session.get(User, stud)
        result = access.can_pay_class(cls, user)
    assert result is True  # lazy expire failed but sub still exists


def test_parent_can_pay_with_active_subscription(app):
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


# ───────────────────────── attendance.py ─────────────────────────


def test_run_absence_alerts_with_date_string(app):
    from app.services import attendance

    with app.app_context():
        result = attendance.run_absence_alerts("2026-11-04")
    assert result >= 0


def test_run_absence_alerts_email_failure_does_not_write_log(app, monkeypatch):
    """send_absence_alert_email raising -> except branch (line 58->53 arc + line 60)."""
    from tests.conftest import make_class, make_family_link, make_grade, make_school, make_subject, make_user

    from app.extensions import db
    from app.models.attendance import AbsenceAlertLog, Attendance
    from app.services import attendance

    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=1)
    subj = make_subject(app)
    cid = make_class(app, sid, gid, subj)
    stu_uid = make_user(app, role="student", school_id=sid)
    parent_uid = make_user(app, role="parent", school_id=sid)
    make_family_link(app, parent_uid, stu_uid)

    with app.app_context():
        att = Attendance(class_id=cid, student_id=stu_uid, date=__import__("datetime").date.today(), status="absent")
        db.session.add(att)
        db.session.commit()

        def _boom(*a, **kw):
            raise RuntimeError("email broke")

        with patch("app.services.email.send_absence_alert_email", _boom):
            result = attendance.run_absence_alerts()
        assert result == 0
        assert db.session.query(AbsenceAlertLog).count() == 0


# ───────────────────────── __init__.py ─────────────────────────


def test_health_without_backup_dir(app):
    """BACKUP_DIR 未设置 -> backup_file None -> warning (489->495 arc)."""
    from app import create_app

    a = create_app()
    a.config["TESTING"] = True
    a.config["WTF_CSRF_ENABLED"] = False
    a.config["TALISMAN_ENABLED"] = False
    a.config.pop("BACKUP_DIR", None)
    client = a.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200


def test_health_with_backup_dir_no_backups(app, monkeypatch, tmp_path):
    """BACKUP_DIR 存在但无备份文件 -> warning (491->495 arc)."""
    from app import create_app

    a = create_app()
    a.config["TESTING"] = True
    a.config["WTF_CSRF_ENABLED"] = False
    a.config["TALISMAN_ENABLED"] = False
    a.config["BACKUP_DIR"] = str(tmp_path)
    client = a.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200


def test_talisman_enabled_csp_missing_placeholder(app, monkeypatch):
    """Talisman enabled, CSP without {CSP_NONCE} placeholder -> 102-112 branch."""
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


def test_wallet_balance_parent_without_school_returns_400(app):
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
    # Request another user's balance without school_id
    resp = client.get("/api/v1/wallet/balance?user_id=999")
    assert resp.status_code in (400, 403)


def test_wallet_transactions_parent_nonlinked_child_returns_403(app):
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


# ───────────────────────── i18n (app/__init__.py) ─────────────────────────


def test_fallback_csp_not_dict(app):
    """CSP non-dict -> empty dict fallback (193-194)."""
    from config import ProductionConfig

    import app as app_module

    class _NonDictCsp:
        TALISMAN_ENABLED = False
        TALISMAN_CONTENT_SECURITY_POLICY = "not a dict"
        WTF_CSRF_ENABLED = False
        SESSION_COOKIE_SECURE = False
        SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "postgresql://localhost:5432/azad_eschool_dev")

    a = app_module.create_app(_NonDictCsp)
    client = a.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200
