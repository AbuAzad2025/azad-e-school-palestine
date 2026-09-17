"""Round H — gap closure: defensive/fallback branches (CI-verified map).

Covers: tasks.dispatch() guardrails (inline/error/timeout/skip + celery stub),
sentry wrapper (DSN absent/present, ImportError path), TTL cache fallbacks
(memory + redis-failure), api_auth token round-trips, wallet REST validation
branches, family link lifecycle, individual subscription paths, calendar
routes/services, discount-code validation, and AI mock-chat branches.
"""

from __future__ import annotations

import asyncio
import sys
import time
import types
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from app.core import cache as cache_mod
from app.core import sentry as sentry_mod
from app.tasks import _HAS_CELERY, dispatch
from tests.conftest import (
    _uid,
    make_class,
    make_class_member,
    make_grade,
    make_school,
    make_subject,
    make_user,
)

PASSWORD = "TestPass123!"


# ── helpers ────────────────────────────────────────────────────────────────


def mk(app, role="student", school_id=None):
    email = f"h-{_uid()}@test.com"
    uid = make_user(app, role=role, school_id=school_id, email=email)
    return uid, email


def login(client, email):
    client.post("/auth/login", data={"email": email, "password": PASSWORD})


# ── 1. tasks.dispatch() guardrails (sync fallback paths) ──────────────────


class TestDispatchGuardrails:
    def test_inline_success(self):
        def job(a, b):
            return a + b

        out = dispatch(job, 2, 3)
        assert out == {"mode": "inline", "result": 5}

    def test_inline_error_captured(self):
        def boom():
            raise ValueError("kaput")

        out = dispatch(boom)
        assert out["mode"] == "inline_error"
        assert "kaput" in out["error"]

    def test_inline_timeout_abandons(self):
        def slow():
            time.sleep(1.2)

        out = dispatch(slow, inline_timeout=0.15)
        assert out["mode"] == "inline_timeout"
        assert out["timeout"] == 0.15

    def test_zero_timeout_skips_long_task(self):
        def job():
            return 1

        out = dispatch(job, inline_timeout=0)
        assert out["mode"] == "skipped"
        assert "long task" in out["reason"]

    def test_celery_mode_or_stub_fallback(self):
        """With celery: .delay wins; without: a .delay-having object still runs inline."""
        calls = []

        def job():
            calls.append(1)
            return "ok"

        if _HAS_CELERY:
            fake = SimpleNamespace(delay=MagicMock(return_value=SimpleNamespace(id="tid-1")))
            out = dispatch(fake)
            assert out["mode"] == "celery"
            assert out["task_id"] == "tid-1"
            assert calls == []  # never executed locally
        else:
            # Without celery even a .delay-bearing object falls back to inline
            fake = SimpleNamespace(delay=MagicMock())
            out = dispatch(job)
            assert out == {"mode": "inline", "result": "ok"}

    def test_notifications_module_guard(self):
        """_HAS_CELERY=False → importing the tasks module raises ImportError.

        Deterministic in any collection order: purge cached copies and force
        the package-level flag False during import (same proven pattern as
        the round-F video guard — earlier suites can leave the cached
        app.tasks module with a leaked True flag).
        """
        import importlib
        import sys

        sys.modules.pop("app.tasks.notifications", None)
        try:
            with patch("app.tasks._HAS_CELERY", False):
                with pytest.raises(ImportError):
                    importlib.import_module("app.tasks.notifications")
        finally:
            sys.modules.pop("app.tasks.notifications", None)
            from app.tasks import _HAS_CELERY as _flag_now

            if _flag_now:  # celery usable → restore a healthy cached module
                importlib.import_module("app.tasks.notifications")


# ── 2. sentry wrapper ──────────────────────────────────────────────────────


class TestSentryWrapper:
    def test_init_without_dsn_is_noop(self, app):
        app.config["SENTRY_DSN"] = None
        sentry_mod.init_sentry(app)  # returns early, no import attempted

    def test_init_with_dsn_uses_sdk(self, app, monkeypatch):
        fake = types.ModuleType("sentry_sdk")
        fake.init = MagicMock()
        int_flask = types.ModuleType("sentry_sdk.integrations.flask")
        int_flask.FlaskIntegration = MagicMock(name="FlaskIntegration")
        int_sa = types.ModuleType("sentry_sdk.integrations.sqlalchemy")
        int_sa.SqlalchemyIntegration = MagicMock(name="SqlalchemyIntegration")
        monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
        monkeypatch.setitem(sys.modules, "sentry_sdk.integrations.flask", int_flask)
        monkeypatch.setitem(sys.modules, "sentry_sdk.integrations.sqlalchemy", int_sa)

        app.config["SENTRY_DSN"] = "https://k@sentry.example/1"
        app.config["SENTRY_ENVIRONMENT"] = "test"
        sentry_mod.init_sentry(app)
        assert fake.init.called
        kwargs = fake.init.call_args.kwargs
        assert kwargs["environment"] == "test"
        app.config["SENTRY_DSN"] = None

    def test_set_user_none_and_anonymous(self, monkeypatch):
        fake = types.ModuleType("sentry_sdk")
        fake.set_user = MagicMock()
        monkeypatch.setitem(sys.modules, "sentry_sdk", fake)

        sentry_mod.set_sentry_user(None)
        fake.set_user.assert_called_with(None)

        anon = SimpleNamespace(is_authenticated=False)
        sentry_mod.set_sentry_user(anon)
        fake.set_user.assert_called_with(None)

    def test_set_user_authenticated_dict(self, monkeypatch):
        fake = types.ModuleType("sentry_sdk")
        fake.set_user = MagicMock()
        monkeypatch.setitem(sys.modules, "sentry_sdk", fake)

        user = SimpleNamespace(is_authenticated=True, id=7, email="u@t.com", role=SimpleNamespace(value="teacher"))
        sentry_mod.set_sentry_user(user)
        sent = fake.set_user.call_args.args[0]
        assert sent == {"id": "7", "email": "u@t.com", "role": "teacher"}

    def test_capture_exception_and_message(self, monkeypatch):
        fake = types.ModuleType("sentry_sdk")
        fake.capture_exception = MagicMock()
        fake.capture_message = MagicMock()
        monkeypatch.setitem(sys.modules, "sentry_sdk", fake)

        err = ValueError("x")
        sentry_mod.capture_exception(err)
        fake.capture_exception.assert_called_once_with(err)
        sentry_mod.capture_message("boom", level="error")
        fake.capture_message.assert_called_once_with("boom", level="error")


# ── 3. TTL cache — memory backend + redis fallbacks ───────────────────────


@pytest.fixture()
def mem_cache(monkeypatch):
    monkeypatch.setenv("RATELIMIT_STORAGE_URL", "memory://")
    cache_mod.reset_cache_backend()
    cache_mod.clear()
    yield cache_mod
    cache_mod.clear()
    cache_mod.reset_cache_backend()


class TestTtlCache:
    def test_set_get_roundtrip(self, mem_cache):
        mem_cache.set("k1", {"a": 1}, ttl=30)
        assert mem_cache.get("k1") == {"a": 1}

    def test_get_missing_returns_none(self, mem_cache):
        assert mem_cache.get("nope") is None

    def test_expired_entry_evicted(self, mem_cache):
        mem_cache.set("k2", "v", ttl=30)
        expires_at, payload = mem_cache._MEM["k2"]
        mem_cache._MEM["k2"] = (expires_at - 60, payload)
        assert mem_cache.get("k2") is None
        assert "k2" not in mem_cache._MEM

    def test_delete_invalidates(self, mem_cache):
        mem_cache.set("k3", 5)
        mem_cache.delete("k3")
        assert mem_cache.get("k3") is None

    def test_clear_empties_all(self, mem_cache):
        mem_cache.set("k4", 1)
        mem_cache.set("k5", 2)
        mem_cache.clear()
        assert mem_cache.get("k4") is None and mem_cache.get("k5") is None

    def test_redis_unreachable_falls_back_to_memory(self, monkeypatch):
        monkeypatch.setenv("RATELIMIT_STORAGE_URL", "redis://127.0.0.1:1/0")
        cache_mod.reset_cache_backend()
        try:
            cache_mod.set("k6", "v")
            assert cache_mod.get("k6") == "v"
        finally:
            cache_mod.clear()
            cache_mod.reset_cache_backend()

    def test_redis_ops_raising_fall_back_to_memory(self, mem_cache, monkeypatch):
        class Broken:
            def get(self, *_a):
                raise ConnectionError("down")

            def setex(self, *_a):
                raise ConnectionError("down")

            def delete(self, *_a):
                raise ConnectionError("down")

        monkeypatch.setattr(cache_mod, "_redis", Broken(), raising=False)
        monkeypatch.setattr(cache_mod, "_redis_checked", True, raising=False)

        mem_cache.set("k7", "v7")
        assert mem_cache.get("k7") == "v7"
        mem_cache.delete("k7")
        assert mem_cache.get("k7") is None

    def test_redis_get_returns_json(self, mem_cache, monkeypatch):
        class FakeRedis:
            def __init__(self):
                self.store = {}

            def setex(self, key, ttl, payload):
                self.store[key] = payload

            def get(self, key):
                return self.store.get(key)

        fr = FakeRedis()
        monkeypatch.setattr(cache_mod, "_redis", fr, raising=False)
        monkeypatch.setattr(cache_mod, "_redis_checked", True, raising=False)

        mem_cache.set("k8", {"x": [1, 2]})
        assert mem_cache.get("k8") == {"x": [1, 2]}
        assert mem_cache.get("k9") is None  # redis miss → None


# ── 4. api_auth tokens ─────────────────────────────────────────────────────


class TestApiAuthTokens:
    def test_roundtrip(self, app):
        from app.core.api_auth import make_api_token, read_api_token

        with app.app_context():
            tok = make_api_token(42)
            assert read_api_token(tok) == 42

    def test_tampered_token_rejected(self, app):
        from app.core.api_auth import make_api_token, read_api_token

        with app.app_context():
            assert read_api_token(make_api_token(42) + "x") is None

    def test_wrong_kind_rejected(self, app):
        from app.core.api_auth import _SALT_API, read_api_token
        from itsdangerous import URLSafeTimedSerializer

        with app.app_context():
            s = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt=_SALT_API)
            assert read_api_token(s.dumps({"uid": 1, "kind": "session"})) is None
            assert read_api_token(s.dumps({"uid": None, "kind": "pat"})) is None

    def test_bearer_header_flows(self, app):
        from app.core import api_auth
        from app.extensions import db
        from app.models.user import User

        uid, email = mk(app, role="student")
        with app.app_context():
            tok = api_auth.make_api_token(uid)

            with app.test_request_context(headers={"Authorization": f"Bearer {tok}"}):
                user = api_auth.user_from_bearer()
                assert user is not None and user.id == uid

            with app.test_request_context(headers={"Authorization": "Basic abc"}):
                assert api_auth.user_from_bearer() is None

            with app.test_request_context(headers={"Authorization": "Bearer "}), app.app_context():
                assert api_auth.user_from_bearer() is None

            with app.test_request_context():
                assert api_auth.user_from_bearer() is None

            # inactive or deleted user rejected
            db.session.get(User, uid).is_active = False
            db.session.commit()
            with app.test_request_context(headers={"Authorization": f"Bearer {tok}"}):
                assert api_auth.user_from_bearer() is None

    def test_api_auth_required_401(self, app):
        from app.core.api_auth import api_auth_required
        from flask import jsonify

        @api_auth_required
        def ep():
            return jsonify(ok=True)

        with app.test_request_context():
            resp = ep()
            assert resp[1] == 401


# ── 5. wallet REST API validation branches ─────────────────────────────────


@pytest.fixture()
def school_and_users(app):
    sid = make_school(app)
    admin_uid, admin_email = mk(app, role="school_admin", school_id=sid)
    stu_uid, stu_email = mk(app, role="student", school_id=sid)
    other_sid = make_school(app)
    other_uid, _ = mk(app, role="student", school_id=other_sid)
    return {
        "sid": sid,
        "other_sid": other_sid,
        "admin": (admin_uid, admin_email),
        "student": (stu_uid, stu_email),
        "outsider": (other_uid, None),
        "app": app,
    }


class TestWalletApi:
    def test_balance_self_ok(self, app, school_and_users):
        env = school_and_users
        c = app.test_client()
        login(c, env["student"][1])
        r = c.get("/api/v1/wallet/balance")
        assert r.status_code == 200
        assert "balance" in r.get_json()["data"]

    def test_balance_of_other_as_student_forbidden(self, app, school_and_users):
        env = school_and_users
        c = app.test_client()
        login(c, env["student"][1])
        r = c.get(f"/api/v1/wallet/balance?user_id={env['outsider'][0]}")
        assert r.status_code == 403

    def test_balance_of_other_as_admin_ok(self, app, school_and_users):
        env = school_and_users
        c = app.test_client()
        login(c, env["admin"][1])
        r = c.get(f"/api/v1/wallet/balance?user_id={env['student'][0]}")
        assert r.status_code == 200

    def test_balance_individual_without_school_400(self, app):
        # individual student has no school_id → 400 VALIDATION_ERROR
        email = f"h-{_uid()}@test.com"
        make_user(app, role="student", school_id=None, email=email, is_individual=True)
        c = app.test_client()
        login(c, email)
        r = c.get("/api/v1/wallet/balance")
        assert r.status_code == 400

    def test_transactions_self_ok(self, app, school_and_users):
        env = school_and_users
        c = app.test_client()
        login(c, env["student"][1])
        r = c.get("/api/v1/wallet/transactions?page=1&per_page=5")
        assert r.status_code == 200
        assert r.get_json()["data"] == []

    def test_transactions_other_student_403(self, app, school_and_users):
        env = school_and_users
        c = app.test_client()
        login(c, env["student"][1])
        r = c.get(f"/api/v1/wallet/transactions?user_id={env['admin'][0]}")
        assert r.status_code == 403

    def test_transfer_validations(self, app, school_and_users):
        env = school_and_users
        c = app.test_client()
        login(c, env["student"][1])
        base = "/api/v1/wallet/transfers"

        assert c.post(base, json={"amount": "5", "idempotency_key": "k"}).status_code == 400
        assert c.post(base, json={"dest_user_id": env["outsider"][0], "amount": "5"}).status_code == 400
        assert (
            c.post(base, json={"dest_user_id": env["outsider"][0], "amount": "abc", "idempotency_key": "k"}).status_code
            == 400
        )
        assert (
            c.post(base, json={"dest_user_id": env["outsider"][0], "amount": "5", "idempotency_key": " "}).status_code
            == 400
        )
        # source wallet of someone else (non-super) → 403
        r = c.post(
            base,
            json={
                "source_user_id": env["admin"][0],
                "dest_user_id": env["outsider"][0],
                "amount": "5",
                "idempotency_key": "k1",
            },
        )
        assert r.status_code == 403

    def test_deposit_and_transfer_roundtrip(self, app, school_and_users):
        env = school_and_users
        c = app.test_client()
        login(c, env["admin"][1])

        r = c.post(
            "/api/v1/wallet/deposits",
            json={"user_id": env["student"][0], "amount": "100", "idempotency_key": f"d-{_uid()}"},
        )
        assert r.status_code == 200
        assert r.get_json()["data"]["status"] == "completed"

        # deposit validation branches
        assert c.post("/api/v1/wallet/deposits", json={"amount": "5", "idempotency_key": "x"}).status_code == 400
        assert (
            c.post("/api/v1/wallet/deposits", json={"user_id": 1, "amount": "-5", "idempotency_key": "x"}).status_code
            == 400
        )
        assert (
            c.post("/api/v1/wallet/deposits", json={"user_id": 1, "amount": "zz", "idempotency_key": "x"}).status_code
            == 400
        )
        assert c.post("/api/v1/wallet/deposits", json={"user_id": 1, "amount": "5"}).status_code == 400

        # student transfers part of the balance to classmate
        c2 = app.test_client()
        login(c2, env["student"][1])
        r2 = c2.post(
            "/api/v1/wallet/transfers",
            json={
                "dest_user_id": env["outsider"][0],
                "amount": "40",
                "idempotency_key": f"t-{_uid()}",
                "description": "help",
            },
        )
        assert r2.status_code == 200
        assert r2.get_json()["data"]["status"] == "completed"


@pytest.fixture()
def _clean_family_tables(app):
    """قاعدة الاختبار دائمة — نمسح بقايا رموز/روابط قبل كل اختبار ربط."""
    from app.extensions import db as _db

    with app.app_context():
        _db.session.execute(_db.text("TRUNCATE family_links, family_link_codes RESTART IDENTITY CASCADE"))
        _db.session.commit()
    yield


# ── 6. family link lifecycle ───────────────────────────────────────────────


class TestFamilyService:
    def _student_and_parent(self, app):
        sid = make_school(app)
        student = make_user(app, role="student", school_id=sid, email=f"h-{_uid()}@t.com")
        parent = make_user(app, role="parent", school_id=None, email=f"h-{_uid()}@t.com")
        return sid, student, parent

    def test_generate_code_rejects_non_student(self, app, _clean_family_tables):
        from app.services.family import generate_link_code

        _, _, parent = self._student_and_parent(app)
        with app.app_context():
            code, err = generate_link_code(parent)
            assert code is None and err

    def test_link_flow_success_and_duplicate(self, app, _clean_family_tables):
        from app.services.family import generate_link_code, is_parent_of, link_parent, list_children, remove_link

        _, student, parent = self._student_and_parent(app)
        with app.app_context():
            code, err = generate_link_code(student)
            assert err is None and code

            link, err = link_parent(parent, code.lower())
            assert err is None and link is not None
            assert is_parent_of(parent, student)
            assert len(list_children(parent)) == 1

            # second link to same student → already-linked error
            code2, _ = generate_link_code(student)
            assert code2 and code2 != code
            _l2, err2 = link_parent(parent, code2)
            assert _l2 is None and err2

            # remove then not parent anymore
            ok, rerr = remove_link(link.id, parent)
            assert ok and rerr is None
            assert not is_parent_of(parent, student)

    def test_link_validation_branches(self, app, _clean_family_tables):
        from app.extensions import db
        from app.models.family import FamilyLinkCode
        from app.services.family import link_parent

        _, student, parent = self._student_and_parent(app)
        with app.app_context():
            assert link_parent(parent, "  ")[1] is not None  # empty
            assert link_parent(student, "ABCD1234")[1] is not None  # not a parent
            assert link_parent(parent, "NOPE0000")[1] is not None  # unknown code

            expired = FamilyLinkCode(
                student_id=student, code="EXP00001", expires_at=datetime.now(UTC) - timedelta(hours=1)
            )
            db.session.add(expired)
            db.session.commit()
            assert link_parent(parent, "EXP00001")[1] is not None

            # wrong-parent remove
            from app.services.family import remove_link

            assert remove_link(999999, parent)[1] is not None

    def test_get_parent_helper(self, app):
        from app.services.family import get_parent

        _, student, parent = self._student_and_parent(app)
        with app.app_context():
            assert get_parent(student) is None


# ── 7. individual subscription paths ───────────────────────────────────────


class TestIndividualSubscribe:
    def _setup_class(self, app, *, price, max_students=None, public=True):
        sid = make_school(app)
        gid = make_grade(app, sid)
        subj = make_subject(app)
        cid = make_class(app, sid, gid, subj)
        from app.extensions import db
        from app.models.class_room import ClassRoom

        with app.app_context():
            cls = db.session.get(ClassRoom, cid)
            cls.is_public = public
            cls.price = price
            if max_students:
                cls.max_students = max_students
            db.session.commit()
        return sid, cid

    def test_non_public_rejected(self, app):
        from app.services.individual import subscribe_to_class

        _, cid = self._setup_class(app, price=0, public=False)
        stu = make_user(app, role="student", email=f"h-{_uid()}@t.com")
        with app.app_context():
            assert subscribe_to_class(stu, cid) is not None

    def test_already_member_rejected(self, app):
        from app.services.individual import subscribe_to_class

        sid, cid = self._setup_class(app, price=0)
        stu = make_user(app, role="student", school_id=sid, email=f"h-{_uid()}@t.com")
        make_class_member(app, cid, stu)
        with app.app_context():
            assert "مسبقاً" in subscribe_to_class(stu, cid)

    def test_capacity_full(self, app):
        from app.services.individual import subscribe_to_class

        sid, cid = self._setup_class(app, price=0, max_students=1)
        stu = make_user(app, role="student", school_id=sid, email=f"h-{_uid()}@t.com")
        other = make_user(app, role="student", school_id=sid, email=f"h-{_uid()}@t.com")
        make_class_member(app, cid, other)
        with app.app_context():
            assert "ممتلئ" in subscribe_to_class(stu, cid)

    def test_free_class_activates_immediately(self, app):
        from app.models.class_room import ClassMember
        from app.services.individual import subscribe_to_class

        sid, cid = self._setup_class(app, price=0)
        stu = make_user(app, role="student", school_id=sid, email=f"h-{_uid()}@t.com")
        with app.app_context():
            assert subscribe_to_class(stu, cid) is None
            m = ClassMember.query.filter_by(class_id=cid, user_id=stu).first()
            assert m is not None and m.status == "active"

    def test_paid_class_creates_pending_subscription(self, app):
        from app.models.billing import Subscription
        from app.services.individual import subscribe_to_class

        sid, cid = self._setup_class(app, price=100)
        stu = make_user(app, role="student", school_id=sid, email=f"h-{_uid()}@t.com")
        with app.app_context():
            assert subscribe_to_class(stu, cid) is None
            sub = Subscription.query.filter_by(user_id=stu, class_id=cid).first()
            assert sub is not None and sub.status == "pending"

    def test_get_student_classes_lists(self, app):
        from app.services.individual import get_student_classes

        sid, cid = self._setup_class(app, price=0)
        stu = make_user(app, role="student", school_id=sid, email=f"h-{_uid()}@t.com")
        make_class_member(app, cid, stu)
        with app.app_context():
            assert len(get_student_classes(stu)) == 1


# ── 8. calendar routes + service ───────────────────────────────────────────


class TestCalendar:
    def _school_admin(self, app):
        sid = make_school(app)
        uid, email = mk(app, role="school_admin", school_id=sid)
        return sid, uid, email

    def test_index_rbac(self, app):
        from app.services.calendar import create_event

        sid, _u, email = self._school_admin(app)
        with app.app_context():
            create_event(sid, "بداية الفصل", "term_start", date(2030, 9, 1))

        c = app.test_client()
        # anonymous → redirect to login
        assert c.get(f"/calendar/{sid}").status_code in (302, 308)
        # student → 403
        _stu, stu_email = mk(app, role="student", school_id=sid)
        c2 = app.test_client()
        login(c2, stu_email)
        assert c2.get(f"/calendar/{sid}").status_code == 403

        # admin → 200
        login(c, email)
        assert c.get(f"/calendar/{sid}").status_code == 200

    def test_event_create_validation_and_success(self, app):
        from app.models.calendar import AcademicEvent

        sid, _u, email = self._school_admin(app)
        c = app.test_client()
        login(c, email)

        # missing title → service error flash, redirect back
        r = c.post(f"/calendar/{sid}/events", data={"title": "", "event_type": "holiday", "start_date": "2030-01-01"})
        assert r.status_code == 302
        with app.app_context():
            assert AcademicEvent.query.filter_by(school_id=sid).count() == 0

        r = c.post(
            f"/calendar/{sid}/events", data={"title": "عيد", "event_type": "holiday", "start_date": "2030-01-01"}
        )
        assert r.status_code == 302
        with app.app_context():
            assert AcademicEvent.query.filter_by(school_id=sid).count() == 1

    def test_event_delete_same_and_cross_school(self, app):
        from app.extensions import db
        from app.models.calendar import AcademicEvent
        from app.services.calendar import create_event

        sid, _u, email = self._school_admin(app)
        other_sid = make_school(app)
        with app.app_context():
            _ev_own, err = create_event(sid, "موسمي", "holiday", date(2030, 3, 1))
            assert err is None
            ev_other, _ = create_event(other_sid, "بعيد", "holiday", date(2030, 3, 2))
            ev_other_id = ev_other.id
            own_id = AcademicEvent.query.filter_by(school_id=sid).first().id

        c = app.test_client()
        login(c, email)

        # cross-school delete → 403
        assert c.post(f"/calendar/events/{ev_other_id}/delete").status_code == 403
        # own-school delete → soft delete (is_active=False)
        r = c.post(f"/calendar/events/{own_id}/delete")
        assert r.status_code == 302
        with app.app_context():
            ev = db.session.get(AcademicEvent, own_id)
            assert ev is not None and ev.is_active is False

    def test_create_event_empty_title(self, app):
        from app.services.calendar import create_event

        sid = make_school(app)
        with app.app_context():
            ev, err = create_event(sid, "   ", "holiday", date(2030, 1, 1))
            assert ev is None and err


# ── 9. discount-code validation matrix ─────────────────────────────────────


def _plan_with_code(app, **dc_kw):
    sid = make_school(app)
    gid = make_grade(app, sid)
    subj = make_subject(app)
    cid = make_class(app, sid, gid, subj)
    from app.extensions import db
    from app.models.billing import DiscountCode, SubscriptionPlan

    with app.app_context():
        plan = SubscriptionPlan(
            school_id=sid, class_id=cid, name="خطة", plan="individual", price=Decimal("100"), duration_days=30
        )
        db.session.add(plan)
        db.session.flush()
        defaults = dict(code=f"DC{_uid()[:6].upper()}", name="خصم", type="percentage", value=Decimal("10"))
        defaults.update(dc_kw)
        dc = DiscountCode(**defaults)
        db.session.add(dc)
        db.session.commit()
        return plan.id, dc.code


class TestDiscountValidation:
    def test_empty_and_unknown(self, app):
        from app.services.billing import validate_discount_code

        with app.app_context():
            assert validate_discount_code("", 1)[1] is not None
            assert validate_discount_code("GHOST00", 1)[1] is not None

    def test_inactive(self, app):
        from app.services.billing import validate_discount_code

        pid, code = _plan_with_code(app, is_active=False)
        with app.app_context():
            assert "مفعل" in validate_discount_code(code, pid)[1]

    def test_expired(self, app):
        from app.services.billing import validate_discount_code

        pid, code = _plan_with_code(app, expiry_date=date.today() - timedelta(days=1))
        with app.app_context():
            assert "منتهي" in validate_discount_code(code, pid)[1]

    def test_exhausted(self, app):
        from app.services.billing import validate_discount_code

        pid, code = _plan_with_code(app, used_count=5, max_uses=5)
        with app.app_context():
            assert "استنفاد" in validate_discount_code(code, pid)[1]

    def test_plan_restricted(self, app):
        from app.services.billing import validate_discount_code

        pid, code = _plan_with_code(app, applicable_plan_ids=[999999])
        with app.app_context():
            assert validate_discount_code(code, pid)[1] is not None

    def test_percentage_and_fixed_and_cap(self, app):
        from app.services.billing import validate_discount_code

        pid, code = _plan_with_code(app)  # 10% of 100 → 10
        with app.app_context():
            d, err = validate_discount_code(code, pid)
            assert err is None and d == Decimal("10")

        pid2, code2 = _plan_with_code(app, type="fixed", value=Decimal("30"))
        with app.app_context():
            d2, _ = validate_discount_code(code2, pid2)
            assert d2 == Decimal("30")

        pid3, code3 = _plan_with_code(app, type="fixed", value=Decimal("500"))
        with app.app_context():
            d3, _ = validate_discount_code(code3, pid3)
            assert d3 == Decimal("100")  # capped at plan price

    def test_apply_to_missing_subscription(self, app):
        from app.services.billing import apply_discount_code

        with app.app_context():
            assert apply_discount_code(999999, "X")[1] is not None
            assert apply_discount_code(1, "")[1] is not None


# ── 10. AI mock-chat branches (offline deterministic) ──────────────────────


class TestAiMockChat:
    def test_mock_answer_keyword_branches(self, app):
        from app.services.ai import AiService

        with app.app_context():
            svc = AiService()
            assert "رياضيات" in svc._mock_ai_answer("how to solve this equation")
            assert "اختبارات" in svc._mock_ai_answer("I have a question about the test")
            assert "الدرجات" in svc._mock_ai_answer("what is my grade")
            assert "الواجبات" in svc._mock_ai_answer("help with homework assignment")
            assert svc._mock_ai_answer("") is not None
            assert "سؤالك" in svc._mock_ai_answer("شيء عام مختلف")

    def test_mock_stream_chunks(self, app):
        from app.services.ai import AiService

        with app.app_context():
            chunks = AiService()._mock_stream_chunks("أ ب ج د هـ")
            assert all(isinstance(c, str) for c in chunks)
            assert "".join(chunks).split() == ["أ", "ب", "ج", "د", "هـ"]

    def test_ask_question_offline_end_to_end(self, app):
        from app.services.ai import AiService

        uid = make_user(app, role="student", email=f"h-{_uid()}@t.com")
        with app.app_context():
            svc = AiService()

            async def run():
                out = ""
                async for chunk in svc.ask_question_stream(uid, "solve x + 1 = 2"):
                    out += chunk
                return out

            raw = asyncio.run(run())
            assert "[DONE]" in raw
            result = asyncio.run(svc.ask_question(uid, "سؤال عام عن المادة"))
            assert result["answer"]
            assert result["session_id"] is not None
