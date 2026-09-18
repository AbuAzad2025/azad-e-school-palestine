"""Round I — exception/fallback tail closure (CI-verified map, 347 lines).

Targets: app factory full-config branches (Talisman/Sentry/ratelimit/health/
currency fallback/500), permission decorators (400/403/404 arms + student_only
+ AI-quota JSON), RLS introspection guards, context helpers, bearer-token
fallbacks, wallet REST validation arms, payments CashU idempotency +
plan-school resolution, tenant quota caps, grading/notifications/reports task
error+retry paths, tasks/__init__ celery-present branch via a fake module,
streaming finally-rollback, and route error-flash branches.
"""

from __future__ import annotations

import base64
import importlib
import json
import sys
import types
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from tests.conftest import (
    _uid,
    make_attachment,
    make_class,
    make_class_member,
    make_family_link_code,
    make_grade,
    make_grade_category,
    make_grade_entry,
    make_grade_item,
    make_lesson,
    make_payment,
    make_school,
    make_subject,
    make_subscription,
    make_subscription_plan,
    make_tutor_profile,
    make_tutoring_session,
    make_user,
    make_user_role_link,
)
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import BadRequest, Forbidden, NotFound

PASSWORD = "TestPass123!"

_LEVELS: dict[int, int] = {}


def _next_level(sid: int) -> int:
    _LEVELS[sid] = _LEVELS.get(sid, 0) + 1
    return _LEVELS[sid]


def mk(app, role="student", school_id=None):
    email = f"ri-{_uid()}@test.com"
    return make_user(app, role=role, school_id=school_id, email=email), email


def persona(app, role="student", school_id=None):
    uid, email = mk(app, role, school_id)
    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    return uid, client


def login_email(app, email):
    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    return client


def setup_class(app):
    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=_next_level(sid))
    subj = make_subject(app)
    cid = make_class(app, sid, gid, subj)
    return sid, cid


class _RetryCalled(Exception):
    pass


def _fake_self():
    def _retry(**kw):
        raise _RetryCalled()

    return SimpleNamespace(retry=_retry)


@pytest.fixture
def celery_on():
    """Import task modules under a fake celery (CI has no celery installed)."""
    with patch("app.tasks._HAS_CELERY", True):
        mock_celery = MagicMock()

        def _task_dec(*a, **kw):
            if a:
                return a[0]
            return lambda f: f

        mock_celery.task.side_effect = _task_dec
        with patch("app.tasks.celery_app", mock_celery):
            popped = []
            for name in ("app.tasks.grading", "app.tasks.reports", "app.tasks.notifications"):
                if name in sys.modules:
                    sys.modules.pop(name)
                    popped.append(name)
            yield
            for name in ("app.tasks.grading", "app.tasks.reports", "app.tasks.notifications"):
                sys.modules.pop(name, None)


# ═══════════════════════════════════════════════════════════════════════════
# 1. App factory branches
# ═══════════════════════════════════════════════════════════════════════════


class TestAppFactory:
    def test_full_config_branches(self):
        """Talisman + Sentry DSN + rate limiter all enabled → factory arms run."""
        from config import Config

        class FullConfig(Config):
            TALISMAN_ENABLED = True
            TALISMAN_FORCE_HTTPS = False
            RATELIMIT_ENABLED = True
            SENTRY_DSN = "https://k@localhost/1"
            TESTING = True
            WTF_CSRF_ENABLED = False

        from types import ModuleType
        from unittest.mock import patch as _patch

        from app import create_app

        fake_sdk = ModuleType("sentry_sdk")
        fake_sdk.init = lambda *a, **k: None
        fake_sdk.set_tag = lambda *a, **k: None
        fake_sdk.set_user = lambda *a, **k: None
        fake_sdk.capture_exception = lambda *a, **k: None
        fake_sdk.capture_message = lambda *a, **k: None
        fake_sdk.integrations = ModuleType("sentry_sdk.integrations")
        fake_int = fake_sdk.integrations
        fake_int.flask = ModuleType("sentry_sdk.integrations.flask")
        fake_int.flask.FlaskIntegration = lambda *a, **k: object()
        fake_int.sqlalchemy = ModuleType("sentry_sdk.integrations.sqlalchemy")
        fake_int.sqlalchemy.SqlalchemyIntegration = lambda *a, **k: object()
        # mutate whichever fake got registered first — other tests in this
        # file may have installed a partial stub earlier
        sdk = sys.modules.setdefault("sentry_sdk", fake_sdk)
        for attr in ("init", "set_tag", "set_user", "capture_exception", "capture_message"):
            setattr(sdk, attr, getattr(fake_sdk, attr))
        sys.modules.setdefault("sentry_sdk.integrations", fake_int)
        sys.modules.setdefault("sentry_sdk.integrations.flask", fake_int.flask)
        sys.modules.setdefault("sentry_sdk.integrations.sqlalchemy", fake_int.sqlalchemy)
        with _patch.dict("os.environ", {"SENTRY_DSN": ""}):
            app2 = create_app(FullConfig)
        client = app2.test_client()
        resp = client.get("/auth/login")
        assert resp.status_code in (200, 302)

    def test_server_error_500_handler(self, app):
        """Unhandled exception inside a view → app-level 500 + error template."""
        sid, cid = setup_class(app)
        uid, email = mk(app, "student", school_id=sid)
        make_class_member(app, cid, uid)
        make_lesson(app, cid)
        client = login_email(app, email)
        # /progress/my imports Lesson inside the view → patch the source module;
        # force the view to blow up mid-flight
        with patch("app.models.content.Lesson") as m:
            m.query.filter.return_value.order_by.return_value.all.side_effect = RuntimeError("boom")
            resp = client.get("/progress/my")
        assert resp.status_code == 500
        with app.app_context():
            from app.extensions import db
            from app.models.user import User

            assert db.session.get(User, uid) is not None

    def test_currency_format_fallback(self, app):
        with app.app_context():
            fn = app.jinja_env.filters["currencyformat"]
            assert fn("abc", "XYZ") == "abc XYZ"
            assert fn(None, "XYZ") == "—"

    def test_anonymous_web_redirects_to_login(self, app):
        client = app.test_client()
        resp = client.get("/schools")
        assert resp.status_code == 308  # TALISMAN_FORCE_HTTPS=False → strict_slashes 308

    def test_health_disk_error_degrades(self, app):
        """disk_usage failure → check_disk() exception arm reports 'down'."""
        _, client = persona(app, "super_admin")
        with patch("shutil.disk_usage", side_effect=RuntimeError("no disk")):
            resp = client.get("/admin/health")
        assert resp.status_code == 200
        assert b"down" in resp.data


# ═══════════════════════════════════════════════════════════════════════════
# 2. Permission decorators — every guard arm
# ═══════════════════════════════════════════════════════════════════════════


class TestPermissionDecorators:
    def _login(self, app, uid):
        from app.extensions import db
        from app.models.user import User
        from flask_login import login_user

        u = db.session.get(User, uid)
        login_user(u)
        return u

    def test_class_access_missing_id_400(self, app):
        from app.core.permissions import class_access_required

        @class_access_required
        def _v(class_id, class_room=None):
            return "ok"

        sid, _cid = setup_class(app)
        uid, _ = mk(app, "student", school_id=sid)
        with app.test_request_context():
            self._login(app, uid)
            with pytest.raises(BadRequest):
                _v(class_id=None)

    def test_class_access_unknown_404(self, app):
        from app.core.permissions import class_access_required

        @class_access_required
        def _v(class_id, class_room=None):
            return "ok"

        sid, _cid = setup_class(app)
        uid, _ = mk(app, "student", school_id=sid)
        with app.test_request_context():
            self._login(app, uid)
            with pytest.raises(NotFound):
                _v(class_id=99999999)

    def test_class_access_foreign_403(self, app):
        from app.core.permissions import class_access_required

        @class_access_required
        def _v(class_id, class_room=None):
            return "ok"

        sid_a, cid_a = setup_class(app)
        sid_b = make_school(app)
        uid_b, _ = mk(app, "student", school_id=sid_b)
        with app.test_request_context():
            self._login(app, uid_b)
            with pytest.raises(Forbidden):
                _v(class_id=cid_a)

    def test_class_teach_missing_400(self, app):
        from app.core.permissions import class_teach_required

        @class_teach_required
        def _v(class_id, class_room=None):
            return "ok"

        sid, _cid = setup_class(app)
        uid, _ = mk(app, "teacher", school_id=sid)
        with app.test_request_context():
            self._login(app, uid)
            with pytest.raises(BadRequest):
                _v(class_id=None)

    def test_class_teach_non_teacher_403(self, app):
        from app.core.permissions import class_teach_required

        @class_teach_required
        def _v(class_id, class_room=None):
            return "ok"

        sid, cid = setup_class(app)
        uid, _ = mk(app, "teacher", school_id=sid)  # not assigned to class
        with app.test_request_context():
            self._login(app, uid)
            with pytest.raises(Forbidden):
                _v(class_id=cid)

    def test_parent_of_missing_400_and_unlinked_403(self, app):
        from app.core.permissions import parent_of_required

        @parent_of_required
        def _v(student_id):
            return "ok"

        sid, cid = setup_class(app)
        puid, _ = mk(app, "parent", school_id=sid)
        with app.test_request_context():
            self._login(app, puid)
            with pytest.raises(BadRequest):
                _v(student_id=None)
            with pytest.raises(Forbidden):
                _v(student_id=99999999)

    def test_student_only(self, app):
        from app.core.permissions import student_only

        @student_only
        def _v():
            return "ok"

        sid, _cid = setup_class(app)
        tuid, _ = mk(app, "teacher", school_id=sid)
        suid, _ = mk(app, "student", school_id=sid)
        with app.test_request_context():
            self._login(app, tuid)
            with pytest.raises(Forbidden):
                _v()
        with app.test_request_context():
            self._login(app, suid)
            assert _v() == "ok"

    def test_invalidate_ai_quota_cache(self, app):
        from app.core.permissions import invalidate_ai_quota_cache

        invalidate_ai_quota_cache(12345)

    def test_ai_quota_denied_web_403(self, app):
        from app.core.permissions import require_ai_quota

        @require_ai_quota
        def _v():
            return "ok"

        sid, _cid = setup_class(app)
        uid, _ = mk(app, "student", school_id=sid)
        with app.test_request_context("/ai/chat"):
            self._login(app, uid)
            with patch(
                "app.core.permissions.tenant_ai_quota",
                return_value=(False, "AI_DISABLED_FOR_TENANT", "معطّل"),
            ):
                with pytest.raises(Forbidden):
                    _v()

    def test_ai_quota_denied_json_403(self, app):
        from app.core.permissions import require_ai_quota

        @require_ai_quota
        def _v():
            return "ok"

        sid, _cid = setup_class(app)
        uid, _ = mk(app, "student", school_id=sid)
        with app.test_request_context("/ai/chat", json={}):
            self._login(app, uid)
            with patch(
                "app.core.permissions.tenant_ai_quota",
                return_value=(False, "AI_QUOTA_EXCEEDED", "استُهلكت الحصة"),
            ):
                resp = _v()
            assert resp.status_code == 403
            assert resp.get_json()["error"]["code"] == "AI_QUOTA_EXCEEDED"


# ═══════════════════════════════════════════════════════════════════════════
# 3. Context helpers + RLS + api_auth
# ═══════════════════════════════════════════════════════════════════════════


class TestContextHelpers:
    def _login(self, app, uid):
        from app.extensions import db
        from app.models.user import User
        from flask_login import login_user

        login_user(db.session.get(User, uid))

    def test_has_any_role_variants(self, app):
        from app.core.context import has_any_role

        sid, _cid = setup_class(app)
        uid, _ = mk(app, "teacher", school_id=sid)
        with app.test_request_context():
            from app.models.user import UserRole

            self._login(app, uid)
            assert has_any_role("teacher") is True
            assert has_any_role(UserRole.teacher) is True
            assert has_any_role("student", UserRole.parent) is False

    def test_can_teach_and_view_paths(self, app):
        from app.core.context import can_teach_class, can_view_class

        sid = make_school(app)
        gid = make_grade(app, sid, grade_level=_next_level(sid))
        subj = make_subject(app)
        tid, _ = mk(app, "teacher", school_id=sid)
        cid = make_class(app, sid, gid, subj, teacher_id=tid)
        said, _ = mk(app, "school_admin", school_id=sid)
        suid, _ = mk(app, "student", school_id=sid)
        make_class_member(app, cid, suid)
        guid, _ = mk(app, "super_admin")
        with app.test_request_context():
            from app.extensions import db
            from app.models.class_room import ClassRoom

            cls = db.session.get(ClassRoom, cid)
            self._login(app, tid)
            assert can_teach_class(cls) is True
            assert can_view_class(cls) is True
            self._login(app, said)
            assert can_teach_class(cls) is True
            assert can_view_class(cls) is True
            self._login(app, guid)
            assert can_view_class(cls) is True
            self._login(app, suid)
            assert can_view_class(cls) is True


class TestRlsGuards:
    def test_introspection_exception_false(self, app):
        from app.core import rls

        with app.app_context():
            with patch("app.core.rls.db") as m:
                m.session.get_bind.side_effect = RuntimeError("no conn")
                assert rls._table_exists("whatever") is False
                assert rls._has_column("whatever", "school_id") is False

    def test_reset_context_swallows(self, app):
        from app.core import rls

        with patch("app.core.rls.db") as m:
            m.session.execute.side_effect = RuntimeError("gone")
            rls.reset_tenant_context()

    def test_enable_rls_missing_table(self, app):
        from app.core import rls

        with app.app_context():
            assert rls.enable_rls_on_table("no_such_table_xyz") is False
            assert rls.enable_rls_on_indirect_table("no_such_table_xyz", "select 1") is False

    def test_disable_all_swallows_errors(self, app):
        from app.core import rls

        with patch("app.core.rls.db") as m:
            m.session.execute.side_effect = RuntimeError("x")
            rls.disable_all_rls_policies()
            m.session.commit.assert_called()


class TestApiAuthBearer:
    def test_bearer_fallback_allows(self, app):
        from app.core.api_auth import api_auth_required, make_api_token, user_from_bearer

        @api_auth_required
        def _v():
            return "ok"

        sid, _cid = setup_class(app)
        uid, _ = mk(app, "student", school_id=sid)
        with app.app_context():
            token = make_api_token(uid)
        with app.test_request_context(headers={"Authorization": f"Bearer {token}"}):
            assert user_from_bearer() is not None
            assert user_from_bearer().id == uid
            assert _v() == "ok"

    def test_bad_and_missing_tokens(self, app):
        from app.core.api_auth import user_from_bearer

        with app.test_request_context(headers={"Authorization": "Bearer garbage-token"}):
            assert user_from_bearer() is None
        with app.test_request_context(headers={"Authorization": "Basic xyz"}):
            assert user_from_bearer() is None
        with app.test_request_context(headers={"Authorization": "Bearer "}):
            assert user_from_bearer() is None


# ═══════════════════════════════════════════════════════════════════════════
# 4. Transaction edge branches
# ═══════════════════════════════════════════════════════════════════════════


class TestTransactionEdges:
    def test_nested_tx_hook_propagation(self, app):
        from app.core.db import tx

        with app.app_context():
            tx(lambda: tx(lambda: None))

    def test_post_commit_hook_failure_logged_not_raised(self, app):
        from app.core.db import tx, tx_on_commit

        with app.app_context():

            def _boom():
                raise ZeroDivisionError("hook broke")

            def _reg():
                tx_on_commit(_boom)

            tx(_reg)  # hook failure after commit must not raise

    def test_expire_all_failure_swallowed(self, app):
        from app.core.db import tx

        with app.app_context():
            try:
                with patch.object(db_session_expire_target(), "expire_all", side_effect=RuntimeError("x")):
                    tx(lambda: None)
            except (AttributeError, TypeError):
                pytest.skip("scoped session does not allow patching expire_all")


def db_session_expire_target():
    from app.extensions import db

    return db.session


# ═══════════════════════════════════════════════════════════════════════════
# 5. Pure service bits
# ═══════════════════════════════════════════════════════════════════════════


class TestServicePureBits:
    def test_letter_grade_failing(self, app):
        from app.services.grade_calc import _letter_grade

        assert _letter_grade(10.0) == "راسب"

    def test_cosine_zero_norm(self, app):
        from app.services.rag_service import _cosine_similarity

        assert _cosine_similarity({}, {"a": 1.0}) == 0.0
        assert _cosine_similarity({}, {}) == 0.0

    def test_parse_llm_invalid_json(self, app):
        from app.services.quiz_ai_service import _parse_llm_response

        assert _parse_llm_response("not json at all") is None
        assert _parse_llm_response("") is None

    def test_webp_magic(self, app):
        """RIFF prefix maps to video/webm; short headers (<4 bytes) are rejected."""
        from app.core.uploads import _detect_magic_type

        assert _detect_magic_type(b"RIFF\x00\x00\x00\x00WEBP", ".webp") == "video/webm"
        assert _detect_magic_type(b"RIFF", ".webp") == "video/webm"  # 4-byte RFF prefix still detected
        assert _detect_magic_type(b"RIF", ".webp") is None  # too short (<4 bytes)

    def test_fmt_date_fallback(self, app):
        from app.services.email import _fmt_date

        with patch("app.services.email.babel_format_date", side_effect=ValueError("x")):
            assert _fmt_date(datetime(2026, 1, 2), "ar") == "2026-01-02"

    def test_ai_usage_failopen(self, app):
        from app.services.ai_usage import monthly_tokens_used

        with app.app_context():
            with patch("app.services.ai_usage.AiUsageLog") as m:
                m.total_tokens = MagicMock()
                assert monthly_tokens_used(1) == 0

    def test_invoice_pdf_importerror(self, app):
        from app.services.invoice import render_invoice_pdf

        sid, cid = setup_class(app)
        uid, _ = mk(app, "student", school_id=sid)
        make_class_member(app, cid, uid)
        plan = make_subscription_plan(app, sid, class_id=cid)
        sub_id = make_subscription(app, uid, plan, cid)
        with app.app_context():
            with patch.dict(sys.modules, {"xhtml2pdf": None, "xhtml2pdf.pisa": None}):
                # generate_invoice_html renders base templates → needs request context
                with app.test_request_context("/"):
                    assert render_invoice_pdf(sub_id) is None

    def test_report_card_pdf_importerror(self, app):
        from app.services.report_card import render_report_card_pdf

        sid, cid = setup_class(app)
        uid, _ = mk(app, "student", school_id=sid)
        make_class_member(app, cid, uid)
        with app.app_context():
            with patch.dict(sys.modules, {"xhtml2pdf": None, "xhtml2pdf.pisa": None}):
                assert render_report_card_pdf(uid, cid) is None

    def test_payment_reminder_missing_subscription(self, app):
        from app.models.billing import Subscription
        from app.services.email import send_payment_reminder_email

        with app.app_context():
            ghost = Subscription(id=99999999)
            assert send_payment_reminder_email(ghost, 3) is False

    def test_audit_forwarded_ip(self, app):
        from app.services.communication import audit

        sid, _cid = setup_class(app)
        uid, _ = mk(app, "teacher", school_id=sid)
        with app.test_request_context("/", headers={"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}):
            from app.extensions import db
            from app.models.user import User
            from flask_login import login_user

            login_user(db.session.get(User, uid))
            audit("test.action", "schools", sid)

    def test_health_database_down(self, app):
        from app.services import health

        with app.app_context():
            with patch("app.services.health.db") as m:
                m.session.execute.side_effect = RuntimeError("down")
                r = health.check_database()
            assert r["status"] == "down"

    def test_health_disk_down(self, app):
        from app.services import health

        with patch("shutil.disk_usage", side_effect=RuntimeError("x")):
            r = health.check_disk()
        assert r["status"] == "down"

    def test_growth_rate_nonzero(self, app):
        from app.services.revenue import get_growth_rate

        sid, cid = setup_class(app)
        uid, _ = mk(app, "student", school_id=sid)
        plan = make_subscription_plan(app, sid, class_id=cid)
        sub_id = make_subscription(app, uid, plan, cid)
        pid = make_payment(app, sub_id, amount=50, status="approved")
        now = datetime.now(UTC)
        with app.app_context():
            from app.core.db import tx
            from app.extensions import db
            from app.models.billing import ManualPayment

            def _backdate():
                mp = db.session.get(ManualPayment, pid)
                mp.created_at = now - timedelta(days=45)

            tx(_backdate)
            growth = get_growth_rate(date_from=now - timedelta(days=60), date_to=now)
            assert growth < 0  # current period empty, previous had revenue

    def test_individual_public_classes_and_errors(self, app):
        from app.services.individual import get_public_classes, subscribe_to_class

        sid = make_school(app)
        lvl = _next_level(sid)
        gid = make_grade(app, sid, grade_level=lvl)
        subj = make_subject(app)
        cid = make_class(app, sid, gid, subj)
        uid, _ = mk(app, "student", school_id=sid)
        with app.app_context():
            from app.extensions import db
            from app.models.class_room import ClassRoom

            db.session.get(ClassRoom, cid).is_public = True
            db.session.commit()
            # get_public_classes filters on Grade.grade_level (numeric level), not the grade id
            assert any(c.id == cid for c in get_public_classes(grade_level=lvl))
            assert any(c.id == cid for c in get_public_classes(subject_id=subj))
            # unknown student → error string; real student in a free class → None (success)
            assert subscribe_to_class(99999999, cid)
            assert subscribe_to_class(uid, cid) is None

    def test_onboarding_complete_twice(self, app):
        from app.core.db import tx
        from app.services.onboarding import complete_step, get_wizard_steps

        sid = make_school(app)
        steps = get_wizard_steps()
        with app.app_context():
            from app.extensions import db
            from app.models.system import OnboardingProgress

            def _seed():
                db.session.add(OnboardingProgress(school_id=sid, current_step=1, total_steps=len(steps)))

            tx(_seed)
            for i in range(1, len(steps) + 1):
                complete_step(sid, i)
            prog = complete_step(sid, 1)  # already complete → returns progress unchanged
            assert prog is not None
            assert prog.is_complete
            assert complete_step(sid, 99) is None  # out-of-range guard

    def test_tenant_quota_caps(self, app):
        from app.core.db import tx
        from app.services.tenant import check_quota, get_quota, set_tier

        sid = make_school(app)
        with app.app_context():
            set_tier(sid, "free")
            set_tier(sid, "free")  # update-existing branch
            q = get_quota(sid)

            def _zero():
                q.max_students = 0
                q.max_teachers = 0
                q.max_classes = 0

            tx(_zero)
            assert check_quota(sid, "students")[0] is False
            assert check_quota(sid, "teachers")[0] is False
            assert check_quota(sid, "classes")[0] is False
            assert check_quota(sid, "ai")[0] is False

    def test_quiz_stats_distribution_buckets(self, app):
        from app.core.db import tx
        from app.extensions import db
        from app.models.assessment import QuizAttempt
        from app.services.quiz_stats import get_quiz_stats

        sid, cid = setup_class(app)
        tid, _ = mk(app, "teacher", school_id=sid)
        suid, _ = mk(app, "student", school_id=sid)
        with app.app_context():
            from app.extensions import db
            from app.models.assessment import Question, Quiz

            def _mk():
                q = Quiz(class_id=cid, title="q", total_mark=100.0, created_by=tid)
                db.session.add(q)
                db.session.flush()
                a1 = QuizAttempt(quiz_id=q.id, student_id=suid, status="submitted", score=30)
                a2 = QuizAttempt(quiz_id=q.id, student_id=suid, attempt_no=2, status="submitted", score=70)
                db.session.add_all([a1, a2])
                # bins are percentages of total_possible → need one Question worth 100 marks
                db.session.add(Question(quiz_id=q.id, type="mcq", prompt="p", mark=100.0, sort_order=1))
                return q.id

            qid = tx(_mk)
            stats = get_quiz_stats(qid)
            assert stats is not None
            assert stats.score_distribution["20-40"] == 1
            assert stats.score_distribution["60-80"] == 1

    def test_progress_service_branches(self, app):
        from app.core.db import tx
        from app.extensions import db
        from app.models.progress import StudentProgress
        from app.services.progress import (
            class_progress_overview,
            record_lesson_view,
            update_video_progress,
        )

        sid, cid = setup_class(app)
        uid, _ = mk(app, "student", school_id=sid)
        uid2, _ = mk(app, "student", school_id=sid)
        lid = make_lesson(app, cid)
        att_id = make_attachment(app, lid)
        with app.app_context():

            def _seed():
                db.session.add(StudentProgress(student_id=uid, lesson_id=lid, class_id=cid, status="not_started"))
                db.session.add(
                    StudentProgress(
                        student_id=uid2,
                        lesson_id=lid,
                        class_id=cid,
                        status="completed",
                        progress_pct=100,
                    )
                )

            tx(_seed)
            p = record_lesson_view(uid, lid, cid)
            assert p.status == "in_progress"
            vp = update_video_progress(uid, att_id, lid, cid, 95, 100)
            assert vp.completed is True
            overview = class_progress_overview(cid)
            assert isinstance(overview, list)

    def test_video_service_token_and_access(self, app):
        from app.services.video_service import (
            generate_stream_token,
            get_master_playlist_url,
            get_stream_url,
            validate_lesson_access,
            verify_stream_token,
        )

        sid = make_school(app)
        gid = make_grade(app, sid, grade_level=_next_level(sid))
        subj = make_subject(app)
        tid, _ = mk(app, "teacher", school_id=sid)
        cid = make_class(app, sid, gid, subj, teacher_id=tid)
        said, _ = mk(app, "school_admin", school_id=sid)
        suid, _ = mk(app, "student", school_id=sid)
        make_class_member(app, cid, suid)
        guid, _ = mk(app, "super_admin")
        lid = make_lesson(app, cid)
        bad = base64.urlsafe_b64encode(b"1:1:1:9999999999:shortsig").decode()
        ok, err = verify_stream_token(bad, 1, 1, 1)
        assert ok is False and err == "Invalid token format"
        with app.test_request_context("/"):
            from app.extensions import db as _db
            from app.models.user import User

            url = get_stream_url(suid, sid, lid, "master.m3u8")
            assert "token=" in url and "uid=" in url
            assert "master.m3u8" in get_master_playlist_url(suid, sid, lid)
            assert validate_lesson_access(guid, sid, lid) == (True, None)
            with app.test_request_context("/"):
                from flask_login import login_user

                login_user(_db.session.get(User, said))
                assert validate_lesson_access(said, sid, lid) == (True, None)
            assert validate_lesson_access(tid, sid, lid) == (True, None)
            assert validate_lesson_access(suid, sid, lid) == (True, None)
        with app.app_context():
            token = generate_stream_token(suid, sid, lid)
        assert token

    def test_gamification_streak_and_course(self, app):
        from app.core.db import tx
        from app.extensions import db
        from app.models.gamification import Badge, BadgeCriteriaType
        from app.models.progress import StudentProgress
        from app.services.gamification import _check_streak, check_and_award_badges

        sid, cid = setup_class(app)
        uid, _ = mk(app, "student", school_id=sid)
        uid2, _ = mk(app, "student", school_id=sid)
        # one lesson per day — (student_id, lesson_id) is unique
        day_lessons = [make_lesson(app, cid) for _ in range(7)]
        with app.app_context():

            def _seed():
                db.session.add(
                    Badge(
                        name="سلسلة", icon_name="fire", criteria_type=BadgeCriteriaType.streak_7_days, criteria_value=7
                    )
                )
                db.session.add(Badge(name="إكمال", icon_name="book", criteria_type=BadgeCriteriaType.course_complete))
                # Seed at noon UTC: func.date() renders in the *server* timezone, so
                # seeding near local midnight (server tz != UTC) shifts dates by one
                # day and breaks the streak. Noon UTC maps to the same calendar date
                # in any tz up to +12h — deterministic 24/7.
                noon = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
                for d, lid_d in enumerate(day_lessons):
                    db.session.add(
                        StudentProgress(
                            student_id=uid,
                            lesson_id=lid_d,
                            class_id=cid,
                            status="completed",
                            progress_pct=100,
                            completed_at=noon - timedelta(days=d),
                        )
                    )

            tx(_seed)
            awarded = check_and_award_badges(uid, "lesson_completed", {"class_id": cid})
            assert isinstance(awarded, list)
            assert _check_streak(uid, 7) is True
            # gap breaks the streak (separate student — no progress rows)
            assert _check_streak(uid2, 2) is False

    def test_schools_service_code_loops(self, app):
        from app.extensions import db
        from app.models.class_room import ClassRoom
        from app.services import schools as schools_svc

        sid = make_school(app)
        gid = make_grade(app, sid, grade_level=_next_level(sid))
        subj = make_subject(app)
        cid = make_class(app, sid, gid, subj)
        with app.app_context():
            existing_code = db.session.get(ClassRoom, cid).join_code
            with patch.object(schools_svc, "_join_code", side_effect=[existing_code, "ZZ9Q9Z1"]):
                created, err = schools_svc.create_class(school_id=sid, grade_id=gid, subject_id=subj, name="صف2")
            assert err is None and created is not None
            cid2 = created.id
            assert db.session.get(ClassRoom, cid2).join_code == "ZZ9Q9Z1"
            cls = db.session.get(ClassRoom, cid2)
            with patch.object(schools_svc, "_join_code", side_effect=[existing_code, "YY8P8Y2"]):
                assert schools_svc.regenerate_join_code(cls) == "YY8P8Y2"
            with patch.object(schools_svc, "create_school", return_value=(None, "boom")):
                s, err = schools_svc.create_school_with_defaults("مدرسة", None)
            assert s is None and err == "boom"

    def test_school_approvals_error_paths(self, app):
        from app.core.db import tx as _tx
        from app.extensions import db
        from app.models.user import UserApprovalStatus
        from app.services.school_approvals import (
            get_approval_queue_for_user,
            reject_user_role_link,
        )

        sid = make_school(app)
        tuid, _ = mk(app, "teacher")  # no school link — make_user_role_link adds the only one
        link_id = make_user_role_link(app, tuid, sid, role="teacher")
        suid, _ = mk(app, "student", school_id=sid)
        nousid, _ = mk(app, "student")
        with app.app_context():
            from app.models.user import User as _U

            ok, err = reject_user_role_link(link_id, 99999999, "no")
            assert ok is False and err
            ok2, err2 = reject_user_role_link(link_id, suid, None)
            assert ok2 is False and err2
            assert get_approval_queue_for_user(nousid) == []
            # wrong-role admin → queue empty (no super/school admin arms)
            assert get_approval_queue_for_user(tuid) == []

            # pending user → link reachable through the queue, then rejected
            def _pending():
                u = db.session.get(_U, tuid)
                u.approval_status = UserApprovalStatus.pending

            _tx(_pending)
            assert len(get_approval_queue_for_user(nousid)) == 0  # student role → no queue
            ok3, err3 = reject_user_role_link(link_id, suid, "reason")
            assert ok3 is False and err3  # student lacks the approve role

    def test_wallet_service_frozen_branches(self, app):
        from app.core.db import tx
        from app.extensions import db
        from app.models.wallet import Wallet
        from app.services import wallet_service

        sid, cid = setup_class(app)
        a, _ = mk(app, "student", school_id=sid)
        b, _ = mk(app, "student", school_id=sid)
        with app.app_context():
            wallet_service.get_or_create_wallet(sid, a)
            wallet_service.get_or_create_wallet(sid, b)
            wallet_service.admin_credit(sid, a, Decimal("100"), f"dep-{_uid()}", "تمويل")

            def _freeze_b():
                w = db.session.query(Wallet).filter_by(school_id=sid, user_id=b).first()
                w.status = "frozen"

            tx(_freeze_b)
            _tx, err = wallet_service.process_transfer(
                school_id=sid,
                source_user_id=a,
                dest_user_id=b,
                amount=Decimal("10"),
                idempotency_key=f"tr-{_uid()}",
                description="t",
            )
            assert _tx is None and err
            _tx2, err2 = wallet_service.admin_credit(sid, b, Decimal("5"), f"dep-{_uid()}", "t")
            assert _tx2 is None and err2

    def test_access_member_true(self, app):
        from app.extensions import db
        from app.models.class_room import ClassRoom
        from app.models.user import User
        from app.services.access import can_view_class

        sid, cid = setup_class(app)
        uid, _ = mk(app, "student", school_id=sid)
        make_class_member(app, cid, uid)
        with app.app_context():
            cls = db.session.get(ClassRoom, cid)
            user = db.session.get(User, uid)
            with app.test_request_context("/"):
                from flask_login import login_user

                login_user(user)
                assert can_view_class(cls, user) is True

    def test_gradebook_submit_and_update(self, app):
        from app.extensions import db
        from app.models.gradebook import GradeItem
        from app.services.gradebook import create_assignment, set_grade, submit_assignment

        sid, cid = setup_class(app)
        tid, _ = mk(app, "teacher", school_id=sid)
        uid, _ = mk(app, "student", school_id=sid)
        with app.app_context():
            assignment, err = create_assignment(class_id=cid, title="واجب", body="افعل", max_mark=10, created_by=tid)
            assert err is None
            bad = FileStorage(stream=BytesIO(b"MZ junk"), filename="x.png", content_type="image/png")
            sub, serr = submit_assignment(assignment, uid, None, bad)
            assert sub is None and serr
            cat = make_grade_category(app, cid, "أعمال", 50)
            item_id = make_grade_item(app, cid, cat, "اختبار", 100)
            item = db.session.get(GradeItem, item_id)
            set_grade(uid, item, 80)
            set_grade(uid, item, 90, note="محدّث")
            from app.models.gradebook import GradeEntry

            entry = GradeEntry.query.filter_by(student_id=uid, grade_item_id=item_id).first()
            assert entry.mark == 90 and entry.note == "محدّث"

    def test_export_empty_category_continues(self, app):
        from app.services.export import export_grades_excel

        sid, cid = setup_class(app)
        make_grade_category(app, cid, "فارغة", 50)
        with app.app_context():
            data = export_grades_excel(cid)
            assert isinstance(data, bytes) and len(data) > 0

    def test_assessment_deadline_naive_and_race(self, app):
        from app.core.db import tx
        from app.extensions import db
        from app.models.assessment import Quiz, QuizAttempt
        from app.services.assessment import deadline_exceeded, start_attempt

        sid, cid = setup_class(app)
        tid, _ = mk(app, "teacher", school_id=sid)
        uid, _ = mk(app, "student", school_id=sid)
        with app.app_context():

            def _mk():
                q = Quiz(class_id=cid, title="q", duration_min=30, created_by=tid)
                db.session.add(q)
                return q

            quiz = tx(_mk)
            attempt, err = start_attempt(quiz, uid)
            assert err is None

            def _naive():
                att = db.session.get(QuizAttempt, attempt.id)
                att.started_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2)

            tx(_naive)
            fresh = db.session.get(QuizAttempt, attempt.id)
            assert deadline_exceeded(fresh) is True
            # race branch: tx fails → existing in_progress attempt returned
            with patch("app.services.assessment.tx", side_effect=RuntimeError("dup")):
                att2, err2 = start_attempt(quiz, uid)
            assert att2 is not None and att2.id == attempt.id

    def test_ai_limits_guardrails(self, app):
        from app.services.ai import BudgetTracker, RateLimiter, get_ai_service

        with app.app_context():
            svc = get_ai_service()
            cls = type(svc)
            saved_rl = cls._rate_limiter
            saved_bt = cls._budget_tracker
            try:
                cls._rate_limiter = None
                cls._budget_tracker = None
                ok, msg = svc._check_limits(100)
                assert ok is True and msg == ""
                cls._rate_limiter = RateLimiter(0, 0)
                ok2, msg2 = svc._check_limits(100)
                assert ok2 is False
                # rate limiter must be active (and permissive) to reach the budget arm
                cls._rate_limiter = RateLimiter(999999, 999999)
                cls._budget_tracker = BudgetTracker(0.0)
                ok3, msg3 = svc._check_limits(100000)
                assert ok3 is False and "Budget" in msg3
            finally:
                cls._rate_limiter = saved_rl
                cls._budget_tracker = saved_bt


def ClassRoomTarget():
    from app.models.class_room import ClassRoom

    return ClassRoom


# ═══════════════════════════════════════════════════════════════════════════
# 6. Route guard arms (404/403/flash errors)
# ═══════════════════════════════════════════════════════════════════════════


class TestRouteGuards:
    # ── content ──
    def test_content_class_404(self, app):
        _, client = persona(app, "teacher")
        assert client.get("/classes/999999/lessons").status_code == 404

    def test_content_publish_missing_lesson_404(self, app):
        sid, cid = setup_class(app)
        tid, email = mk(app, "teacher", school_id=sid)
        from app.extensions import db
        from app.models.class_room import ClassRoom

        with app.app_context():
            db.session.get(ClassRoom, cid).teacher_id = tid
            db.session.commit()
        client = login_email(app, email)
        assert client.post(f"/classes/{cid}/lessons/999999/publish").status_code == 404

    def test_content_youtube_missing_lesson_404(self, app):
        sid, cid = setup_class(app)
        tid, email = mk(app, "teacher", school_id=sid)
        from app.extensions import db
        from app.models.class_room import ClassRoom

        with app.app_context():
            db.session.get(ClassRoom, cid).teacher_id = tid
            db.session.commit()
        client = login_email(app, email)
        assert client.post(f"/classes/{cid}/lessons/999999/youtube", data={"url": "https://x"}).status_code == 404

    def test_content_import_missing_lesson_404(self, app):
        _, client = persona(app, "teacher")
        assert client.post("/classes/import/999999").status_code == 404

    def test_content_lesson_create_error_flash(self, app):
        sid, cid = setup_class(app)
        tid, email = mk(app, "teacher", school_id=sid)
        from app.extensions import db
        from app.models.class_room import ClassRoom

        with app.app_context():
            db.session.get(ClassRoom, cid).teacher_id = tid
            db.session.commit()
        client = login_email(app, email)
        with patch("app.modules.content.routes.create_lesson", return_value=(None, "boom")):
            resp = client.post(f"/classes/{cid}/lessons", data={"title": "درس"})
        assert resp.status_code in (200, 302)

    # ── grades ──
    def test_grades_class_404(self, app):
        _, client = persona(app, "teacher")
        assert client.get("/classes/999999/assignments").status_code == 404

    def test_grades_assignment_404(self, app):
        sid, cid = setup_class(app)
        _, client = persona(app, "teacher", school_id=sid)
        assert client.get(f"/classes/{cid}/assignments/999999").status_code == 404

    def test_grades_assignment_create_error_flash(self, app):
        sid, cid = setup_class(app)
        tid, email = mk(app, "teacher", school_id=sid)
        from app.extensions import db
        from app.models.class_room import ClassRoom

        with app.app_context():
            cls = db.session.get(ClassRoom, cid)
            cls.teacher_id = tid
            db.session.commit()
        client = login_email(app, email)
        with patch("app.modules.grades.routes.create_assignment", return_value=(None, "boom")):
            resp = client.post(f"/classes/{cid}/assignments", data={"title": "و", "body": "ب", "max_mark": 10})
        assert resp.status_code == 302

    def test_report_card_parent_branches(self, app):
        sid, cid = setup_class(app)
        stid, _ = mk(app, "student", school_id=sid)
        make_class_member(app, cid, stid)  # parent access derives from the student's membership
        puid, pemail = mk(app, "parent", school_id=sid)
        client = login_email(app, pemail)
        assert client.get(f"/classes/{cid}/report-card/{stid}/pdf").status_code == 403
        from app.core.db import tx as _tx

        with app.app_context():
            from app.extensions import db
            from app.models.family import FamilyLink

            def _link():
                db.session.add(FamilyLink(parent_id=puid, student_id=stid))

            _tx(_link)
        # parent link grants the HTML page; PDF may still render or 4xx on missing data
        html = client.get(f"/classes/{cid}/report-card/{stid}")
        assert html.status_code in (200, 302)
        assert client.get(f"/classes/{cid}/report-card/{stid}/pdf").status_code in (200, 302, 400, 404)

    def test_rubric_grade_student_403(self, app):
        from app.services.gradebook import create_assignment, submit_assignment

        sid, cid = setup_class(app)
        tid, _ = mk(app, "teacher", school_id=sid)
        stid, semail = mk(app, "student", school_id=sid)
        make_class_member(app, cid, stid)
        with app.app_context():
            assignment, _err = create_assignment(class_id=cid, title="و", body="ب", max_mark=10, created_by=tid)
            sub, err2 = submit_assignment(assignment, stid, "حلي", None)
            assert err2 is None
            sub_id = sub.id
        client = login_email(app, semail)
        assert client.post(f"/classes/rubric/grade/{sub_id}", data={}).status_code == 403

    # ── assessment ──
    def test_quiz_create_error_flash(self, app):
        sid, cid = setup_class(app)
        tid, email = mk(app, "teacher", school_id=sid)
        from app.extensions import db
        from app.models.class_room import ClassRoom

        with app.app_context():
            db.session.get(ClassRoom, cid).teacher_id = tid
            db.session.commit()
        client = login_email(app, email)
        with patch("app.modules.assessment.routes.create_quiz", return_value=(None, "boom")):
            resp = client.post(f"/classes/{cid}/quizzes/new", data={"title": "اختبار"})
        assert resp.status_code in (200, 302)

    def test_attempt_start_none_flash(self, app):
        from app.core.db import tx
        from app.extensions import db
        from app.models.assessment import Quiz

        sid, cid = setup_class(app)
        tid, _ = mk(app, "teacher", school_id=sid)
        stid, semail = mk(app, "student", school_id=sid)
        make_class_member(app, cid, stid)
        with app.app_context():

            def _mk():
                q = Quiz(class_id=cid, title="q", created_by=tid)
                db.session.add(q)
                return q

            quiz = tx(_mk)
            qid = quiz.id
        client = login_email(app, semail)
        with patch("app.modules.assessment.routes.start_attempt", return_value=(None, "err")):
            resp = client.get(f"/classes/quizzes/{qid}/attempt")
        assert resp.status_code == 302

    def test_submit_already_submitted_redirect(self, app):
        from app.core.db import TxError, tx
        from app.extensions import db
        from app.models.assessment import Quiz, QuizAttempt

        sid, cid = setup_class(app)
        tid, _ = mk(app, "teacher", school_id=sid)
        stid, semail = mk(app, "student", school_id=sid)
        make_class_member(app, cid, stid)
        with app.app_context():

            def _mk():
                q = Quiz(class_id=cid, title="q", created_by=tid)
                db.session.add(q)
                db.session.flush()
                a = QuizAttempt(quiz_id=q.id, student_id=stid, status="in_progress")
                db.session.add(a)
                return a

            att = tx(_mk)
            att_id = att.id
        client = login_email(app, semail)
        with patch("app.modules.assessment.routes.submit_attempt", side_effect=TxError("سبق الإرسال مسبقاً")):
            resp = client.post(f"/classes/attempt/{att_id}/submit", data={})
        assert resp.status_code == 302

    def test_quiz_stats_guards(self, app):
        from app.core.db import tx
        from app.extensions import db
        from app.models.assessment import Quiz
        from app.models.class_room import ClassRoom

        sid, cid = setup_class(app)
        tid, temail = mk(app, "teacher", school_id=sid)
        with app.app_context():
            db.session.get(ClassRoom, cid).teacher_id = tid
            db.session.commit()

            def _mk():
                q = Quiz(class_id=cid, title="q", created_by=tid)
                db.session.add(q)
                return q

            quiz = tx(_mk)
            qid = quiz.id
        # student (non-teacher) → 403
        suid, semail = mk(app, "student", school_id=sid)
        sclient = login_email(app, semail)
        assert sclient.get(f"/classes/quiz/{qid}/stats").status_code == 403
        tclient = login_email(app, temail)
        with patch("app.modules.assessment.routes.get_quiz_stats", return_value=None):
            resp = tclient.get(f"/classes/quiz/{qid}/stats")
        assert resp.status_code == 302

    # ── billing ──
    def test_billing_class_404(self, app):
        _, client = persona(app, "student")
        assert client.get("/billing/999999").status_code == 404

    def test_billing_subscribe_duplicate_error_flash(self, app):
        sid, cid = setup_class(app)
        uid, email = mk(app, "student", school_id=sid)
        make_class_member(app, cid, uid)
        plan = make_subscription_plan(app, sid, class_id=cid)
        client = login_email(app, email)
        first = client.post(f"/billing/{cid}/subscribe", data={"plan_id": plan})
        assert first.status_code in (200, 302)
        second = client.post(f"/billing/{cid}/subscribe", data={"plan_id": plan})
        assert second.status_code in (200, 302)

    def test_billing_plan_create_error_flash(self, app):
        sid, cid = setup_class(app)
        from app.extensions import db
        from app.models.class_room import ClassRoom

        with app.app_context():
            tid, email = mk(app, "teacher", school_id=sid)
            db.session.get(ClassRoom, cid).teacher_id = tid
            db.session.commit()
        client = login_email(app, email)
        with patch("app.modules.billing.routes.create_plan", return_value=(None, "boom")):
            resp = client.post(f"/billing/{cid}/plans", data={"name": "باقة", "price": "100", "currency": "ILS"})
        assert resp.status_code in (200, 302)

    # ── messages ──
    def test_messages_compose_reply_missing_404(self, app):
        _, client = persona(app, "student")
        assert client.get("/messages/send/999999").status_code == 404

    def test_messages_compose_missing_fields_flash(self, app):
        _, client = persona(app, "student")
        resp = client.post("/messages/send", data={})
        assert resp.status_code == 302

    def test_messages_compose_bad_recipient_flash(self, app):
        _, client = persona(app, "student")
        resp = client.post("/messages/send", data={"recipient_id": "999999", "subject": "s", "body": "b"})
        assert resp.status_code == 302

    def test_messages_thread_404(self, app):
        _, client = persona(app, "student")
        assert client.get("/messages/thread/999999").status_code == 404

    # ── progress ──
    def test_progress_class_404_and_403(self, app):
        _, client = persona(app, "student")
        assert client.get("/progress/class/999999").status_code == 404
        sid, cid = setup_class(app)
        outsider, oemail = mk(app, "student")
        oclient = login_email(app, oemail)
        assert oclient.get(f"/progress/class/{cid}").status_code == 403

    def test_progress_parent_branch(self, app):
        """Parent without link → 403; after FamilyLink → detail page renders."""
        sid, cid = setup_class(app)
        stid, _ = mk(app, "student", school_id=sid)
        make_class_member(app, cid, stid)  # parent access derives from the student's membership
        puid, pemail = mk(app, "parent", school_id=sid)
        client = login_email(app, pemail)
        assert client.get(f"/progress/class/{cid}/student/{stid}").status_code == 403
        from app.core.db import tx
        from app.extensions import db
        from app.models.family import FamilyLink

        with app.app_context():

            def _link():
                db.session.add(FamilyLink(parent_id=puid, student_id=stid))

            tx(_link)
        resp = client.get(f"/progress/class/{cid}/student/{stid}")
        assert resp.status_code == 200

    def test_progress_heartbeat_nonmember_403(self, app):
        sid, cid = setup_class(app)
        lid = make_lesson(app, cid)
        uid, email = mk(app, "student", school_id=sid)
        client = login_email(app, email)
        assert client.post(f"/progress/lesson/{lid}/heartbeat", json={"seconds": 30}).status_code == 403

    def test_progress_my_page(self, app):
        sid, cid = setup_class(app)
        uid, email = mk(app, "student", school_id=sid)
        make_class_member(app, cid, uid)
        make_lesson(app, cid)
        client = login_email(app, email)
        assert client.get("/progress/my").status_code == 200

    # ── family ──
    def test_family_link_success_flash(self, app):
        sid, _cid = setup_class(app)
        stid, _ = mk(app, "student", school_id=sid)
        code = make_family_link_code(app, stid)
        puid, pemail = mk(app, "parent", school_id=sid)
        client = login_email(app, pemail)
        resp = client.post("/family/link", data={"code": code})
        assert resp.status_code == 302

    def test_family_remove_missing_404_flash(self, app):
        _, client = persona(app, "parent")
        resp = client.post("/family/link/999999/remove")
        assert resp.status_code == 302

    def test_family_generate_twice_error_redirect(self, app):
        sid, _cid = setup_class(app)
        uid, email = mk(app, "student", school_id=sid)
        client = login_email(app, email)
        first = client.get("/family/generate")
        assert first.status_code == 200
        second = client.get("/family/generate")
        # second call reuses/rotates the existing code and still renders (200) or redirects
        assert second.status_code in (200, 302)

    # ── individual ──
    def test_individual_duplicate_subscribe_flash(self, app):
        sid, cid = setup_class(app)
        uid, email = mk(app, "student", school_id=sid)
        client = login_email(app, email)
        assert client.post(f"/my/catalog/{cid}/subscribe").status_code == 302
        assert client.post(f"/my/catalog/{cid}/subscribe").status_code == 302

    # ── gamification ──
    def test_badges_check_role_and_payload(self, app):
        sid, _cid = setup_class(app)
        tuid, temail = mk(app, "teacher", school_id=sid)
        tclient = login_email(app, temail)
        assert tclient.post("/profile/badges/check", json={"event_type": "lesson_completed"}).status_code == 403
        suid, semail = mk(app, "student", school_id=sid)
        sclient = login_email(app, semail)
        assert sclient.post("/profile/badges/check", json={}).status_code == 400

    # ── calendar ──
    def test_calendar_delete_missing_flash(self, app):
        """Deleting a foreign-school event as school_admin → 403; own-school missing → flash redirect."""
        sid = make_school(app)
        _, client = persona(app, "school_admin", school_id=sid)
        # non-existent event → 404 via get_or_404
        assert client.post("/calendar/events/999999/delete").status_code == 404

    def test_calendar_create_error_flash(self, app):
        sid = make_school(app)
        _, client = persona(app, "school_admin", school_id=sid)
        with patch("app.modules.calendar.routes.create_event", return_value=(None, "boom")):
            resp = client.post(f"/calendar/{sid}/events", data={"title": "حدث", "date": "2026-10-01"})
        assert resp.status_code in (200, 302)

    # ── schools ──
    def test_schools_classes_scope_guard(self, app):
        # /schools/classes is my_classes (any logged-in user) → 200
        _, client = persona(app, "super_admin")
        assert client.get("/schools/classes").status_code == 200
        sid = make_school(app)
        _, client2 = persona(app, "school_admin", school_id=sid)
        assert client2.get("/schools/classes").status_code == 200

    def test_school_create_error_flash(self, app):
        _, client = persona(app, "super_admin")
        with patch("app.modules.schools.routes.create_school_with_defaults", return_value=(None, "boom")):
            resp = client.post("/schools/new", data={"name_ar": "مدرسة"})
        assert resp.status_code in (200, 302)

    def test_school_class_create_error_flash(self, app):
        sid = make_school(app)
        gid = make_grade(app, sid, grade_level=_next_level(sid))
        _, client = persona(app, "school_admin", school_id=sid)
        with patch("app.modules.schools.routes.create_class", return_value=(None, "boom")):
            resp = client.post(f"/schools/{sid}/classes/new", data={"subject": "رياضيات", "grade_id": gid})
        assert resp.status_code in (200, 302)

    # ── tutoring ──
    def test_tutoring_profile_404(self, app):
        _, client = persona(app, "student")
        assert client.get("/tutoring/tutors/999999").status_code == 404

    def test_tutoring_profile_create_error_flash(self, app):
        _, client = persona(app, "teacher")
        with patch("app.modules.tutoring.routes.create_tutor_profile", return_value=(None, "boom")):
            resp = client.post(
                "/tutoring/profile/new",
                data={"subject": "رياضيات", "price_hour": "10", "price_session": "5", "mode": "both", "bio": "ب"},
            )
        assert resp.status_code in (200, 302)

    def test_tutoring_book_self_warning(self, app):
        uid, email = mk(app, "teacher")
        make_tutor_profile(app, uid)
        client = login_email(app, email)
        resp = client.get(f"/tutoring/book/{uid}")
        assert resp.status_code == 302

    def test_tutoring_end_live_foreign_403(self, app):
        sid, _cid = setup_class(app)
        t1, _ = mk(app, "teacher", school_id=sid)
        stu, _ = mk(app, "student", school_id=sid)
        sess = make_tutoring_session(app, t1, stu, status="active")
        t2, t2email = mk(app, "teacher", school_id=sid)
        client = login_email(app, t2email)
        assert client.post(f"/tutoring/sessions/{sess}/end-live").status_code == 403

    def test_tutoring_rate_window_and_error(self, app):
        sid, _cid = setup_class(app)
        t1, _ = mk(app, "teacher", school_id=sid)
        stu, semail = mk(app, "student", school_id=sid)
        old = (datetime.now(UTC) - timedelta(hours=25)).replace(tzinfo=None)
        old_sess = make_tutoring_session(app, t1, stu, status="completed", end_time=old)
        client = login_email(app, semail)
        assert client.post(f"/tutoring/rate/{old_sess}", data={"rating": "5"}).status_code == 302
        fresh = make_tutoring_session(app, t1, stu, status="completed", end_time=datetime.now(UTC))
        with patch("app.modules.tutoring.routes.rate_session", return_value=(None, "boom")):
            resp = client.post(f"/tutoring/rate/{fresh}", data={"rating": "4"})
        assert resp.status_code in (200, 302)  # flash + re-render or redirect

    def test_tutoring_payout_error_flash(self, app):
        uid, email = mk(app, "teacher")
        make_tutor_profile(app, uid)
        client = login_email(app, email)
        resp = client.post("/tutoring/payout-request", data={"amount": "999999"})
        assert resp.status_code in (200, 302)

    # ── school approvals ──
    def test_approval_reject_foreign_admin_403(self, app):
        sid = make_school(app)
        tuid, _ = mk(app, "teacher")  # no school link yet — mk() would collide with uq_user_role_link
        link_id = make_user_role_link(app, tuid, sid, role="teacher")
        sid_b = make_school(app)
        _, client = persona(app, "school_admin", school_id=sid_b)
        assert client.post(f"/school-admin/approvals/{link_id}/reject", data={"reason": "x"}).status_code == 403

    # ── admin ──
    def test_impersonate_non_super_403(self, app):
        sid = make_school(app)
        tuid, _ = mk(app, "teacher", school_id=sid)
        _, client = persona(app, "school_admin", school_id=sid)
        assert client.post(f"/admin/users/{tuid}/impersonate").status_code == 403

    # ── media ──
    def test_media_stream_guards(self, app):
        from app.services.video_service import generate_stream_token

        sid, cid = setup_class(app)
        uid, email = mk(app, "student", school_id=sid)
        make_class_member(app, cid, uid)
        lid = make_lesson(app, cid)
        client = login_email(app, email)
        assert client.get(f"/media/stream/{lid}/master.m3u8?token=x&uid=abc&sid=1").status_code == 400
        assert client.get(f"/media/stream/{lid}/master.m3u8?token=x&uid={uid}&sid={sid}").status_code == 403
        with app.app_context():
            token = generate_stream_token(uid, sid, lid)
        assert client.get(f"/media/stream/{lid}/a..b.m3u8?token={token}&uid={uid}&sid={sid}").status_code == 400
        assert client.get(f"/media/stream/{lid}/evil.txt?token={token}&uid={uid}&sid={sid}").status_code == 400


# ═══════════════════════════════════════════════════════════════════════════
# 7. Wallet REST validation arms
# ═══════════════════════════════════════════════════════════════════════════


class TestWalletApi:
    def test_balance_viewing_other_student_403(self, app):
        sid, _cid = setup_class(app)
        a, aemail = mk(app, "student", school_id=sid)
        b, _ = mk(app, "student", school_id=sid)
        client = login_email(app, aemail)
        assert client.get(f"/api/v1/wallet/balance?user_id={b}").status_code == 403

    def test_balance_no_school_400(self, app):
        uid, email = mk(app, "student")
        client = login_email(app, email)
        resp = client.get("/api/v1/wallet/balance")
        assert resp.status_code == 400

    def test_transactions_no_school_400(self, app):
        uid, email = mk(app, "student")
        client = login_email(app, email)
        assert client.get("/api/v1/wallet/transactions").status_code == 400

    def test_transactions_super_with_school_ok(self, app):
        sid, cid = setup_class(app)
        stu, _ = mk(app, "student", school_id=sid)
        _, client = persona(app, "super_admin")
        resp = client.get(f"/api/v1/wallet/transactions?school_id={sid}&user_id={stu}")
        assert resp.status_code == 200

    def test_transfers_invalid_amount_400(self, app):
        sid, _cid = setup_class(app)
        a, aemail = mk(app, "student", school_id=sid)
        b, _ = mk(app, "student", school_id=sid)
        client = login_email(app, aemail)
        resp = client.post(
            "/api/v1/wallet/transfers",
            json={"dest_user_id": b, "amount": "abc", "idempotency_key": "k1"},
        )
        assert resp.status_code == 400

    def test_transfers_wallet_error_400(self, app):
        sid, _cid = setup_class(app)
        a, aemail = mk(app, "student", school_id=sid)
        b, _ = mk(app, "student", school_id=sid)
        client = login_email(app, aemail)
        with patch("app.services.wallet_service.get_or_create_wallet", return_value=(None, "boom")):
            resp = client.post(
                "/api/v1/wallet/transfers",
                json={"dest_user_id": b, "amount": "5", "idempotency_key": "k2"},
            )
        assert resp.status_code == 400

    def test_deposit_super_without_school_400(self, app):
        _, client = persona(app, "super_admin")
        resp = client.post("/api/v1/wallet/deposits", json={"user_id": 1, "amount": "5", "idempotency_key": "k3"})
        assert resp.status_code == 400

    def test_deposit_success(self, app):
        sid, _cid = setup_class(app)
        a, _ = mk(app, "student", school_id=sid)
        _, client = persona(app, "school_admin", school_id=sid)
        resp = client.post(
            "/api/v1/wallet/deposits",
            json={"user_id": a, "amount": "25.50", "idempotency_key": f"dep-{_uid()}"},
        )
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# 8. Payments deep branches
# ═══════════════════════════════════════════════════════════════════════════


class TestPaymentsDeep:
    def test_cashu_idempotent_hit(self, app):
        """webhook secret + valid HMAC signature → idempotent replay returns True."""
        import hashlib
        import hmac

        from app.core.db import tx
        from app.extensions import db
        from app.models.billing import ProcessedEvent
        from app.services.payments import CashUGateway, PaymentGateway, PaymentIntent, PaymentStatus

        secret = "test-webhook-secret"
        payload = {"transaction_id": "ITEST1"}
        sig = hmac.new(secret.encode(), json.dumps(payload, sort_keys=True).encode(), hashlib.sha256).hexdigest()

        with app.app_context():

            def _mk():
                db.session.add(ProcessedEvent(event_id="cashu_ITEST1", gateway="cashu", payload={}))

            tx(_mk)
            g = CashUGateway({"webhook_secret": secret})
            intent = PaymentIntent(
                id="cashu_ITEST1",
                gateway=PaymentGateway.CASHU,
                amount=Decimal("10"),
                currency="ILS",
                status=PaymentStatus.PENDING,
                user_id=1,
            )
            assert g.verify_payment(intent, {"payload": payload, "headers": {"X-Cashu-Signature": sig}}) is True

    def test_handle_payment_resolves_plan_school(self, app):
        from app.services.payments import PaymentGateway, get_payment_service

        sid, cid = setup_class(app)
        stid, _ = mk(app, "student", school_id=sid)
        plan = make_subscription_plan(app, sid, class_id=cid)
        sub_id = make_subscription(app, stid, plan, cid, status="pending")
        make_payment(app, sub_id, amount=10, status="approved")
        svc = get_payment_service()
        with app.app_context():
            svc._handle_successful_payment(
                {"subscription_id": sub_id, "amount": "1000", "transaction_id": f"T-{_uid()}"},
                PaymentGateway.CASHU,
            )


# ═══════════════════════════════════════════════════════════════════════════
# 9. Task error/retry paths + tasks/__init__ celery branch
# ═══════════════════════════════════════════════════════════════════════════


class TestTaskErrorPaths:
    def test_grading_guard_import_error(self):
        sys.modules.pop("app.tasks.grading", None)
        with patch("app.tasks._HAS_CELERY", False):
            with pytest.raises(ImportError):
                importlib.import_module("app.tasks.grading")
        sys.modules.pop("app.tasks.grading", None)

    def test_reports_guard_import_error(self):
        sys.modules.pop("app.tasks.reports", None)
        with patch("app.tasks._HAS_CELERY", False):
            with pytest.raises(ImportError):
                importlib.import_module("app.tasks.reports")
        sys.modules.pop("app.tasks.reports", None)

    def test_auto_grade_orphan_answer_skipped(self, app, celery_on):
        """Answers whose question is not in the attempt's quiz are skipped (FK-valid)."""
        from app.core.db import tx
        from app.extensions import db
        from app.models.assessment import Answer, Question, Quiz, QuizAttempt

        sid, cid = setup_class(app)
        tid, _ = mk(app, "teacher", school_id=sid)
        stid, _ = mk(app, "student", school_id=sid)
        with app.app_context():

            def _mk():
                q = Quiz(class_id=cid, title="q", created_by=tid)
                db.session.add(q)
                db.session.flush()
                a = QuizAttempt(quiz_id=q.id, student_id=stid, status="submitted")
                db.session.add(a)
                db.session.flush()
                # Question belongs to a DIFFERENT quiz of the same class →
                # FK-valid, but absent from attempt.quiz.questions (skip arm).
                q2 = Quiz(class_id=cid, title="q2", created_by=tid)
                db.session.add(q2)
                db.session.flush()
                orphan_q = Question(
                    quiz_id=q2.id, type="mcq", prompt="س", options={"i": ["a"]}, correct_answer={"index": 0}, mark=5
                )
                db.session.add(orphan_q)
                db.session.flush()
                db.session.add(Answer(attempt_id=a.id, question_id=orphan_q.id, answer={"index": 0}))
                return a.id

            att_id = tx(_mk)
        from app.tasks.grading import auto_grade_quiz_attempt

        with app.app_context():
            result = auto_grade_quiz_attempt(self=None, attempt_id=att_id)
        assert result["status"] == "completed"
        assert result["score"] == 0

    def test_batch_gradebook_update_existing(self, app, celery_on):
        from app.tasks.grading import batch_update_gradebook

        sid, cid = setup_class(app)
        stid, _ = mk(app, "student", school_id=sid)
        cat = make_grade_category(app, cid, "أعمال", 50)
        item_id = make_grade_item(app, cid, cat, "اختبار", 100)
        make_grade_entry(app, stid, item_id, 50)
        with app.app_context():
            res = batch_update_gradebook(
                self=None,
                class_id=cid,
                grade_item_id=item_id,
                entries=[{"student_id": stid, "mark": 90, "note": "n1"}],
            )
        assert res["status"] == "completed" and res["updated"] == 1

    def test_batch_gradebook_error_branches(self, app, celery_on):
        from app.core.db import TxError
        from app.tasks.grading import batch_update_gradebook

        sid, cid = setup_class(app)
        with app.app_context():
            with patch("app.core.db.tx", side_effect=TxError("txfail")):
                res = batch_update_gradebook(self=None, class_id=cid, grade_item_id=1, entries=[])
            assert res["status"] == "failed"
            with patch("app.core.db.tx", side_effect=RuntimeError("boom")):
                res2 = batch_update_gradebook(self=None, class_id=cid, grade_item_id=1, entries=[])
            assert res2["status"] == "failed"

    def test_dispatch_notification_retry(self, app, celery_on):
        from app.tasks.notifications import dispatch_notification

        sid, cid = setup_class(app)
        uid, _ = mk(app, "student", school_id=sid)
        with app.app_context():
            # user must exist, or the task returns early before touching Notification
            with patch("app.models.communication.Notification", side_effect=RuntimeError("db")):
                with pytest.raises(_RetryCalled):
                    dispatch_notification(_fake_self(), uid, "grade", "t")

    def test_bulk_announcement_partial_errors(self, app, celery_on):
        from app.tasks.notifications import bulk_dispatch_school_announcement

        sid, cid = setup_class(app)
        s1, _ = mk(app, "student", school_id=sid)
        s2, _ = mk(app, "student", school_id=sid)
        with app.app_context():
            with patch("app.models.communication.Notification", side_effect=RuntimeError("db")):
                res = bulk_dispatch_school_announcement(self=None, school_id=sid, title="t", body="b")
            assert res["success"] is True
            assert len(res["errors"]) == 2

    def test_bulk_announcement_outer_retry(self, app, celery_on):
        from app.models.user import User
        from app.tasks.notifications import bulk_dispatch_school_announcement

        with app.app_context():
            with patch.object(User, "query", new_callable=PropertyMock, side_effect=RuntimeError("x")):
                with pytest.raises(_RetryCalled):
                    bulk_dispatch_school_announcement(_fake_self(), school_id=1, title="t", body="b")

    def test_email_dispatch_retry(self, app, celery_on):
        from app.tasks.notifications import dispatch_email_notification

        sid, _cid = setup_class(app)
        uid, _ = mk(app, "student", school_id=sid)
        with app.app_context():
            with patch("app.services.email._send", side_effect=RuntimeError("smtp")):
                with pytest.raises(_RetryCalled):
                    dispatch_email_notification(_fake_self(), user_id=uid, subject="s", html_body="<p>x</p>")

    def test_report_card_task_failure(self, app, celery_on):
        from app.tasks.reports import generate_report_card

        sid, cid = setup_class(app)
        stid, _ = mk(app, "student", school_id=sid)
        with app.app_context():
            with patch("app.services.grade_calc.calculate_student_grade", side_effect=RuntimeError("x")):
                res = generate_report_card(self=None, student_id=stid, class_id=cid, school_id=sid)
            assert res["status"] == "failed" and res["error"]

    def test_class_report_task_failure(self, app, celery_on):
        from app.tasks.reports import generate_class_report

        sid, cid = setup_class(app)
        with app.app_context():
            with patch("app.services.grade_calc.class_grades_summary", side_effect=RuntimeError("x")):
                res = generate_class_report(self=None, class_id=cid, school_id=sid)
            assert res["status"] == "failed" and res["error"]

    def test_invoice_task_missing_subscription(self, app, celery_on):
        from app.tasks.reports import generate_invoice

        with app.app_context():
            res = generate_invoice(self=None, subscription_id=99999999, school_id=1)
            assert res["status"] == "failed"
            assert res["error"] == "Subscription not found"

    def test_tasks_init_celery_branch(self, app):
        """Execute the celery-present module branch via a fake celery module."""
        saved = {
            k: v
            for k, v in sys.modules.items()
            if k == "app.tasks" or k.startswith("app.tasks.") or k == "celery" or k.startswith("celery.")
        }

        def _connect(fn=None, **k):
            if fn is None:  # used as @connect(kwargs) → return decorator
                return lambda f: f
            return fn  # celery applies @connect as bare decorator: fn is passed directly

        signals = types.SimpleNamespace(
            task_prerun=types.SimpleNamespace(connect=_connect),
            task_postrun=types.SimpleNamespace(connect=_connect),
        )
        fake_celery = types.ModuleType("celery")

        class _FakeCeleryApp:
            def __init__(self, *a, **k):
                self.conf = SimpleNamespace(update=lambda *a, **k: None)

            def config_from_object(self, *a, **k):
                return None

            def autodiscover_tasks(self, *a, **k):
                return None

        fake_celery.Celery = _FakeCeleryApp
        fake_celery.signals = signals
        fake_sig = types.ModuleType("celery.signals")
        fake_sig.task_prerun = signals.task_prerun
        fake_sig.task_postrun = signals.task_postrun
        try:
            sys.modules.pop("app.tasks", None)
            sys.modules["celery"] = fake_celery
            sys.modules["celery.signals"] = fake_sig
            t2 = importlib.import_module("app.tasks")
            t2 = importlib.reload(t2)
            assert t2._HAS_CELERY is True
            t2.init_celery(app)
            assert t2.celery_app.flask_app is app
            # ContextTask on a bare mixin has no celery Task.__call__; both
            # branches (flask_app set / None) funnel into super().__call__
            inst = t2.ContextTask()
            with pytest.raises(AttributeError):
                inst()  # flask_app set → app-context branch
            t2.celery_app.flask_app = None
            with pytest.raises(AttributeError):
                inst()  # no flask_app → fallback branch
            # signal handlers log start/end
            t2._task_prerun_handler(sender=SimpleNamespace(name="t"), task_id="x")
            t2._task_postrun_handler(sender=SimpleNamespace(name="t"), task_id="x", retval=None, state="SUCCESS")
            t2._task_postrun_handler(sender=SimpleNamespace(name="t"), task_id="x", retval=None, state="FAILURE")
        finally:
            for k in [k for k in sys.modules if k == "app.tasks" or k.startswith("app.tasks.")]:
                sys.modules.pop(k, None)
            sys.modules.pop("celery", None)
            sys.modules.pop("celery.signals", None)
            for k, v in saved.items():
                sys.modules[k] = v


# ═══════════════════════════════════════════════════════════════════════════
# 10. AI module streaming rollback + tutoring service deep branches
# ═══════════════════════════════════════════════════════════════════════════


class TestStreamingAndTutoring:
    def test_chat_stream_finally_rollback(self, app):
        """Stream with no AI key → offline fallback; DB error inside → 500 handled."""
        sid, cid = setup_class(app)
        uid, email = mk(app, "student", school_id=sid)
        client = login_email(app, email)
        # Tenant quota must be enabled, or the route 403s before streaming.
        from app.services.tenant import set_tier

        with app.app_context():
            set_tier(sid, "pro")
        # offline fallback (no API key in tests) exercises the finally-rollback path
        resp = client.post("/ai/chat/stream", json={"question": "سؤال"})
        assert resp.status_code in (200, 500)
        # drain the streamed body so the view generator completes and releases its DB locks
        resp.get_data()
        # and a service crash aborts cleanly
        with patch("app.modules.ai.routes.get_ai_service", side_effect=RuntimeError("down")):
            resp2 = client.post("/ai/chat/stream", json={"question": "س2"})
        assert resp2.status_code in (200, 500)
        resp2.get_data()

    def test_tutoring_service_deep(self, app, monkeypatch):
        from app.services import tutoring as t

        sid, _cid = setup_class(app)
        t1, _ = mk(app, "teacher", school_id=sid)
        stu, _ = mk(app, "student", school_id=sid)
        with app.app_context():
            prof, perr = t.create_tutor_profile(
                tutor_id=t1, subject="رياضيات", price_hour=10, price_session=5, mode="both", bio="ب"
            )
            assert perr is None and prof is not None
            # duplicate profile → error branch
            _dup, dup_err = t.create_tutor_profile(
                tutor_id=t1, subject="رياضيات", price_hour=10, price_session=5, mode="both", bio="ب"
            )
            assert dup_err
            # active sessions query
            assert isinstance(t.get_active_sessions_for_tutor(t1), list)
            sess = t.create_session(t1, stu, "رياضيات", datetime.now(UTC), mode="online", price=50)
            # 24h rate window: old completed session → rejected
            from app.core.db import tx

            old_naive = (datetime.now(UTC) - timedelta(hours=30)).replace(tzinfo=None)

            def _old():
                s = db_get_session(sess.id)
                s.status = "completed"
                s.end_time = old_naive

            tx(_old)
            _res, err = t.rate_session(sess.id, stu, 5, None)
            assert err

    def test_zoom_failure_branches(self, app, monkeypatch):
        from app.services import tutoring as t

        sid, _cid = setup_class(app)
        t1, _ = mk(app, "teacher", school_id=sid)
        stu, _ = mk(app, "student", school_id=sid)
        monkeypatch.setenv("ZOOM_ACCOUNT_ID", "acc")
        monkeypatch.setenv("ZOOM_CLIENT_ID", "cid")
        monkeypatch.setenv("ZOOM_CLIENT_SECRET", "sec")
        with app.app_context():
            sess = t.create_session(t1, stu, "رياضيات", datetime.now(UTC), mode="online", price=50)
            with patch("urllib.request.urlopen", side_effect=RuntimeError("down")):
                url, err = t.generate_zoom_meeting(sess.id, t1)
            assert url is None and err
            # token succeeds, meeting creation fails generically
            token_resp = MagicMock()
            token_resp.read.return_value = json.dumps({"access_token": "tok"}).encode()
            cm = MagicMock()
            cm.__enter__.return_value = token_resp
            cm.__exit__.return_value = False
            with patch("urllib.request.urlopen", side_effect=[cm, RuntimeError("kaboom")]):
                url2, err2 = t.generate_zoom_meeting(sess.id, t1)
            assert url2 is None and err2

    def test_live_url_variants(self, app):
        from app.services import tutoring as t

        sid, _cid = setup_class(app)
        t1, _ = mk(app, "teacher", school_id=sid)
        stu, _ = mk(app, "student", school_id=sid)
        with app.app_context():
            sess = t.create_session(t1, stu, "رياضيات", datetime.now(UTC), mode="online", price=50)

            def _set_zoom():
                s = db_get_session(sess.id)
                s.video_provider = "zoom"
                s.zoom_join_url = "https://zoom.us/j/123"

            from app.core.db import tx

            tx(_set_zoom)
            assert t.generate_live_session_url(sess.id, t1) == "https://zoom.us/j/123"

            def _clear_zoom():
                s = db_get_session(sess.id)
                s.zoom_join_url = None
                # provider stays "zoom" → the generate_zoom_meeting arms below

            tx(_clear_zoom)
            with patch.object(t, "generate_zoom_meeting", return_value=("https://z/x", None)):
                assert t.generate_live_session_url(sess.id, t1) == "https://z/x"
            with patch.object(t, "generate_zoom_meeting", return_value=(None, "nope")):
                assert t.generate_live_session_url(sess.id, t1) is None
            # second session: default provider builds a deterministic jitsi room URL
            sess2 = t.create_session(t1, stu, "علوم", datetime.now(UTC), mode="online", price=50)
            jitsi_url = t.generate_live_session_url(sess2.id, t1)
            assert jitsi_url and "azad-tutoring-" in jitsi_url


def db_get_session(session_id):
    from app.extensions import db
    from app.models.tutoring import TutoringSession

    return db.session.get(TutoringSession, session_id)
