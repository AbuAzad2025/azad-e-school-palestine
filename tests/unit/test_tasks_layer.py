"""Batch 2 — app/tasks layer coverage (real task bodies, real DB/file effects).

Runs under the fake-celery harness (celery not installed locally/CI): task
modules import with @celery_app.task as identity, so task functions execute
directly. `bind=True` tasks are called with a dummy self (only used for
retry() on failure paths — not hit in the success paths asserted here).

Covers:
- grading.auto_grade_quiz_attempt: real MCQ/true_false grading via the shared
  _grade_answer contract, skip/nonexistent branches, essay left ungraded.
- notifications.dispatch_notification / bulk_dispatch_school_announcement:
  real Notification rows, tenancy-scoped bulk send, role filter, missing user.
- reports.generate_report_card / generate_class_report / generate_invoice:
  real grade data, real JSON artifacts on disk, failed-subscription branch.
- video.transcode_video_to_hls guardrails: missing source, bad probe.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from tests.conftest import (
    make_class,
    make_class_member,
    make_grade,
    make_school,
    make_subject,
    make_user,
)


@pytest.fixture(scope="module", autouse=True)
def _fake_celery():
    """Import task modules with @celery_app.task neutralized (identity).

    Celery is intentionally not installed; patching the module-level names
    lets the real task bodies import and run as plain functions.
    """
    with (
        patch("app.tasks._HAS_CELERY", True),
        patch("app.tasks.celery_app") as mock_celery,
    ):

        def _task_dec(*a, **kw):
            """Handle both @task and @task(...) — always preserve the function."""
            if a:  # bare @celery_app.task — a[0] is the function
                return a[0]
            return lambda f: f  # @celery_app.task(**kwargs) factory form

        mock_celery.task.side_effect = _task_dec
        from app.tasks import grading, notifications, reports, video  # noqa: F401

        yield


def _self():
    """Dummy bound-task self: retry() is only reached on error paths."""
    m = MagicMock()
    m.retry.side_effect = RuntimeError("retry-should-not-fire")
    return m


# ═══════════════════════════════════════════════════════════════════════════
# grading.auto_grade_quiz_attempt
# ═══════════════════════════════════════════════════════════════════════════


def _quiz_with_questions(app, school_id, student_id):
    """Build a real submitted attempt with 1 MCQ (correct+wrong) + essay."""
    from app.extensions import db
    from app.models.assessment import Answer, Question, Quiz, QuizAttempt

    gid = make_grade(app, school_id)
    sub = make_subject(app)
    cid = make_class(app, school_id, gid, sub)
    quiz = Quiz(class_id=cid, title="اختبار", status="published", attempts_allowed=1)
    db.session.add(quiz)
    db.session.flush()
    q1 = Question(
        quiz_id=quiz.id,
        type="mcq",
        prompt="2+2؟",
        options={"a": "3", "b": "4"},
        correct_answer={"index": 1},
        mark=Decimal("5"),
        sort_order=1,
    )
    q2 = Question(
        quiz_id=quiz.id,
        type="true_false",
        prompt="الشمس نجم",
        correct_answer={"value": True},
        mark=Decimal("5"),
        sort_order=2,
    )
    q3 = Question(quiz_id=quiz.id, type="essay", prompt="اشرح", mark=Decimal("10"), sort_order=3)
    db.session.add_all([q1, q2, q3])
    db.session.flush()

    attempt = QuizAttempt(
        quiz_id=quiz.id,
        student_id=student_id,
        attempt_no=1,
        status="submitted",
        started_at=datetime.now(UTC),
        submitted_at=datetime.now(UTC),
    )
    db.session.add(attempt)
    db.session.flush()
    db.session.add_all(
        [
            Answer(attempt_id=attempt.id, question_id=q1.id, answer={"index": 1}),  # correct
            Answer(attempt_id=attempt.id, question_id=q2.id, answer={"value": False}),  # wrong
            Answer(attempt_id=attempt.id, question_id=q3.id, answer={"text": "نص"}),
        ]
    )
    db.session.commit()
    return quiz.id, attempt.id


class TestAutoGrade:
    def test_grades_real_attempt_correctly(self, app):
        from app.tasks.grading import auto_grade_quiz_attempt

        sid = make_school(app)
        student_id = make_user(app, role="student", school_id=sid)
        with app.app_context():
            quiz_id, attempt_id = _quiz_with_questions(app, sid, student_id)

            result = auto_grade_quiz_attempt(_self(), attempt_id)

            assert result["status"] == "completed"
            assert result["error"] is None
            assert result["score"] == 5.0  # mcq ✓ (5) + true_false ✗ (0) + essay manual

            from app.extensions import db
            from app.models.assessment import Answer, QuizAttempt

            att = db.session.get(QuizAttempt, attempt_id)
            assert att.status == "graded"
            graded = {a.question_id: a for a in Answer.query.filter_by(attempt_id=attempt_id)}
            marks = {float(a.awarded_mark) if a.awarded_mark is not None else None for a in graded.values()}
            assert marks == {5.0, 0.0, None}  # mcq ✓, true_false ✗, essay manual

    def test_skips_non_submitted_attempt(self, app):
        from app.extensions import db
        from app.models.assessment import Quiz, QuizAttempt
        from app.tasks.grading import auto_grade_quiz_attempt

        sid = make_school(app)
        student_id = make_user(app, role="student", school_id=sid)
        with app.app_context():
            gid = make_grade(app, sid)
            cid = make_class(app, sid, gid, make_subject(app))
            quiz = Quiz(class_id=cid, title="t", status="published")
            db.session.add(quiz)
            db.session.flush()
            att = QuizAttempt(quiz_id=quiz.id, student_id=student_id, attempt_no=1, status="in_progress")
            db.session.add(att)
            db.session.commit()

            result = auto_grade_quiz_attempt(_self(), att.id)
            assert result["status"] == "skipped"
            assert result["error"] == "Not in submitted status"

    def test_missing_attempt_reports_failed(self, app):
        from app.tasks.grading import auto_grade_quiz_attempt

        with app.app_context():
            result = auto_grade_quiz_attempt(_self(), 999_999)
            assert result["status"] == "failed"
            assert "not found" in result["error"].lower()


# ═══════════════════════════════════════════════════════════════════════════
# notifications
# ═══════════════════════════════════════════════════════════════════════════


class TestNotificationTasks:
    def test_dispatch_notification_creates_row(self, app):
        from app.extensions import db
        from app.models.communication import Notification
        from app.tasks.notifications import dispatch_notification

        sid = make_school(app)
        user_id = make_user(app, role="student", school_id=sid)
        with app.app_context():
            result = dispatch_notification(_self(), user_id, "grade", "درجة جديدة", body="رياضيات", link="/grades")
            assert result["success"] is True
            assert result["error"] is None
            row = db.session.get(Notification, result["notification_id"])
            assert row is not None
            assert row.type == "grade" and row.link == "/grades"

    def test_dispatch_notification_missing_user(self, app):
        from app.tasks.notifications import dispatch_notification

        with app.app_context():
            result = dispatch_notification(_self(), 987_654, "grade", "t")
            assert result["success"] is False
            assert result["error"] == "User not found"

    def test_bulk_announcement_scoped_to_school(self, app):
        from app.models.communication import Notification
        from app.tasks.notifications import bulk_dispatch_school_announcement

        sid_a = make_school(app)
        sid_b = make_school(app)
        ua_id = make_user(app, role="student", school_id=sid_a)
        ub_id = make_user(app, role="student", school_id=sid_b)
        with app.app_context():
            result = bulk_dispatch_school_announcement(_self(), sid_a, "عنوان", "نص")
            assert result["success"] is True
            assert result["sent_count"] == 1  # only school A's student
            assert result["errors"] == []
            ids = [n.user_id for n in Notification.query.filter_by(type="announcement")]
            assert ua_id in ids and ub_id not in ids  # tenant isolation

    def test_bulk_announcement_role_filter(self, app):
        from app.models.communication import Notification
        from app.tasks.notifications import bulk_dispatch_school_announcement

        sid = make_school(app)
        make_user(app, role="student", school_id=sid)
        teacher_id = make_user(app, role="teacher", school_id=sid)
        with app.app_context():
            result = bulk_dispatch_school_announcement(_self(), sid, "اجتماع", "المعلمون فقط", recipient_role="teacher")
            assert result["sent_count"] == 1
            rows = Notification.query.filter_by(type="announcement").all()
            assert [r.user_id for r in rows] == [teacher_id]

    def test_bulk_announcement_empty_school(self, app):
        from app.tasks.notifications import bulk_dispatch_school_announcement

        sid = make_school(app)
        with app.app_context():
            result = bulk_dispatch_school_announcement(_self(), sid, "t", "b")
            assert result["success"] is True and result["sent_count"] == 0

    def test_dispatch_email_missing_user(self, app):
        from app.tasks.notifications import dispatch_email_notification

        with app.app_context():
            result = dispatch_email_notification(_self(), 424_242, "s", "<p>b</p>")
            assert result["success"] is False
            assert result["error"] == "User not found"

    def test_dispatch_email_sends_via_email_service(self, app):
        from app.extensions import db
        from app.tasks.notifications import dispatch_email_notification

        sid = make_school(app)
        user_id = make_user(app, role="student", school_id=sid)
        with app.app_context():
            sent: dict = {}

            def fake_send(to, subject, html_body, **kw):
                sent.update(to=to, subject=subject)
                return True

            from app.models.user import User

            email = db.session.get(User, user_id).email
            with patch("app.services.email._send", side_effect=fake_send):
                result = dispatch_email_notification(_self(), user_id, "مرحبا", "<p>نص</p>")
            assert result["success"] is True
            assert sent["to"] == email and sent["subject"] == "مرحبا"


# ═══════════════════════════════════════════════════════════════════════════
# reports
# ═══════════════════════════════════════════════════════════════════════════


class TestReportTasks:
    def test_generate_report_card_writes_artifact(self, app):
        from app.tasks.reports import generate_report_card

        sid = make_school(app)
        student_id = make_user(app, role="student", school_id=sid)
        with app.app_context():
            gid = make_grade(app, sid)
            cid = make_class(app, sid, gid, make_subject(app))
            with patch("app.services.grade_calc.calculate_student_grade", return_value={"total": 88.5}):
                result = generate_report_card(_self(), student_id, cid, sid)

            assert result["status"] == "completed" and result["error"] is None
            with open(result["file_path"], encoding="utf-8") as f:
                data = json.load(f)
            assert data["student_id"] == student_id
            assert data["grade_data"] == {"total": 88.5}

    def test_generate_class_report_counts_students(self, app):
        from app.tasks.reports import generate_class_report

        sid = make_school(app)
        with app.app_context():
            gid = make_grade(app, sid)
            cid = make_class(app, sid, gid, make_subject(app))
            u1_id = make_user(app, role="student", school_id=sid)
            make_class_member(app, cid, u1_id)
            u2_id = make_user(app, role="student", school_id=sid)
            make_class_member(app, cid, u2_id)

            result = generate_class_report(_self(), cid, sid)
            assert result["status"] == "completed"
            assert result["student_count"] == 2
            with open(result["file_path"], encoding="utf-8") as f:
                data = json.load(f)
            assert data["student_count"] == 2

    def test_generate_invoice_missing_subscription(self, app):
        from app.tasks.reports import generate_invoice

        with app.app_context():
            result = generate_invoice(_self(), 555_555, 1)
            assert result["status"] == "failed"
            assert result["error"] == "Subscription not found"

    def test_generate_invoice_writes_artifact(self, app):
        from app.extensions import db
        from app.models.billing import ManualPayment, Subscription, SubscriptionPlan
        from app.tasks.reports import generate_invoice

        sid = make_school(app)
        student_id = make_user(app, role="student", school_id=sid)
        with app.app_context():
            gid = make_grade(app, sid)
            cid = make_class(app, sid, gid, make_subject(app))
            plan = SubscriptionPlan(school_id=sid, name="ترم أول", plan="first_term", price=Decimal("100"))
            db.session.add(plan)
            db.session.flush()
            sub = Subscription(
                user_id=student_id,
                plan_id=plan.id,
                class_id=cid,
                price=Decimal("100"),
                currency="ILS",
                status="active",
            )
            db.session.add(sub)
            db.session.flush()
            pay = ManualPayment(subscription_id=sub.id, reference="REF-1", amount=Decimal("100"), status="approved")
            db.session.add(pay)
            db.session.commit()

            result = generate_invoice(_self(), sub.id, sid)
            assert result["status"] == "completed"
            with open(result["file_path"], encoding="utf-8") as f:
                data = json.load(f)
            assert data["subscription_id"] == sub.id
            assert data["payments"][0]["id"] == pay.id


# ═══════════════════════════════════════════════════════════════════════════
# video — guardrail branches (full pipeline needs ffmpeg; helpers already covered)
# ═══════════════════════════════════════════════════════════════════════════


class TestVideoTaskGuardrails:
    def test_missing_source_fails_fast(self, app):
        from app.tasks.video import transcode_video_to_hls

        with app.app_context():
            result = transcode_video_to_hls(_self(), 1, "/nonexistent/src.mp4", 1)
            assert result["status"] == "failed"
            assert "not found" in result["error"]

    def test_bad_probe_fails_before_transcode(self, app, tmp_path):
        from app.tasks.video import transcode_video_to_hls

        p = tmp_path / "fake.mp4"
        p.write_bytes(b"not a video")
        with app.app_context():
            result = transcode_video_to_hls(_self(), 1, str(p), 1)
            assert result["status"] == "failed"
            assert "invalid" in result["error"].lower() or "probe" in result["error"].lower()
