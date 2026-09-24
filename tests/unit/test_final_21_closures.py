"""Closure tests for the last 21 uncovered lines (one per file) from the coverage ratchet.

app/__init__.py 255            (limiter.view_functions injection)
models/user.py 69              (is_authenticated_prop)
modules/admin/routes.py 314    (impersonate while impersonating non-super)
modules/api/routes.py 473      (search: admin role with no school → filter(False))
modules/billing/routes.py 36   (_class_or_404 → abort 404)
modules/grades/routes.py 308   (report_card_pdf render branch)
modules/media/routes.py 100    (realpath traversal guard → 403)
modules/payments/routes.py 201 (verify_payment → gateway refuses → 400)
modules/progress/routes.py 49  (student_detail parent non-child → 403)
modules/schools/routes.py 32   (_school_id_or_abort abort arm)
modules/tutoring/routes.py 341 (rate window: naive end_time coercion)
services/access.py 55          (can_view_class parent direct member)
services/ai.py 30              (openai import success arm)
services/gamification.py 136   (_check_streak break on gap)
services/grade_calc.py 20      (_letter_grade fallback)
services/progress.py 73        (update_video_progress ≥90% → completed)
services/quiz_stats.py 88      (score bin "40-60")
services/rag_service.py 147    (_cosine_similarity zero-norm arm)
services/school_approvals.py 106 (reject: missing approver)
services/tutoring.py 402       (rate_session success)
services/video_service.py 222  (validate_lesson_access: class missing)
"""

from __future__ import annotations

import importlib
import sys
from datetime import UTC, datetime, timedelta
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

PASSWORD = "TestPass123!"


def _login(client, app, uid: int) -> None:
    from app.extensions import db
    from app.models.user import User

    with app.app_context():
        email = db.session.get(User, uid).email
    client.post("/auth/login", data={"email": email, "password": PASSWORD})


def _api_token(app, uid: int) -> str:
    from app.core.api_auth import make_api_token

    with app.app_context():
        return make_api_token(uid)


# ═════════════════════════════════════════════════════════════════════
# app/__init__.py:255 — limiter injection over real blueprint objects
# ═════════════════════════════════════════════════════════════════════


class TestAppFactoryLimiterInjection:
    def test_limiter_wraps_injected_view_functions(self):
        """Flask 3 leaves Blueprint.view_functions empty on @bp.route(), so the
        limiter loop in create_app never fires. Assigning view_functions
        directly on the *real* blueprints before create_app() makes the
        `limiter.limit(...)(fn)` calls run (lines 249-255)."""
        from app.modules.auth import bp as auth_bp
        from app.modules.tutoring import bp as tutoring_bp

        def login():  # pragma: no cover — never dispatched
            return "ok"

        def book():  # pragma: no cover — never dispatched
            return "ok"

        original_auth = auth_bp.view_functions
        original_tutoring = tutoring_bp.view_functions
        auth_bp.view_functions = {"login": login}
        tutoring_bp.view_functions = {"book": book}
        try:
            import app as app_pkg

            app_pkg.create_app()
        finally:
            auth_bp.view_functions = original_auth
            tutoring_bp.view_functions = original_tutoring


# ═════════════════════════════════════════════════════════════════════
# models/user.py:69 — is_authenticated_prop
# ═════════════════════════════════════════════════════════════════════


class TestUserAuthenticatedProp:
    def test_is_authenticated_prop_mirrors_is_active(self, app):
        from tests.conftest import make_user

        uid = make_user(app, role="student")
        with app.app_context():
            from app.extensions import db
            from app.models.user import User

            u = db.session.get(User, uid)
            assert u.is_authenticated_prop == u.is_active is True
            u.is_active = False
            assert u.is_authenticated_prop is False


# ═════════════════════════════════════════════════════════════════════
# modules/admin/routes.py:314 — impersonate guard measured on the impersonator
# ═════════════════════════════════════════════════════════════════════


class TestImpersonateWhileImpersonating:
    def test_impersonation_by_non_super_actor_403(self, app, client):
        """Guard passes for the logged-in super admin, but the actor measured is
        the impersonated (impersonator_id) user — a school_admin → 403."""
        from tests.conftest import make_user

        super_uid = make_user(app, role="super_admin")
        admin_uid = make_user(app, role="school_admin")
        _login(client, app, super_uid)
        with client.session_transaction() as sess:
            sess["impersonator_id"] = admin_uid
        resp = client.post(f"/admin/users/{admin_uid}/impersonate")
        assert resp.status_code == 403


# ═════════════════════════════════════════════════════════════════════
# modules/api/routes.py:473 — search else-branch (admin role, no school)
# ═════════════════════════════════════════════════════════════════════


class TestApiSearchElseBranch:
    def test_search_school_admin_without_school_users_empty(self, app, client):
        """school_admin with no school link → school_id None → else filter(False)."""
        from tests.conftest import make_user

        uid = make_user(app, role="school_admin")
        token = _api_token(app, uid)
        resp = client.get("/api/v1/search?q=ab", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.get_json()["data"]["users"] == []


# ═════════════════════════════════════════════════════════════════════
# modules/billing/routes.py:36 — _class_or_404 abort arm
# ═════════════════════════════════════════════════════════════════════


class TestBillingClassOr404:
    def test_subscribe_unknown_class_404(self, app, client):
        from tests.conftest import make_user

        uid = make_user(app, role="student")
        _login(client, app, uid)
        resp = client.post("/billing/999999/subscribe")
        assert resp.status_code == 404


# ═════════════════════════════════════════════════════════════════════
# modules/grades/routes.py:308 — report_card_pdf render branch
# ═════════════════════════════════════════════════════════════════════


class TestReportCardPdfRender:
    def test_report_card_pdf_renders_or_falls_back(self, app, client):
        """can_view_class passes for the class teacher → render_report_card_pdf
        branch runs (PDF body or flash fallback when xhtml2pdf is absent)."""
        from tests.conftest import make_class, make_grade, make_school, make_subject, make_user

        school_id = make_school(app)
        teacher_uid = make_user(app, role="teacher", school_id=school_id)
        class_id = make_class(app, school_id, make_grade(app, school_id), make_subject(app))
        _login(client, app, teacher_uid)
        resp = client.get(f"/classes/{class_id}/report-card/999999/pdf")
        assert resp.status_code in (200, 302)


# ═════════════════════════════════════════════════════════════════════
# modules/media/routes.py:100 — realpath traversal guard
# ═════════════════════════════════════════════════════════════════════


class TestMediaRealpathGuard:
    def test_stream_rejects_file_outside_media_dir(self, app, client, monkeypatch):
        from app.services.video_service import generate_stream_token
        from tests.conftest import (
            make_class,
            make_class_member,
            make_grade,
            make_lesson,
            make_school,
            make_subject,
            make_user,
        )

        school_id = make_school(app)
        uid = make_user(app, role="student", school_id=school_id)
        class_id = make_class(app, school_id, make_grade(app, school_id), make_subject(app))
        make_class_member(app, class_id, uid)
        lesson_id = make_lesson(app, class_id)
        filename = "seg0.ts"
        with app.app_context():
            token = generate_stream_token(uid, school_id, lesson_id)
        # realpath lies: the resolved file lands outside the media dir
        monkeypatch.setattr(
            "os.path.realpath",
            lambda p: "/mnt/outside" if str(p).endswith(filename) else "/mnt/media",
        )
        _login(client, app, uid)
        url = f"/media/stream/{lesson_id}/{filename}?token={token}&uid={uid}&sid={school_id}"
        assert client.get(url).status_code == 403


# ═════════════════════════════════════════════════════════════════════
# modules/payments/routes.py:201 — verify_payment refused branch
# ═════════════════════════════════════════════════════════════════════


class TestPaymentsVerifyBranches:
    def _post_verify(self, client, verified: bool):
        from app.services.payments import PaymentGateway

        gateway = SimpleNamespace(verify_payment=lambda intent, data: verified)
        service = SimpleNamespace(gateways={PaymentGateway.MANUAL: gateway})
        with patch("app.services.payments.get_payment_service", return_value=service):
            return client.post(
                "/payments/verify",
                json={"payment_id": "p-1", "gateway": "manual", "verification_data": {}},
            )

    def test_verify_payment_refused_400(self, app, client):
        from tests.conftest import make_user

        uid = make_user(app, role="student")
        _login(client, app, uid)
        resp = self._post_verify(client, verified=False)
        assert resp.status_code == 400
        assert resp.get_json()["success"] is False

    def test_verify_payment_accepted_200(self, app, client):
        from tests.conftest import make_user

        uid = make_user(app, role="student")
        _login(client, app, uid)
        resp = self._post_verify(client, verified=True)
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True


# ═════════════════════════════════════════════════════════════════════
# modules/progress/routes.py:49 — student_detail parent non-child 403
# ═════════════════════════════════════════════════════════════════════


class TestProgressStudentDetailForbidden:
    def test_parent_member_of_class_but_not_parent_of_student_403(self, app, client):
        from tests.conftest import make_class, make_class_member, make_grade, make_school, make_subject, make_user

        school_id = make_school(app)
        parent_uid = make_user(app, role="parent", school_id=school_id)
        other_uid = make_user(app, role="student", school_id=school_id)
        class_id = make_class(app, school_id, make_grade(app, school_id), make_subject(app))
        make_class_member(app, class_id, parent_uid)  # passes can_view_class…
        _login(client, app, parent_uid)
        resp = client.get(f"/progress/class/{class_id}/student/{other_uid}")
        assert resp.status_code == 403


# ═════════════════════════════════════════════════════════════════════
# modules/schools/routes.py:32 — _school_id_or_abort abort arm
# ═════════════════════════════════════════════════════════════════════


class TestSchoolIdOrAbort:
    def test_unauthenticated_request_context_aborts_403(self, app):
        from app.modules.schools.routes import _school_id_or_abort

        with app.test_request_context("/schools/"):
            with pytest.raises(Exception) as excinfo:
                _school_id_or_abort()
        assert getattr(excinfo.value, "code", None) == 403


# ═════════════════════════════════════════════════════════════════════
# modules/tutoring/routes.py:341 — rate window coercion of naive end_time
# ═════════════════════════════════════════════════════════════════════


class TestTutoringRateWindow:
    def test_rate_form_coerces_naive_end_time(self, app, client):
        """end_time naive (DB round-trip) + duration_min=0 → replace(tzinfo=UTC)
        arm executes and the GET renders the rate form."""
        from app.extensions import db
        from app.models.tutoring import TutoringSession
        from tests.conftest import make_tutoring_session, make_user

        tutor_uid = make_user(app, role="teacher")
        student_uid = make_user(app, role="student")
        sid = make_tutoring_session(app, tutor_uid, student_uid, status="completed")
        with app.app_context():
            s = db.session.get(TutoringSession, sid)
            s.end_time = (datetime.now(UTC) - timedelta(hours=1)).replace(tzinfo=None)
            s.duration_min = 0
            db.session.commit()
        _login(client, app, student_uid)
        resp = client.get(f"/tutoring/rate/{sid}")
        assert resp.status_code == 200


# ═════════════════════════════════════════════════════════════════════
# services/access.py:55 — parent direct class member
# ═════════════════════════════════════════════════════════════════════


class TestCanViewClassParentMember:
    def test_parent_direct_member_can_view(self, app):
        from app.extensions import db
        from app.models.class_room import ClassRoom
        from app.models.user import User
        from app.services.access import can_view_class
        from tests.conftest import make_class, make_class_member, make_grade, make_school, make_subject, make_user

        school_id = make_school(app)
        parent_uid = make_user(app, role="parent", school_id=school_id)
        class_id = make_class(app, school_id, make_grade(app, school_id), make_subject(app))
        make_class_member(app, class_id, parent_uid)
        with app.app_context():
            class_room = db.session.get(ClassRoom, class_id)
            user = db.session.get(User, parent_uid)
            # current_school_id() reads current_user → needs a request context
            with app.test_request_context("/"):
                assert can_view_class(class_room, user) is True


# ═════════════════════════════════════════════════════════════════════
# services/ai.py:30 — openai import success arm
# ═════════════════════════════════════════════════════════════════════


class TestAiOpenAIImport:
    def test_openai_available_true_with_fake_module(self):
        """Injecting a fake `openai` module makes the import succeed →
        OPENAI_AVAILABLE True; restore afterwards."""
        import app.services.ai as ai_module

        fake = ModuleType("openai")
        fake.AsyncOpenAI = object  # the only name the module imports
        saved = sys.modules.get("openai")
        sys.modules["openai"] = fake
        try:
            importlib.reload(ai_module)
            assert ai_module.OPENAI_AVAILABLE is True
            assert ai_module.AsyncOpenAI is object
        finally:
            if saved is None:
                sys.modules.pop("openai", None)
            else:
                sys.modules["openai"] = saved
            importlib.reload(ai_module)
        from importlib.util import find_spec

        assert ai_module.OPENAI_AVAILABLE is (find_spec("openai") is not None)


# ═════════════════════════════════════════════════════════════════════
# services/gamification.py:136 — _check_streak break on gap
# ═════════════════════════════════════════════════════════════════════


class TestCheckStreakGap:
    def test_streak_breaks_on_non_consecutive_days(self, app):
        from app.extensions import db
        from app.models.progress import StudentProgress
        from app.services.gamification import _check_streak
        from tests.conftest import make_class, make_grade, make_lesson, make_school, make_subject, make_user

        uid = make_user(app, role="student")
        school_id = make_school(app)
        class_id = make_class(app, school_id, make_grade(app, school_id), make_subject(app))
        # two distinct lessons: (student_id, lesson_id) is unique per progress row
        lesson_ids = [make_lesson(app, class_id), make_lesson(app, class_id)]
        with app.app_context():
            today = datetime.now(UTC).date()
            base = datetime(today.year, today.month, today.day, 12, 0, tzinfo=UTC)
            for delta, lesson_id in zip((1, 5), lesson_ids, strict=True):  # gap → break at i=1
                db.session.add(
                    StudentProgress(
                        student_id=uid,
                        lesson_id=lesson_id,
                        class_id=class_id,
                        status="completed",
                        completed_at=base - timedelta(days=delta),
                    )
                )
            db.session.commit()
            assert _check_streak(uid, 2) is False


# ═════════════════════════════════════════════════════════════════════
# services/grade_calc.py:20 — _letter_grade fallback arm
# ═════════════════════════════════════════════════════════════════════


class TestLetterGradeFallback:
    def test_negative_score_falls_back_to_fail(self):
        from app.services.grade_calc import _letter_grade

        assert _letter_grade(-1.0) == "راسب"


# ═════════════════════════════════════════════════════════════════════
# services/progress.py:73 — update_video_progress ≥90% arm
# ═════════════════════════════════════════════════════════════════════


class TestUpdateVideoProgressCompletion:
    def test_second_update_crosses_90pct_marks_completed(self, app):
        from app.models.progress import VideoProgress
        from app.services.progress import update_video_progress
        from tests.conftest import (
            make_attachment,
            make_class,
            make_grade,
            make_lesson,
            make_school,
            make_subject,
            make_user,
        )

        school_id = make_school(app)
        uid = make_user(app, role="student")
        class_id = make_class(app, school_id, make_grade(app, school_id), make_subject(app))
        lesson_id = make_lesson(app, class_id)
        attachment_id = make_attachment(app, lesson_id)
        with app.app_context():
            update_video_progress(uid, attachment_id, lesson_id, class_id, 100, 200)
            update_video_progress(uid, attachment_id, lesson_id, class_id, 190, 200)
            vp = VideoProgress.query.filter_by(student_id=uid, attachment_id=attachment_id).first()
            assert vp.seconds_watched == 190
            assert vp.completed is True


# ═════════════════════════════════════════════════════════════════════
# services/quiz_stats.py:88 — score bin "40-60"
# ═════════════════════════════════════════════════════════════════════


class TestQuizStatsScoreBins:
    def test_half_correct_lands_in_40_60_bin(self, app):
        from app.services.assessment import add_question, create_quiz, save_answer, start_attempt, submit_attempt
        from app.services.quiz_stats import get_quiz_stats
        from tests.conftest import make_class, make_grade, make_school, make_subject, make_user

        school_id = make_school(app)
        class_id = make_class(app, school_id, make_grade(app, school_id), make_subject(app))
        uid = make_user(app, role="student")
        with app.app_context():
            quiz, _ = create_quiz(class_id, "Bin Quiz")
            q1 = add_question(quiz, "mcq", "س1", {"options": ["أ", "ب"]}, {"index": 0}, mark=10)
            q2 = add_question(quiz, "mcq", "س2", {"options": ["أ", "ب"]}, {"index": 0}, mark=10)
            attempt, _ = start_attempt(quiz, uid)
            save_answer(attempt, q1.id, {"index": 0})  # correct
            save_answer(attempt, q2.id, {"index": 1})  # wrong
            submit_attempt(attempt, allow_after_deadline=True)
            stats = get_quiz_stats(quiz.id)
        assert stats.score_distribution["40-60"] == 1


# ═════════════════════════════════════════════════════════════════════
# services/rag_service.py:147 — zero-norm cosine arm
# ═════════════════════════════════════════════════════════════════════


class TestCosineSimilarityZeroNorm:
    def test_all_zero_vectors_return_zero(self):
        from app.services.rag_service import _cosine_similarity

        assert _cosine_similarity({"a": 0.0}, {"a": 0.0}) == 0.0


# ═════════════════════════════════════════════════════════════════════
# services/school_approvals.py:106 — reject with missing approver
# ═════════════════════════════════════════════════════════════════════


class TestRejectApproverMissing:
    def test_reject_with_nonexistent_approver(self, app):
        from tests.conftest import make_school, make_user

        school_id = make_school(app)
        uid = make_user(app, role="teacher", school_id=school_id, approved=False)
        from app.services.school_approvals import reject_user_role_link

        with app.app_context():
            from app.models.user import UserRoleLink

            link = UserRoleLink.query.filter_by(user_id=uid, school_id=school_id).first()
            ok, err = reject_user_role_link(link.id, 999999)
            assert ok is False
            assert err is not None


# ═════════════════════════════════════════════════════════════════════
# services/tutoring.py:402 — rate_session success path
# ═════════════════════════════════════════════════════════════════════


class TestRateSessionSuccess:
    def test_rate_session_creates_review(self, app):
        from app.extensions import db
        from app.models.tutoring import TutoringSession
        from app.services.tutoring import rate_session
        from tests.conftest import make_tutoring_session, make_user

        tutor_uid = make_user(app, role="teacher")
        student_uid = make_user(app, role="student")
        sid = make_tutoring_session(app, tutor_uid, student_uid, status="completed")
        with app.app_context():
            s = db.session.get(TutoringSession, sid)
            s.end_time = (datetime.now(UTC) - timedelta(hours=1)).replace(tzinfo=None)
            s.duration_min = 0
            db.session.commit()
            review, err = rate_session(sid, student_uid, 5)
            assert err is None
            assert review is not None
            assert review.rating == 5


# ═════════════════════════════════════════════════════════════════════
# services/video_service.py:222 — validate_lesson_access class missing
# ═════════════════════════════════════════════════════════════════════


class TestValidateLessonAccessMissingClass:
    def test_lesson_with_missing_class_denied(self, app):
        from app.extensions import db
        from app.services.video_service import validate_lesson_access

        with app.app_context():
            lesson = SimpleNamespace(class_id=424242)
            with patch.object(
                db.session,
                "get",
                side_effect=[lesson, None],
            ):
                allowed, error = validate_lesson_access(1, 1, 12345)
        assert allowed is False
        assert error == "Class not found"
