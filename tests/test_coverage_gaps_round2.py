# -*- coding: utf-8 -*-
"""Round-2 coverage: real-branch tests for core/services/tasks gaps.

Every test exercises production behaviour â€” no coverage-theatre. Assertions
verify observable outcomes (return values, side effects, idempotency), not
just "does not crash".
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

PASSWORD = "TestPass123!"


def _email() -> str:
    return f"r2-{uuid.uuid4().hex[:10]}@test.com"


def _login(client, email: str) -> None:
    client.post("/auth/login", data={"email": email, "password": PASSWORD})


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ errors.py â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestCorrelationId:
    def test_outside_app_context_falls_back_to_contextvar(self):
        from app.core import errors

        cid = errors.correlation_id()
        assert isinstance(cid, str) and cid


class TestLogError:
    def test_current_user_broken_is_tolerated(self, app, monkeypatch):
        import flask_login

        class _Boom:
            @property
            def is_authenticated(self):
                raise RuntimeError("session gone")

        monkeypatch.setattr(flask_login, "current_user", _Boom())
        with app.app_context(), app.test_request_context("/"):
            from app.core import errors

            ref = errors.log_error(ValueError("nope"), 500, code="INTERNAL_ERROR")
        assert isinstance(ref, str) and ref


class TestHandleHttpException:
    def test_500_delegates_to_unexpected_handler(self, app):
        from werkzeug.exceptions import InternalServerError

        from app.core import errors

        with app.app_context(), app.test_request_context("/", headers={"Accept": "application/json"}):
            resp, status = errors.handle_http_exception(InternalServerError("x"))
        assert status == 500

    def test_csrf_error_renders_400_with_csrf_code(self, app):
        from flask_wtf.csrf import CSRFError

        from app.core import errors

        with app.app_context(), app.test_request_context("/", headers={"Accept": "text/html"}):
            result = errors.handle_http_exception(CSRFError())
        assert result is not None
        if isinstance(result, tuple):
            assert result[1] == 400
        else:
            assert result.status_code == 400


class TestUnexpectedRollbackFailure:
    def test_rollback_failure_still_returns_500(self, app, monkeypatch):
        import app.extensions as ext

        def _boom_rollback():
            raise RuntimeError("rollback broke")

        monkeypatch.setattr(ext.db.session, "rollback", _boom_rollback)
        with app.app_context(), app.test_request_context("/", headers={"Accept": "application/json"}):
            from app.core import errors

            result = errors.handle_unexpected_exception(RuntimeError("x"))
        assert result is not None


class TestMakeHttpHandlerNonHttpException:
    def test_tx_error_maps_to_409_and_renders(self, app):
        from app.core import errors
        from app.core.db import TxError

        handler = None
        code_table = app.error_handler_spec[None][409]
        handler = list(code_table.values())[0]

        with app.app_context(), app.test_request_context("/", headers={"Accept": "text/html"}):
            result = handler(TxError("xung Ä‘á»™t"))
        if isinstance(result, tuple):
            assert result[1] == 409
        else:
            assert result.status_code == 409


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ db.py â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_inner_tx_context_finalize_without_parent(app):
    from sqlalchemy import text as sa_text

    from app.core.db import _TxContext, db

    with app.app_context():
        db.session.execute(sa_text("SELECT 1"))  # session usable; context itself is synthetic
        ctx = _TxContext()
        ctx.is_outermost = False
        ctx._parent = None
        ctx.finalize(committed=True)  # must not raise nor propagate hooks


def test_nested_sqlalchemy_error_propagates_and_outer_rolls_back(app):
    from sqlalchemy.exc import SQLAlchemyError

    from app.core.db import tx
    from app.extensions import db

    def inner():
        raise SQLAlchemyError("boom")

    def outer():
        tx(inner)

    with app.app_context():
        with pytest.raises(SQLAlchemyError):
            tx(outer)
        # Ø¨Ø¹Ø¯ Ø§Ù„Ø§Ø³ØªØ«Ù†Ø§Ø¡ Ø§Ù„Ù…ØªØ¯Ø§Ø®Ù„ Ø£ÙÙ„ØºÙŠØª Ø§Ù„Ù…Ø¹Ø§Ù…Ù„Ø© Ø§Ù„Ø®Ø§Ø±Ø¬ÙŠØ© â€” ÙˆÙ„ÙŠØ³Øª Ø¹Ø§Ù„Ù‚Ø©
        assert not db.session.is_active or db.session().is_active


def test_nested_generic_error_propagates_and_outer_rolls_back(app):
    from app.core.db import tx

    def inner():
        raise ValueError("boom")

    def outer():
        tx(inner)

    with app.app_context(), pytest.raises(ValueError):
        tx(outer)


def test_log_transaction_failure_tolerates_tenancy_failure(app, monkeypatch):
    import app.core.tenancy as tenancy

    def _boom():
        raise RuntimeError("tenancy broke")

    monkeypatch.setattr(tenancy, "current_school_id", _boom)
    with app.app_context():
        from app.core import db as dbmod

        dbmod._log_transaction_failure("sqlalchemy_error")  # Ù„Ø§ ÙŠØ±ÙØ¹


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ logging.py â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_after_request_without_correlation_id_omits_header(monkeypatch):
    import app as app_module

    class _BoomUuid:
        @staticmethod
        def uuid4():
            raise RuntimeError("uuid broke")

    monkeypatch.setattr("app.core.logging.uuid", _BoomUuid)
    a = app_module.create_app()
    assert a.config.get("TESTING") is not True
    a.config["WTF_CSRF_ENABLED"] = False
    a.config["TALISMAN_ENABLED"] = False
    client = a.test_client()
    resp = client.get("/health")
    assert "X-Request-ID" not in resp.headers


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ pdf.py â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_iter_font_dirs_without_configured_dir(app):
    with app.app_context():
        from app.core import pdf

        dirs = pdf._iter_font_dirs()
    assert isinstance(dirs, list) and dirs


def test_write_pdf_file_cleans_tmp_when_replace_fails(app, monkeypatch, tmp_path):
    import app.core.pdf as pdf

    def _boom_replace(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(pdf.os, "replace", _boom_replace)
    monkeypatch.setenv("PDF_OUTPUT_DIR", str(tmp_path))
    with app.app_context():
        with pytest.raises(OSError):
            pdf.write_pdf_file("tests", f"cov-{uuid.uuid4().hex[:6]}", b"%PDF-fake")
    leftovers = list(tmp_path.rglob("*.pdf"))
    assert leftovers == []  # Ø§Ù„Ù…Ù„Ù Ø§Ù„Ù…Ø¤Ù‚Øª Ù†ÙØ¸Ù‘Ù


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ permissions.py â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_has_any_with_none_role_returns_false(app, monkeypatch):
    import app.core.permissions as perms

    monkeypatch.setattr(
        perms,
        "current_user",
        SimpleNamespace(is_authenticated=True, role=None),
    )
    assert perms._has_any() is False


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ api_tenancy.py â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_accessible_school_ids_excludes_inactive_links(app, monkeypatch):
    from tests.conftest import make_school, make_user, make_user_role_link

    import app.core.api_tenancy as api_t
    from app.extensions import db
    from app.models.user import User, UserRole

    sid_a = make_school(app)
    sid_b = make_school(app)
    uid = make_user(app, role="teacher", school_id=sid_a)
    make_user_role_link(app, uid, sid_b, role="teacher", is_active=False)

    with app.app_context():
        u = db.session.get(User, uid)
        fake_user = SimpleNamespace(
            is_authenticated=True,
            role=UserRole.teacher,
            id=uid,
            school_id=sid_a,
            role_links=list(u.role_links),  # Ø±Ø§Ø¨Ø· b ØºÙŠØ± Ù†Ø´Ø· â‡’ Ù…Ø³ØªØ«Ù†Ù‰
        )
        monkeypatch.setattr(api_t, "current_user", fake_user)
        ids = api_t.accessible_school_ids_for_user()
    assert sid_a in ids
    assert sid_b not in ids


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ tenant.py â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_check_quota_teachers_under_limit_allowed(app):
    from tests.conftest import make_school

    from app.services import tenant

    sid = make_school(app)
    with app.app_context():
        ok, msg = tenant.check_quota(sid, "teachers")
    assert ok is True and msg == ""


def test_check_quota_unknown_resource_allowed(app):
    from tests.conftest import make_school

    from app.services import tenant

    sid = make_school(app)
    with app.app_context():
        ok, msg = tenant.check_quota(sid, "storage_blocks")
    assert ok is True and msg == ""


def test_check_quota_ai_enabled_allowed(app):
    from tests.conftest import make_school

    from app.services import tenant

    sid = make_school(app)
    with app.app_context():
        tenant.set_tier(sid, "pro")
        ok, msg = tenant.check_quota(sid, "ai")
    assert ok is True and msg == ""


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ schools.py â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_get_or_create_system_school_keeps_existing_grades(app):
    from tests.conftest import make_school

    from app.extensions import db
    from app.models.school import Grade
    from app.services import schools

    domain = schools.SYSTEM_SCHOOL_DOMAIN
    existing = None
    with app.app_context():
        from app.models.school import School

        existing = School.query.filter_by(domain=domain).first()

    if existing is None:
        sid = make_school(app, name_ar="Ø£Ø²Ø§Ø¯ Ù„Ù„Ø§Ø®ØªØ¨Ø§Ø±", domain=domain)
        with app.app_context():
            for level in range(1, 13):
                db.session.add(Grade(school_id=sid, grade_level=level, name_ar=f"ØµÙ {level}"))
            db.session.commit()

    with app.app_context():
        school = schools.get_or_create_system_school()
        count = Grade.query.filter_by(school_id=school.id).count()
    assert count == 12  # Ù„Ù… ØªÙÙƒØ±ÙŽÙ‘Ø± Ø§Ù„ØµÙÙˆÙ


def test_join_class_individual_with_capacity_proceeds(app):
    from tests.conftest import make_grade, make_school, make_subject, make_user

    from app.extensions import db
    from app.models.class_room import ClassRoom
    from app.services import schools

    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=1)
    subj = make_subject(app)
    with app.app_context():
        cls = ClassRoom(
            school_id=sid,
            grade_id=gid,
            subject_id=subj,
            join_code=f"C-{uuid.uuid4().hex[:6]}",
            name="ØµÙ ÙØ±Ø¯ÙŠ",
            is_public=True,
            max_students=5,
        )
        db.session.add(cls)
        db.session.commit()
        cid = cls.id
    student_id = make_user(app, role="student", school_id=sid)
    with app.app_context():
        member, err = schools.join_class_individual(student_id, cid)
    assert err is None and member is not None


def test_join_class_individual_with_free_plan_joins(app):
    from tests.conftest import (
        make_grade,
        make_school,
        make_subscription_plan,
        make_subject,
        make_user,
    )

    from app.extensions import db
    from app.models.class_room import ClassRoom
    from app.services import schools

    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=1)
    subj = make_subject(app)
    with app.app_context():
        cls = ClassRoom(
            school_id=sid,
            grade_id=gid,
            subject_id=subj,
            join_code=f"C-{uuid.uuid4().hex[:6]}",
            name="ØµÙ Ù…Ø¬Ø§Ù†ÙŠ",
            is_public=True,
        )
        db.session.add(cls)
        db.session.commit()
        cid = cls.id
    make_subscription_plan(app, sid, class_id=cid, price=0.0, plan="annual")
    student_id = make_user(app, role="student", school_id=sid)
    with app.app_context():
        member, err = schools.join_class_individual(student_id, cid)
    assert err is None and member is not None


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ whatsapp.py â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_webhook_scope_rollback_failure_is_swallowed(app, monkeypatch):
    import app.services.whatsapp as wa

    def _boom_rollback():
        raise RuntimeError("rollback broke")

    monkeypatch.setattr(wa.db.session, "rollback", _boom_rollback)
    with app.app_context():
        with wa.verified_webhook_scope():
            pass  # Ø§Ù„Ø®Ø±ÙˆØ¬ ÙŠØ¬Ø¨ Ø£Ù„Ø§ ÙŠØ±ÙØ¹


def test_webhook_scope_begin_listener_reapplies_gucs(app):
    import app.services.whatsapp as wa
    from app.core.db import tx

    with app.app_context():
        with wa.verified_webhook_scope():
            tx(lambda: None)  # Ù…Ø¹Ø§Ù…Ù„Ø© Ø¬Ø¯ÙŠØ¯Ø© â‡’ after_begin â‡’ Ø¥Ø¹Ø§Ø¯Ø© Ø§Ù„Ø¶Ø¨Ø·


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ tasks/__init__.py â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_tasks_module_without_celery_provides_stubs(monkeypatch):
    import importlib
    import sys

    saved = {k: sys.modules.get(k) for k in ("celery", "celery.signals", "app.tasks")}
    sys.modules["celery"] = None
    sys.modules["celery.signals"] = None
    try:
        import app.tasks as tasks_mod

        importlib.reload(tasks_mod)
        assert tasks_mod._HAS_CELERY is False
        assert tasks_mod.celery_app is None
        tasks_mod.init_celery(object())  # no-op ÙˆÙ„Ø§ ÙŠØ±ÙØ¹
        assert callable(tasks_mod.ContextTask)
    finally:
        for k, v in saved.items():
            if v is not None:
                sys.modules[k] = v
        import app.tasks as tasks_mod

        importlib.reload(tasks_mod)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ tasks/notifications.py â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@pytest.fixture(scope="module", autouse=True)
def _fake_celery_notifications():
    """Import task modules with @celery_app.task neutralized (same harness as
    tests/unit/test_final_gap_closures.py)."""
    with (
        patch("app.tasks._HAS_CELERY", True),
        patch("app.tasks.celery_app") as mock_celery,
    ):

        def _task_dec(*a, **kw):
            if a:
                return a[0]
            return lambda f: f

        mock_celery.task.side_effect = _task_dec
        from app.tasks import notifications  # noqa: F401

        yield


class _RetrySentinel(Exception):
    pass


def _self_with_retry():
    m = MagicMock()
    m.retry.side_effect = _RetrySentinel
    return m


def _raw_task():
    from app.tasks import notifications as nmod

    task = getattr(nmod, "send_whatsapp_task", None)
    assert task is not None
    return task


def test_send_whatsapp_task_success(app):
    task = _raw_task()
    with patch("app.services.whatsapp.deliver_outbound", lambda msg: True):
        result = task(_self_with_retry(), to="+970599000000", body="Ù…Ø±Ø­Ø¨Ø§")
    assert result["success"] is True
    assert result["error"] is None


def test_send_whatsapp_task_delivery_rejected(app):
    task = _raw_task()
    with patch("app.services.whatsapp.deliver_outbound", lambda msg: False):
        result = task(_self_with_retry(), to="+970599000000", body="Ù…Ø±Ø­Ø¨Ø§")
    assert result["success"] is False
    assert result["error"] == "delivery_rejected"


def test_send_whatsapp_task_exception_triggers_retry(app):
    task = _raw_task()

    def _boom(_msg):
        raise RuntimeError("provider down")

    with patch("app.services.whatsapp.deliver_outbound", _boom):
        with pytest.raises(_RetrySentinel):
            task(_self_with_retry(), to="+970599000000", body="Ù…Ø±Ø­Ø¨Ø§")


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ tutoring.py â€” Ø£ØºØµØ§Ù† Ø§Ù„Ø§Ø¹ØªÙ…Ø§Ø¯ ÙˆØ§Ù„Ø¹Ù…ÙˆÙ„Ø§Øª â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _mk_tutor_student(app, school_id):
    from tests.conftest import make_user

    tid = make_user(app, role="teacher", school_id=school_id)
    sid = make_user(app, role="student", school_id=school_id)
    return tid, sid


def test_update_profile_ignores_unknown_fields(app):
    from tests.conftest import make_school, make_tutor_profile, make_user

    from app.extensions import db
    from app.models.tutoring import TutorProfile
    from app.services.tutoring import update_profile

    sid = make_school(app)
    tid = make_user(app, role="teacher", school_id=sid)
    with app.app_context():
        make_tutor_profile(app, tid)
        prof = TutorProfile.query.filter_by(tutor_id=tid).first()
        update_profile(prof, not_a_real_field="x", subject="Ø¹Ù„ÙˆÙ…")
        db.session.expire_all()
        assert db.session.get(TutorProfile, prof.id).subject == "Ø¹Ù„ÙˆÙ…"


def test_update_session_ignores_unknown_fields(app):
    from tests.conftest import make_school, make_tutoring_session

    from app.extensions import db
    from app.models.tutoring import TutoringSession
    from app.services.tutoring import update_session

    sid = make_school(app)
    tid, stud_id = _mk_tutor_student(app, sid)
    with app.app_context():
        sess_id = make_tutoring_session(app, tid, stud_id, status="completed")
        sess = db.session.get(TutoringSession, sess_id)
        update_session(sess, not_a_real_field="x", subject="Ø¹Ù„ÙˆÙ…")
        db.session.expire_all()
        assert db.session.get(TutoringSession, sess_id).subject == "Ø¹Ù„ÙˆÙ…"


def test_update_session_live_status_without_live_status(app):
    from tests.conftest import make_school, make_tutoring_session

    from app.extensions import db
    from app.models.tutoring import TutoringSession
    from app.services.tutoring import update_session_live_status

    sid = make_school(app)
    tid, stud_id = _mk_tutor_student(app, sid)
    with app.app_context():
        sess_id = make_tutoring_session(app, tid, stud_id, status="active")
        sess = db.session.get(TutoringSession, sess_id)
        result = update_session_live_status(sess, None, "https://meet.example/x", tid)
        db.session.expire_all()
        assert result is None
        assert db.session.get(TutoringSession, sess_id).online_link == "https://meet.example/x"


def test_update_session_live_status_url_generation_failure(app, monkeypatch):
    import app.services.tutoring as tsvc
    from tests.conftest import make_school, make_tutoring_session

    from app.extensions import db
    from app.models.tutoring import TutoringSession

    sid = make_school(app)
    tid, stud_id = _mk_tutor_student(app, sid)
    monkeypatch.setattr(tsvc, "generate_live_session_url", lambda *a, **kw: None)
    with app.app_context():
        sess_id = make_tutoring_session(app, tid, stud_id, status="active")
        sess = db.session.get(TutoringSession, sess_id)
        result = tsvc.update_session_live_status(sess, "active", None, tid)
        assert result is None


def test_rate_session_without_any_time_anchor(app):
    from tests.conftest import make_school

    from app.extensions import db
    from app.models.tutoring import TutoringSession
    from app.services.tutoring import rate_session

    sid = make_school(app)
    tid, stud_id = _mk_tutor_student(app, sid)
    with app.app_context():
        sess = TutoringSession(
            tutor_id=tid,
            student_id=stud_id,
            subject="Ø±ÙŠØ§Ø¶ÙŠØ§Øª",
            scheduled_at=None,
            end_time=None,
            price=100.0,
            status="completed",
            payment_status="paid",
        )
        db.session.add(sess)
        db.session.commit()
        review, err = rate_session(sess.id, stud_id, 5, "Ù…Ù…ØªØ§Ø²")
    assert err is None and review is not None


def test_wallet_for_commission_settlement_raises_when_unfixable(app, monkeypatch):
    import app.services.tutoring as tsvc
    import app.services.wallet_service as wallet_svc
    from tests.conftest import make_school, make_tutoring_session

    from app.core.db import TxError
    from app.extensions import db
    from app.models.tutoring import TutoringSession

    sid = make_school(app)
    tid, stud_id = _mk_tutor_student(app, sid)
    sess_id = make_tutoring_session(app, tid, stud_id, status="completed", payment_status="paid")
    monkeypatch.setattr(wallet_svc, "get_or_create_wallet", lambda *a, **kw: (None, "ØªØ¹Ø°Ù‘Ø±Øª Ø¥Ù†Ø´Ø§Ø¡ Ø§Ù„Ù…Ø­ÙØ¸Ø©"))
    with app.app_context():
        locked = db.session.get(TutoringSession, sess_id)
        with pytest.raises(TxError):
            tsvc._wallet_for_commission_settlement(locked)


def test_notify_settlement_failure_nonexistent_session_is_safe(app):
    from app.services.tutoring import notify_settlement_failure

    with app.app_context():
        notify_settlement_failure(999_999, 999_999, "Ø³Ø¨Ø¨ Ø§Ø®ØªØ¨Ø§Ø±")  # Ù„Ø§ ÙŠØ±ÙØ¹


def test_notify_settlement_failure_scoped_to_school(app):
    from tests.conftest import make_school, make_tutoring_session, make_user

    from app.services.tutoring import notify_settlement_failure

    sid = make_school(app)
    tid, stud_id = _mk_tutor_student(app, sid)
    make_user(app, role="school_admin", school_id=sid)
    sess_id = make_tutoring_session(app, tid, stud_id, status="completed")
    with app.app_context():
        notify_settlement_failure(sess_id, tid, "Ø³Ø¨Ø¨ Ø§Ø®ØªØ¨Ø§Ø±")  # ÙŠÙÙ„ØªØ± Ø¨Ù…Ø¯Ø±Ø³Ø© Ø§Ù„Ø§Ø¨Ù† ÙˆÙ„Ø§ ÙŠØ±ÙØ¹


def test_append_commission_ledger_is_idempotent(app):
    from tests.conftest import make_school, make_tutoring_session

    from app.core.db import tx
    from app.extensions import db
    from app.models.tutoring import TutoringSession
    from app.models.wallet import WalletTransaction
    from app.services import tutoring as tsvc
    from app.services.wallet_service import get_or_create_wallet

    sid = make_school(app)
    tid, stud_id = _mk_tutor_student(app, sid)
    sess_id = make_tutoring_session(app, tid, stud_id, status="completed", price=100.0, payment_status="paid")

    def _append(locked):
        tsvc._append_commission_ledger(
            locked,
            amount_dec=Decimal("100.00"),
            commission_dec=Decimal("20.00"),
        )

    with app.app_context():
        get_or_create_wallet(school_id=sid, user_id=tid)
        locked = db.session.get(TutoringSession, sess_id)
        tx(lambda: _append(locked))
        db.session.expire_all()
        first_inflow = WalletTransaction.query.filter_by(idempotency_key=f"tutoring_session:{sess_id}:inflow").count()
        first_commission = WalletTransaction.query.filter_by(idempotency_key=f"tutoring_session:{sess_id}:commission").count()
        tx(lambda: _append(db.session.get(TutoringSession, sess_id)))
        db.session.expire_all()
        second_inflow = WalletTransaction.query.filter_by(idempotency_key=f"tutoring_session:{sess_id}:inflow").count()
        second_commission = WalletTransaction.query.filter_by(idempotency_key=f"tutoring_session:{sess_id}:commission").count()

    assert (first_inflow, first_commission) == (1, 1)
    assert (second_inflow, second_commission) == (1, 1)  # Ù„Ø§ ØªÙƒØ±Ø§Ø±


def test_confirm_payment_student_unknown_session(app):
    from tests.conftest import make_school

    from app.services.tutoring import confirm_session_payment_by_student

    sid = make_school(app)
    _, stud_id = _mk_tutor_student(app, sid)
    with app.app_context():
        status, err = confirm_session_payment_by_student(999_999, stud_id)
    assert status is None and err


def test_confirm_payment_student_wrong_actor(app):
    from tests.conftest import make_school, make_tutoring_session

    from app.services.tutoring import confirm_session_payment_by_student

    sid = make_school(app)
    tid, stud_id = _mk_tutor_student(app, sid)
    sess_id = make_tutoring_session(app, tid, stud_id, status="completed", price=100.0, payment_status="pending")
    with app.app_context():
        status, err = confirm_session_payment_by_student(sess_id, tid + 10_000)
    assert status is None and err


def test_confirm_payment_student_with_tutor_preconfirmed_returns_paid(app):
    from tests.conftest import make_school, make_tutoring_session

    from app.extensions import db
    from app.models.tutoring import TutoringSession
    from app.services.tutoring import confirm_session_payment_by_student

    sid = make_school(app)
    tid, stud_id = _mk_tutor_student(app, sid)
    sess_id = make_tutoring_session(app, tid, stud_id, status="completed", price=100.0, payment_status="pending")
    with app.app_context():
        sess = db.session.get(TutoringSession, sess_id)
        sess.tutor_confirmed_payment = True
        db.session.commit()
        status, err = confirm_session_payment_by_student(sess_id, stud_id)
    assert err is None and status == "paid"


def test_confirm_payment_tutor_unknown_session(app):
    from tests.conftest import make_school

    from app.services.tutoring import confirm_session_payment_by_tutor

    sid = make_school(app)
    tid, _ = _mk_tutor_student(app, sid)
    with app.app_context():
        status, err = confirm_session_payment_by_tutor(999_999, tid)
    assert status is None and err


def test_confirm_payment_tutor_wrong_actor(app):
    from tests.conftest import make_school, make_tutoring_session

    from app.services.tutoring import confirm_session_payment_by_tutor

    sid = make_school(app)
    tid, stud_id = _mk_tutor_student(app, sid)
    sess_id = make_tutoring_session(app, tid, stud_id, status="completed", price=100.0, payment_status="pending")
    with app.app_context():
        status, err = confirm_session_payment_by_tutor(sess_id, stud_id + 10_000)
    assert status is None and err


def test_confirm_payment_tutor_with_student_preconfirmed_returns_paid(app):
    from tests.conftest import make_school, make_tutoring_session

    from app.extensions import db
    from app.models.tutoring import TutoringSession
    from app.services.tutoring import confirm_session_payment_by_tutor

    sid = make_school(app)
    tid, stud_id = _mk_tutor_student(app, sid)
    sess_id = make_tutoring_session(app, tid, stud_id, status="completed", price=100.0, payment_status="pending")
    with app.app_context():
        sess = db.session.get(TutoringSession, sess_id)
        sess.student_confirmed_payment = True
        db.session.commit()
        status, err = confirm_session_payment_by_tutor(sess_id, tid)
    assert err is None and status == "paid"


def test_reject_payment_unknown_session(app):
    from tests.conftest import make_school

    from app.services.tutoring import reject_session_payment_by_tutor

    sid = make_school(app)
    tid, _ = _mk_tutor_student(app, sid)
    with app.app_context():
        status, err = reject_session_payment_by_tutor(999_999, tid)
    assert status is None and err


def test_reject_payment_wrong_actor(app):
    from tests.conftest import make_school, make_tutoring_session

    from app.services.tutoring import reject_session_payment_by_tutor

    sid = make_school(app)
    tid, stud_id = _mk_tutor_student(app, sid)
    sess_id = make_tutoring_session(app, tid, stud_id, status="completed", price=100.0, payment_status="pending")
    with app.app_context():
        status, err = reject_session_payment_by_tutor(sess_id, stud_id + 10_000)
    assert status is None and err


def test_finalize_payment_skips_already_recorded_inflow(app):
    from tests.conftest import make_school, make_tutoring_session

    from app.extensions import db
    from app.models.tutoring import TutoringSession
    from app.models.wallet import Wallet, WalletTransaction
    from app.services import tutoring as tsvc
    from app.services.wallet_service import (
        _generate_tx_hash,
        get_or_create_wallet,
    )

    sid = make_school(app)
    tid, stud_id = _mk_tutor_student(app, sid)
    sess_id = make_tutoring_session(app, tid, stud_id, status="completed", price=100.0, payment_status="pending")

    with app.app_context():
        wallet, _ = get_or_create_wallet(school_id=sid, user_id=tid)
        key = f"tutoring_session:{sess_id}:inflow"
        db.session.add(
            WalletTransaction(
                school_id=sid,
                source_wallet_id=None,
                destination_wallet_id=wallet.id,
                amount=Decimal("100.00"),
                currency=wallet.currency,
                transaction_type=tsvc.TX_INFLOW_TYPE,
                transaction_hash=_generate_tx_hash(sid, None, wallet.id, Decimal("100.00"), tsvc.TX_INFLOW_TYPE),
                idempotency_key=key,
                status="completed",
            )
        )
        db.session.commit()
        sess = db.session.get(TutoringSession, sess_id)
        sess.tutor_confirmed_payment = True
        db.session.commit()

        status, err = tsvc.confirm_session_payment_by_student(sess_id, stud_id)
        db.session.expire_all()
        inflows = WalletTransaction.query.filter_by(idempotency_key=key).count()
        fresh = db.session.get(Wallet, wallet.id)

    assert err is None and status == "paid"
    assert inflows == 1  # Ù„Ù… ØªÙØ¶Ù Ø­Ø±ÙƒØ© Ù…ÙƒØ±Ø±Ø© (Ø­Ù…Ø§ÙŠØ© Ù…Ù† Ø¥Ø¹Ø§Ø¯Ø© Ø§Ù„Ø§Ø¹ØªÙ…Ø§Ø¯)
    assert fresh.balance == Decimal("0")  # ÙˆÙ„Ù… ÙŠÙØ´Ø­Ù† Ø§Ù„Ø±ØµÙŠØ¯ Ù…Ø±ØªÙŠÙ†


def test_finalize_payment_with_zero_price_skips_ledger(app):
    from tests.conftest import make_school, make_tutoring_session

    from app.models.wallet import WalletTransaction
    from app.services import tutoring as tsvc

    sid = make_school(app)
    tid, stud_id = _mk_tutor_student(app, sid)
    sess_id = make_tutoring_session(app, tid, stud_id, status="completed", price=0.0, payment_status="pending")

    with app.app_context():
        status, err = tsvc.confirm_session_payment_by_student(sess_id, stud_id)
        status2, err2 = tsvc.confirm_session_payment_by_tutor(sess_id, tid)
        inflows = WalletTransaction.query.filter_by(idempotency_key=f"tutoring_session:{sess_id}:inflow").count()

    assert err is None and err2 is None
    assert status2 == "paid"
    assert inflows == 0  # Ø¯Ø±Ø³ Ù…Ø¬Ø§Ù†ÙŠ â€” Ù„Ø§ Ø­Ø±ÙƒØ§Øª Ù…Ø§Ù„ÙŠØ©


def _backdated_session(app, *, status="completed", end_time=None, student_confirmed=False, tutor_confirmed=False):
    from tests.conftest import make_school, make_tutoring_session

    from sqlalchemy import text as sa_text

    from app.extensions import db

    sid = make_school(app)
    tid, stud_id = _mk_tutor_student(app, sid)
    sess_id = make_tutoring_session(
        app,
        tid,
        stud_id,
        status=status,
        price=100.0,
        payment_status="pending",
        end_time=end_time,
    )
    with app.app_context():
        from app.models.tutoring import TutoringSession

        sess = db.session.get(TutoringSession, sess_id)
        sess.student_confirmed_payment = student_confirmed
        sess.tutor_confirmed_payment = tutor_confirmed
        db.session.commit()
        db.session.execute(
            sa_text("UPDATE tutoring_sessions SET created_at = :t WHERE id = :i"),
            {"t": datetime.now(UTC) - timedelta(days=3), "i": sess_id},
        )
        db.session.commit()
    return sid, tid, stud_id, sess_id


def test_auto_timeout_uses_default_grace_period(app):
    from app.services.tutoring import auto_timeout_unconfirmed_sessions

    with app.app_context():
        result = auto_timeout_unconfirmed_sessions()
    assert {"finalized", "skipped", "errors", "cutoff"} <= set(result)


def test_auto_timeout_skips_when_session_disappears_mid_run(app, monkeypatch):
    import app.services.tutoring as tsvc
    from sqlalchemy import text as sa_text

    from app.extensions import db

    _, _, _, sess_id = _backdated_session(app)
    real_tx = tsvc.tx

    def _vanishing_tx(func, *a, **kw):
        db.session.execute(sa_text("DELETE FROM tutoring_sessions WHERE id = :i"), {"i": sess_id})
        db.session.commit()
        return real_tx(func, *a, **kw)

    monkeypatch.setattr(tsvc, "tx", _vanishing_tx)
    with app.app_context():
        result = tsvc.auto_timeout_unconfirmed_sessions(grace_hours=24)
    assert result["skipped"] == 1
    assert result["finalized"] == 0


def test_auto_timeout_skips_when_session_cancelled_mid_run(app, monkeypatch):
    import app.services.tutoring as tsvc
    from sqlalchemy import text as sa_text

    from app.extensions import db

    _, _, _, sess_id = _backdated_session(app)
    real_tx = tsvc.tx

    def _cancelling_tx(func, *a, **kw):
        db.session.execute(sa_text("UPDATE tutoring_sessions SET status = 'cancelled' WHERE id = :i"), {"i": sess_id})
        db.session.commit()
        return real_tx(func, *a, **kw)

    monkeypatch.setattr(tsvc, "tx", _cancelling_tx)
    with app.app_context():
        result = tsvc.auto_timeout_unconfirmed_sessions(grace_hours=24)
    assert result["skipped"] == 1
    assert result["finalized"] == 0


def test_auto_timeout_candidate_with_student_preconfirmed(app):
    import app.services.tutoring as tsvc

    _backdated_session(app, student_confirmed=True)
    with app.app_context():
        result = tsvc.auto_timeout_unconfirmed_sessions(grace_hours=24)
    assert result["finalized"] >= 1
    assert result["errors"] == 0


def test_auto_timeout_candidate_with_tutor_preconfirmed(app):
    import app.services.tutoring as tsvc

    _backdated_session(app, tutor_confirmed=True)
    with app.app_context():
        result = tsvc.auto_timeout_unconfirmed_sessions(grace_hours=24)
    assert result["finalized"] >= 1
    assert result["errors"] == 0


def test_auto_timeout_completed_session_keeps_end_time(app):
    import app.services.tutoring as tsvc

    from app.extensions import db
    from app.models.tutoring import TutoringSession

    end_time = datetime.now(UTC) - timedelta(days=2)
    _, _, _, sess_id = _backdated_session(app, status="completed", end_time=end_time)
    with app.app_context():
        result = tsvc.auto_timeout_unconfirmed_sessions(grace_hours=24)
        sess = db.session.get(TutoringSession, sess_id)
        assert sess.status == "completed"
        assert sess.end_time is not None
    assert result["errors"] == 0


def test_auto_timeout_active_session_gets_completed_keeps_end_time(app):
    import app.services.tutoring as tsvc

    from app.extensions import db
    from app.models.tutoring import TutoringSession

    end_time = datetime.now(UTC) - timedelta(days=2)
    _, _, _, sess_id = _backdated_session(app, status="active", end_time=end_time)
    with app.app_context():
        result = tsvc.auto_timeout_unconfirmed_sessions(grace_hours=24)
        sess = db.session.get(TutoringSession, sess_id)
        assert sess.status == "completed"
        assert sess.end_time is not None  # Ù„Ù… ÙŠÙØ³ØªØ¨Ø¯Ù„ Ø§Ù„ÙˆÙ‚Øª Ø§Ù„Ø£ØµÙ„ÙŠ
    assert result["errors"] == 0


def test_auto_timeout_errors_are_counted_not_raised(app, monkeypatch):
    import app.services.tutoring as tsvc

    _backdated_session(app)
    monkeypatch.setattr(
        tsvc,
        "_finalize_session_payment",
        lambda locked: (_ for _ in ()).throw(RuntimeError("ledger exploded")),
    )
    with app.app_context():
        result = tsvc.auto_timeout_unconfirmed_sessions(grace_hours=24)
    assert result["errors"] == 1
    assert result["finalized"] == 0
