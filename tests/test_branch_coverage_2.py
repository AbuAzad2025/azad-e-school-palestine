"""Second batch branch coverage tests — targets db.py tx() internals,
gamification.py badge criteria branches, assessment.py deadline checks,
billing.py discount edge cases, messages.py thread/sent/inbox,
tutoring.py zoom error paths, grade_appeals.py, and progress edge cases.

Focus: if/elif/else, try/except, short-circuit branches not covered in batch 1.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import (
    make_attachment,
    make_class,
    make_class_member,
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
    make_user,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return f"_{int(time.time()*1000000)}"


def _make_student(app, school_id=None):
    uid = make_user(app, role="student", school_id=school_id)
    return uid


def _make_teacher(app, school_id):
    return make_user(app, role="teacher", school_id=school_id)


def _make_super_admin(app):
    return make_user(app, role="super_admin")


# ===========================================================================
# DB.PY — tx() rollback paths, nested tx, hook failure, expiry
# ===========================================================================

class TestTxRollbackPaths:
    """db.py — exercise every except branch in tx()."""

    def test_tx_success(self, app):
        from app.core.db import tx
        with app.app_context():
            result = tx(lambda: 42)
            assert result == 42

    def test_txTxError_rollback(self, app):
        from app.core.db import TxError, tx
        with app.app_context():
            with pytest.raises(TxError):
                tx(lambda: (_ for _ in ()).throw(TxError("business error")))

    def test_txUnexpectedException_rollback(self, app):
        from app.core.db import tx
        with app.app_context():
            with pytest.raises(RuntimeError):
                tx(lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    def test_tx_on_commit_fires_after_success(self, app):
        from app.core.db import tx, tx_on_commit
        with app.app_context():
            called = []
            def _do():
                tx_on_commit(lambda: called.append("fired"))
                return "ok"
            tx(_do)
            assert called == ["fired"]

    def test_tx_on_commit_DiscardedOnFailure(self, app):
        from app.core.db import TxError, tx, tx_on_commit
        with app.app_context():
            called = []
            def _do():
                tx_on_commit(lambda: called.append("should_not_fire"))
                raise TxError("fail")
            with pytest.raises(TxError):
                tx(_do)
            assert called == []

    def test_tx_on_commit_HookErrorDoesNotCrash(self, app):
        from app.core.db import tx, tx_on_commit
        with app.app_context():
            def _bad_hook():
                raise RuntimeError("hook failed")
            tx_on_commit(_bad_hook)
            # Should not raise — hook failures are logged, not propagated
            tx(lambda: "ok")

    def test_tx_nestedUsesSavepoint(self, app):
        from app.core.db import tx
        with app.app_context():
            results = []
            def inner():
                results.append("inner")
                return "inner_result"
            def outer():
                r = tx(inner)
                results.append("outer")
                return r
            result = tx(outer)
            assert result == "inner_result"
            assert "inner" in results
            assert "outer" in results

    def test_tx_nestedTxErrorRollsBackInner(self, app):
        from app.core.db import TxError, tx
        with app.app_context():
            def inner():
                raise TxError("inner fail")
            def outer():
                try:
                    tx(inner)
                except TxError:
                    pass
                return "outer_continues"
            result = tx(outer)
            assert result == "outer_continues"


# ===========================================================================
# GAMIFICATION — all badge criteria types + _check_streak + _check_course_complete
# ===========================================================================

class TestGamificationBranches:
    """gamification.py — exercise all BadgeCriteriaType branches."""

    def _make_badge(self, app, criteria_type, name="Badge"):
        from app.extensions import db
        from app.models.gamification import Badge
        with app.app_context():
            badge = Badge(name=name, icon_name="star", criteria_type=criteria_type, is_active=True)
            db.session.add(badge)
            db.session.commit()
            return badge.id

    def test_get_active_badges(self, app):
        from app.services.gamification import get_active_badges
        bid = self._make_badge(app, "first_quiz")
        with app.app_context():
            badges = get_active_badges()
            assert any(b.id == bid for b in badges)

    def test_has_badge_false(self, app):
        from app.services.gamification import has_badge
        uid = make_user(app, role="student")
        bid = self._make_badge(app, "first_quiz")
        with app.app_context():
            assert has_badge(uid, bid) is False

    def test_has_badge_true(self, app):
        from app.services.gamification import award_badge, has_badge
        uid = make_user(app, role="student")
        bid = self._make_badge(app, "first_quiz")
        with app.app_context():
            award_badge(uid, bid)
            assert has_badge(uid, bid) is True

    def test_award_badge_duplicate_returns_none(self, app):
        from app.services.gamification import award_badge
        uid = make_user(app, role="student")
        bid = self._make_badge(app, "first_quiz")
        with app.app_context():
            award_badge(uid, bid)
            result = award_badge(uid, bid)
            assert result is None

    def test_get_student_badges(self, app):
        from app.services.gamification import award_badge, get_student_badges
        uid = make_user(app, role="student")
        bid = self._make_badge(app, "first_quiz", name="First Quiz")
        with app.app_context():
            award_badge(uid, bid)
            badges = get_student_badges(uid)
            assert len(badges) >= 1

    def test_first_quiz_badge_awarded(self, app):
        from app.services.gamification import check_and_award_badges
        uid = make_user(app, role="student")
        bid = self._make_badge(app, "first_quiz", name="First Quiz")
        with app.app_context():
            new = check_and_award_badges(uid, "quiz_submitted")
            assert len(new) >= 1

    def test_first_quiz_wrong_event_no_award(self, app):
        from app.services.gamification import check_and_award_badges
        uid = make_user(app, role="student")
        bid = self._make_badge(app, "first_quiz", name="First Quiz")
        with app.app_context():
            new = check_and_award_badges(uid, "lesson_completed")
            assert len(new) == 0

    def test_perfect_score_badge_awarded(self, app):
        from app.services.gamification import check_and_award_badges
        uid = make_user(app, role="student")
        bid = self._make_badge(app, "perfect_score", name="Perfect")
        with app.app_context():
            new = check_and_award_badges(uid, "quiz_submitted", {"score": 100, "max_score": 100})
            assert len(new) >= 1

    def test_perfect_score_not_perfect_no_award(self, app):
        from app.services.gamification import check_and_award_badges
        uid = make_user(app, role="student")
        bid = self._make_badge(app, "perfect_score", name="Perfect")
        with app.app_context():
            new = check_and_award_badges(uid, "quiz_submitted", {"score": 80, "max_score": 100})
            assert len(new) == 0

    def test_perfect_score_no_data_no_award(self, app):
        from app.services.gamification import check_and_award_badges
        uid = make_user(app, role="student")
        bid = self._make_badge(app, "perfect_score", name="Perfect")
        with app.app_context():
            new = check_and_award_badges(uid, "quiz_submitted")
            assert len(new) == 0

    def test_perfect_score_missing_max_score(self, app):
        from app.services.gamification import check_and_award_badges
        uid = make_user(app, role="student")
        bid = self._make_badge(app, "perfect_score", name="Perfect")
        with app.app_context():
            new = check_and_award_badges(uid, "quiz_submitted", {"score": 100})
            assert len(new) == 0

    def test_perfect_score_missing_score(self, app):
        from app.services.gamification import check_and_award_badges
        uid = make_user(app, role="student")
        bid = self._make_badge(app, "perfect_score", name="Perfect")
        with app.app_context():
            new = check_and_award_badges(uid, "quiz_submitted", {"max_score": 100})
            assert len(new) == 0

    def test_streak_badge_insufficient_days(self, app):
        from app.services.gamification import check_and_award_badges
        uid = make_user(app, role="student")
        bid = self._make_badge(app, "streak_7_days", name="Streak")
        with app.app_context():
            new = check_and_award_badges(uid, "any_event")
            assert len(new) == 0

    def test_course_complete_no_class_id(self, app):
        from app.services.gamification import check_and_award_badges
        uid = make_user(app, role="student")
        bid = self._make_badge(app, "course_complete", name="Complete")
        with app.app_context():
            new = check_and_award_badges(uid, "lesson_completed", {})
            assert len(new) == 0

    def test_course_complete_zero_lessons(self, app):
        from app.services.gamification import check_and_award_badges
        from app.extensions import db
        uid = make_user(app, role="student")
        bid = self._make_badge(app, "course_complete", name="Complete")
        sid = make_school(app)
        cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
        with app.app_context():
            new = check_and_award_badges(uid, "lesson_completed", {"class_id": cid})
            assert len(new) == 0

    def test_course_complete_not_all_done(self, app):
        from app.services.gamification import check_and_award_badges
        from app.extensions import db
        from app.models.content import Lesson
        from app.models.progress import StudentProgress
        uid = make_user(app, role="student")
        bid = self._make_badge(app, "course_complete", name="Complete")
        sid = make_school(app)
        cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
        lid1 = make_lesson(app, cid)
        lid2 = make_lesson(app, cid)
        with app.app_context():
            sp = StudentProgress(student_id=uid, lesson_id=lid1, class_id=cid, status="completed")
            db.session.add(sp)
            db.session.commit()
            new = check_and_award_badges(uid, "lesson_completed", {"class_id": cid})
            assert len(new) == 0

    def test_early_bird_badge(self, app):
        from app.services.gamification import check_and_award_badges
        uid = make_user(app, role="student")
        bid = self._make_badge(app, "early_bird", name="Early Bird")
        now = datetime.now(UTC)
        deadline = (now + timedelta(hours=48)).isoformat()
        submitted = now.isoformat()
        with app.app_context():
            new = check_and_award_badges(uid, "assignment_submitted", {
                "deadline": deadline,
                "submitted_at": submitted,
            })
            assert len(new) >= 1

    def test_early_bird_too_late_no_award(self, app):
        from app.services.gamification import check_and_award_badges
        uid = make_user(app, role="student")
        bid = self._make_badge(app, "early_bird", name="Early Bird")
        now = datetime.now(UTC)
        deadline = (now + timedelta(hours=12)).isoformat()
        submitted = now.isoformat()
        with app.app_context():
            new = check_and_award_badges(uid, "assignment_submitted", {
                "deadline": deadline,
                "submitted_at": submitted,
            })
            assert len(new) == 0

    def test_early_bird_no_deadline_data(self, app):
        from app.services.gamification import check_and_award_badges
        uid = make_user(app, role="student")
        bid = self._make_badge(app, "early_bird", name="Early Bird")
        with app.app_context():
            new = check_and_award_badges(uid, "assignment_submitted", {})
            assert len(new) == 0

    def test_early_bird_wrong_event(self, app):
        from app.services.gamification import check_and_award_badges
        uid = make_user(app, role="student")
        bid = self._make_badge(app, "early_bird", name="Early Bird")
        with app.app_context():
            new = check_and_award_badges(uid, "quiz_submitted")
            assert len(new) == 0

    def test_already_earned_not_duplicated(self, app):
        from app.services.gamification import award_badge, check_and_award_badges
        uid = make_user(app, role="student")
        bid = self._make_badge(app, "first_quiz", name="First Quiz")
        with app.app_context():
            award_badge(uid, bid)
            new = check_and_award_badges(uid, "quiz_submitted")
            assert len(new) == 0


# ===========================================================================
# ASSESSMENT — deadline_exceeded branches, save_answer deadline, essay grade
# ===========================================================================

class TestAssessmentDeadlineBranches:
    """assessment.py — deadline_exceeded, save_answer, grade_essay."""

    def _make_quiz(self, app, duration_min=None):
        """Create a quiz with proper FKs and return (quiz_id, class_id, student_id)."""
        from app.extensions import db
        from app.models.assessment import Quiz
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            q = Quiz(class_id=cid, title="Test Quiz", duration_min=duration_min)
            db.session.add(q)
            db.session.commit()
            return q.id, cid, uid

    def test_deadline_exceeded_no_duration(self, app):
        from app.services.assessment import deadline_exceeded
        from app.models.assessment import QuizAttempt, Quiz
        with app.app_context():
            qid, cid, uid = self._make_quiz(app, duration_min=None)
            q = db.session.get(Quiz, qid)
            attempt = QuizAttempt(quiz=q, student_id=uid, status="in_progress")
            assert deadline_exceeded(attempt) is False

    def test_deadline_exceeded_no_started_at(self, app):
        from app.services.assessment import deadline_exceeded
        from app.models.assessment import QuizAttempt, Quiz
        with app.app_context():
            qid, cid, uid = self._make_quiz(app, duration_min=30)
            q = db.session.get(Quiz, qid)
            attempt = QuizAttempt(quiz=q, student_id=uid, status="in_progress", started_at=None)
            assert deadline_exceeded(attempt) is False

    def test_deadline_not_exceeded(self, app):
        from app.services.assessment import deadline_exceeded
        from app.models.assessment import QuizAttempt, Quiz
        with app.app_context():
            qid, cid, uid = self._make_quiz(app, duration_min=60)
            q = db.session.get(Quiz, qid)
            attempt = QuizAttempt(
                quiz=q, student_id=uid, status="in_progress",
                started_at=datetime.now(UTC) - timedelta(minutes=5),
            )
            assert deadline_exceeded(attempt) is False

    def test_deadline_exceeded(self, app):
        from app.services.assessment import deadline_exceeded
        from app.models.assessment import QuizAttempt, Quiz
        with app.app_context():
            qid, cid, uid = self._make_quiz(app, duration_min=5)
            q = db.session.get(Quiz, qid)
            attempt = QuizAttempt(
                quiz=q, student_id=uid, status="in_progress",
                started_at=datetime.now(UTC) - timedelta(minutes=10),
            )
            assert deadline_exceeded(attempt) is True

    def test_save_answer_deadline_exceeded(self, app):
        from app.services.assessment import save_answer
        from app.core.db import TxError
        from app.models.assessment import QuizAttempt, Quiz
        with app.app_context():
            qid, cid, uid = self._make_quiz(app, duration_min=1)
            q = db.session.get(Quiz, qid)
            attempt = QuizAttempt(
                quiz=q, student_id=uid, status="in_progress",
                started_at=datetime.now(UTC) - timedelta(minutes=5),
            )
            with pytest.raises(TxError):
                save_answer(attempt, 1, {"index": 0})

    def test_save_answer_already_submitted(self, app):
        from app.services.assessment import save_answer
        from app.core.db import TxError
        from app.models.assessment import QuizAttempt, Quiz
        with app.app_context():
            qid, cid, uid = self._make_quiz(app)
            q = db.session.get(Quiz, qid)
            attempt = QuizAttempt(quiz=q, student_id=uid, status="submitted")
            with pytest.raises(TxError):
                save_answer(attempt, 1, {"index": 0})

    def test_save_answer_upsert_existing(self, app):
        from app.services.assessment import save_answer
        from app.models.assessment import QuizAttempt, Quiz, Question, Answer
        with app.app_context():
            qid, cid, uid = self._make_quiz(app)
            q = db.session.get(Quiz, qid)
            question = Question(quiz_id=q.id, type="mcq", prompt="X")
            db.session.add(question)
            db.session.flush()
            attempt = QuizAttempt(quiz_id=q.id, student_id=uid, status="in_progress", started_at=datetime.now(UTC))
            db.session.add(attempt)
            db.session.flush()
            existing = Answer(attempt_id=attempt.id, question_id=question.id, answer={"index": 0})
            db.session.add(existing)
            db.session.commit()
            save_answer(attempt, question.id, {"index": 1})
            updated = db.session.get(Answer, existing.id)
            assert updated.answer == {"index": 1}

    def test_grade_essay_with_mark(self, app):
        from app.services.assessment import grade_essay
        from app.models.assessment import QuizAttempt, Quiz, Question, Answer
        with app.app_context():
            qid, cid, uid = self._make_quiz(app)
            q = db.session.get(Quiz, qid)
            question = Question(quiz_id=q.id, type="essay", prompt="Write", mark=20)
            db.session.add(question)
            db.session.flush()
            attempt = QuizAttempt(quiz_id=q.id, student_id=uid, status="in_progress",
                                   started_at=datetime.now(UTC))
            db.session.add(attempt)
            db.session.flush()
            ans = Answer(attempt_id=attempt.id, question_id=question.id,
                          answer={"text": "essay"}, is_correct=None, awarded_mark=None)
            db.session.add(ans)
            db.session.commit()
            grade_essay(ans, 15.0)
            assert ans.awarded_mark == 15.0
            assert ans.is_correct is True

    def test_grade_essay_zero_mark(self, app):
        from app.services.assessment import grade_essay
        from app.models.assessment import QuizAttempt, Quiz, Question, Answer
        with app.app_context():
            qid, cid, uid = self._make_quiz(app)
            q = db.session.get(Quiz, qid)
            question = Question(quiz_id=q.id, type="essay", prompt="Write", mark=20)
            db.session.add(question)
            db.session.flush()
            attempt = QuizAttempt(quiz_id=q.id, student_id=uid, status="in_progress",
                                   started_at=datetime.now(UTC))
            db.session.add(attempt)
            db.session.flush()
            ans = Answer(attempt_id=attempt.id, question_id=question.id,
                          answer={"text": "bad"}, is_correct=None, awarded_mark=None)
            db.session.add(ans)
            db.session.commit()
            grade_essay(ans, 0)
            assert ans.awarded_mark == 0
            assert ans.is_correct is False

    def test_grade_essay_none_mark(self, app):
        from app.services.assessment import grade_essay
        from app.models.assessment import QuizAttempt, Quiz, Question, Answer
        with app.app_context():
            qid, cid, uid = self._make_quiz(app)
            q = db.session.get(Quiz, qid)
            question = Question(quiz_id=q.id, type="essay", prompt="Write", mark=20)
            db.session.add(question)
            db.session.flush()
            attempt = QuizAttempt(quiz_id=q.id, student_id=uid, status="in_progress",
                                   started_at=datetime.now(UTC))
            db.session.add(attempt)
            db.session.flush()
            ans = Answer(attempt_id=attempt.id, question_id=question.id,
                          answer=None, is_correct=None, awarded_mark=None)
            db.session.add(ans)
            db.session.commit()
            grade_essay(ans, None)
            assert ans.awarded_mark is None
            assert ans.is_correct is False


# ===========================================================================
# BILLING — discount apply edge cases
# ===========================================================================

class TestBillingDiscountEdges:
    """billing.py — discount apply/validate edge cases not in batch 1."""

    def test_apply_discount_exceeds_price(self, app):
        from app.services.billing import create_discount_code, apply_discount_code
        from app.models.billing import Subscription as SubModel
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            plan_id = make_subscription_plan(app, sid, cid, price=10)
            uid = _make_student(app)
            sub_id = make_subscription(app, uid, plan_id, cid)
            create_discount_code(sid, "BIGDISC", "Big", "fixed", 100)
            result, err = apply_discount_code(sub_id, "BIGDISC")
            # The discount gets capped at plan price in validate, then
            # new_price = 10 - 10 = 0, so it should succeed
            assert result is not None

    def test_validate_discount_percentage_exact(self, app):
        from app.services.billing import create_discount_code, validate_discount_code
        with app.app_context():
            sid = make_school(app)
            plan_id = make_subscription_plan(app, sid, price=50)
            create_discount_code(sid, "HALF", "Half", "percentage", 50)
            result, err = validate_discount_code("HALF", plan_id)
            assert result == Decimal("25.00")

    def test_validate_discount_fixed_exact(self, app):
        from app.services.billing import create_discount_code, validate_discount_code
        with app.app_context():
            sid = make_school(app)
            plan_id = make_subscription_plan(app, sid, price=100)
            create_discount_code(sid, "MINUS20", "20 off", "fixed", 20)
            result, err = validate_discount_code("MINUS20", plan_id)
            assert result == Decimal("20.00")

    def test_record_manual_payment_none_amount(self, app):
        from app.services.billing import record_manual_payment
        from app.models.billing import Subscription as SubModel
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            plan_id = make_subscription_plan(app, sid, cid, price=100)
            sub_id = make_subscription(app, uid, plan_id, cid)
            sub = db.session.get(SubModel, sub_id)
            result, err = record_manual_payment(sub, "REF", None)
            assert result is None


# ===========================================================================
# MESSAGES — inbox, sent, get_thread, mark_read edges
# ===========================================================================

class TestMessagesEdges:
    """messages.py — inbox, sent, get_thread, mark_read branches."""

    def test_inbox_returns_root_messages(self, app):
        from app.services.messages import send_message, inbox
        with app.app_context():
            uid = _make_student(app)
            rid = _make_student(app)
            msg, _ = send_message(uid, rid, "Root", "Body")
            # Send a reply
            send_message(uid, rid, "Reply", "Reply body", parent_message_id=msg.id)
            inbox_msgs = inbox(rid)
            # Should only show root (parent_message_id=None)
            assert len(inbox_msgs) == 1

    def test_sent_messages(self, app):
        from app.services.messages import send_message, sent
        with app.app_context():
            uid = _make_student(app)
            rid = _make_student(app)
            send_message(uid, rid, "Msg1", "Body1")
            send_message(uid, rid, "Msg2", "Body2")
            sent_msgs = sent(uid)
            assert len(sent_msgs) >= 2

    def test_sent_empty(self, app):
        from app.services.messages import sent
        with app.app_context():
            uid = _make_student(app)
            assert len(sent(uid)) == 0

    def test_get_thread(self, app):
        from app.services.messages import send_message, get_thread
        with app.app_context():
            uid = _make_student(app)
            rid = _make_student(app)
            msg, _ = send_message(uid, rid, "Thread", "Body")
            reply, _ = send_message(uid, rid, "Re: Thread", "Reply", parent_message_id=msg.id)
            thread = get_thread(msg.id)
            assert thread is not None
            assert thread.subject == "Thread"

    def test_get_thread_nonexistent(self, app):
        from app.services.messages import get_thread
        with app.app_context():
            assert get_thread(99999) is None

    def test_mark_read_already_read(self, app):
        from app.services.messages import send_message, mark_read, unread_count
        with app.app_context():
            uid = _make_student(app)
            rid = _make_student(app)
            msg, _ = send_message(uid, rid, "Sub", "Body")
            mark_read(msg.id, rid)
            # Mark again — should be a no-op (msg.is_read is True)
            mark_read(msg.id, rid)
            assert unread_count(rid) == 0

    def test_mark_read_nonexistent_msg(self, app):
        from app.services.messages import mark_read
        with app.app_context():
            # Should not crash
            mark_read(99999, 99999)

    def test_mark_read_already_read_no_op(self, app):
        """msg exists but is already read — mark_read should skip."""
        from app.services.messages import send_message, mark_read, unread_count
        with app.app_context():
            uid = _make_student(app)
            rid = _make_student(app)
            msg, _ = send_message(uid, rid, "Sub", "Body")
            mark_read(msg.id, rid)
            assert unread_count(rid) == 0
            # Second call: msg exists + correct recipient + already read → skip
            mark_read(msg.id, rid)
            assert unread_count(rid) == 0

    def test_inbox_sorted_by_read_status(self, app):
        from app.services.messages import send_message, inbox, mark_read
        with app.app_context():
            uid = _make_student(app)
            rid = _make_student(app)
            msg1, _ = send_message(uid, rid, "First", "Body1")
            msg2, _ = send_message(uid, rid, "Second", "Body2")
            mark_read(msg1.id, rid)
            inbox_msgs = inbox(rid)
            # Unread first
            assert inbox_msgs[0].id == msg2.id

    def test_thread_with_reply(self, app):
        from app.services.messages import send_message, get_thread
        with app.app_context():
            uid = _make_student(app)
            rid = _make_student(app)
            root, _ = send_message(uid, rid, "Root", "Body")
            reply, _ = send_message(rid, uid, "Re: Root", "Reply", parent_message_id=root.id)
            thread = get_thread(root.id)
            assert thread is not None


# ===========================================================================
# TUTORING — zoom error paths, generate_zoom_meeting
# ===========================================================================

class TestTutoringZoomErrorPaths:
    """tutoring.py — Zoom meeting error paths."""

    def test_generate_zoom_meeting_no_config(self, app):
        from app.services.tutoring import create_session as create_sess, generate_zoom_meeting
        with app.app_context():
            tutor = _make_teacher(app, make_school(app))
            student = _make_student(app)
            s_obj = create_sess(tutor, student, "Math", None)
            result, err = generate_zoom_meeting(s_obj.id, tutor)
            assert result is None
            assert err is not None

    def test_generate_zoom_meeting_session_not_found(self, app):
        from app.services.tutoring import generate_zoom_meeting
        with app.app_context():
            uid = _make_student(app)
            result, err = generate_zoom_meeting(99999, uid)
            assert result is None

    def test_generate_zoom_meeting_not_authorized(self, app):
        from app.services.tutoring import create_session as create_sess, generate_zoom_meeting
        with app.app_context():
            tutor = _make_teacher(app, make_school(app))
            student = _make_student(app)
            s_obj = create_sess(tutor, student, "Math", None)
            other = _make_student(app)
            result, err = generate_zoom_meeting(s_obj.id, other)
            assert result is None

    def test_generate_zoom_meeting_incomplete_config(self, app):
        """Missing ZOOM_ACCOUNT_ID."""
        import os
        from app.services.tutoring import create_session as create_sess, generate_zoom_meeting
        with app.app_context():
            tutor = _make_teacher(app, make_school(app))
            student = _make_student(app)
            s_obj = create_sess(tutor, student, "Math", None)
            with patch.dict(os.environ, {"ZOOM_ACCOUNT_ID": "", "ZOOM_CLIENT_ID": "x", "ZOOM_CLIENT_SECRET": "y"}, clear=False):
                result, err = generate_zoom_meeting(s_obj.id, tutor)
                assert result is None

    def test_generate_live_session_url_not_authorized(self, app):
        from app.services.tutoring import create_session as create_sess, generate_live_session_url
        with app.app_context():
            tutor = _make_teacher(app, make_school(app))
            student = _make_student(app)
            s_obj = create_sess(tutor, student, "Math", None)
            other = _make_student(app)
            result = generate_live_session_url(s_obj.id, other)
            assert result is None

    def test_generate_live_session_url_jitsi(self, app):
        from app.services.tutoring import create_session as create_sess, generate_live_session_url
        with app.app_context():
            tutor = _make_teacher(app, make_school(app))
            student = _make_student(app)
            s_obj = create_sess(tutor, student, "Math", None)
            url = generate_live_session_url(s_obj.id, tutor)
            assert url is not None
            assert "jitsi" in url.lower() or "meet" in url.lower()

    def test_generate_live_session_url_zoom_existing(self, app):
        from app.services.tutoring import create_session as create_sess, generate_live_session_url
        from app.models.tutoring import TutoringSession as TS
        with app.app_context():
            tutor = _make_teacher(app, make_school(app))
            student = _make_student(app)
            s_obj = create_sess(tutor, student, "Math", None)
            ts = db.session.get(TS, s_obj.id)
            ts.video_provider = "zoom"
            ts.zoom_join_url = "https://zoom.us/j/123"
            db.session.commit()
            url = generate_live_session_url(s_obj.id, tutor)
            assert url == "https://zoom.us/j/123"

    def test_update_session_live_status_no_online_link(self, app):
        from app.services.tutoring import create_session as create_sess, update_session_live_status
        from app.models.tutoring import TutoringSession as TS
        with app.app_context():
            tutor = _make_teacher(app, make_school(app))
            student = _make_student(app)
            s_obj = create_sess(tutor, student, "Math", None)
            ts = db.session.get(TS, s_obj.id)
            result = update_session_live_status(ts, live_status="completed", online_link=None, user_id=tutor)
            assert ts.status == "completed"

    def test_update_session_live_status_active_no_link(self, app):
        """When live_status='active' and no online_link, generates one."""
        from app.services.tutoring import create_session as create_sess, update_session_live_status
        from app.models.tutoring import TutoringSession as TS
        with app.app_context():
            tutor = _make_teacher(app, make_school(app))
            student = _make_student(app)
            s_obj = create_sess(tutor, student, "Math", None)
            ts = db.session.get(TS, s_obj.id)
            result = update_session_live_status(ts, live_status="active", online_link=None, user_id=tutor)
            # Should generate a Jitsi link
            assert ts.online_link is not None or result is not None


# ===========================================================================
# GRADE APPEALS — all branches
# ===========================================================================

class TestGradeAppealsBranches:
    """grade_appeals.py — submit, review, get branches."""

    def test_submit_appeal_empty_reason(self, app):
        from app.services.grade_appeals import submit_appeal
        with app.app_context():
            result = submit_appeal(99999, 1, "")
            assert result is None

    def test_review_appeal_invalid_status(self, app):
        from app.services.grade_appeals import review_appeal
        with app.app_context():
            result = review_appeal(99999, "invalid", "response", 1)
            assert result is None

    def test_review_appeal_not_found(self, app):
        from app.services.grade_appeals import review_appeal
        with app.app_context():
            reviewer = _make_teacher(app, make_school(app))
            result = review_appeal(99999, "approved", "ok", reviewer)
            assert result is None

    def test_review_appeal_approved_direct(self, app):
        """Test review_appeal with proper FK chain."""
        from app.services.grade_appeals import review_appeal
        from app.extensions import db
        from app.models.gradebook import Assignment, GradeAppeal, Submission
        sid = make_school(app)
        cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
        with app.app_context():
            uid = _make_student(app)
            assignment = Assignment(class_id=cid, title="HW1", max_mark=100)
            db.session.add(assignment)
            db.session.flush()
            sub = Submission(assignment_id=assignment.id, student_id=uid)
            db.session.add(sub)
            db.session.flush()
            ga = GradeAppeal(submission_id=sub.id, student_id=uid, reason="Wrong")
            db.session.add(ga)
            db.session.commit()
            reviewer = _make_teacher(app, sid)
            result = review_appeal(ga.id, "approved", "Fixed", reviewer)
            assert result.status == "approved"

    def test_review_appeal_rejected_direct(self, app):
        from app.services.grade_appeals import review_appeal
        from app.extensions import db
        from app.models.gradebook import Assignment, GradeAppeal, Submission
        sid = make_school(app)
        cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
        with app.app_context():
            uid = _make_student(app)
            a = Assignment(class_id=cid, title="HW1", max_mark=100)
            db.session.add(a)
            db.session.flush()
            sub = Submission(assignment_id=a.id, student_id=uid)
            db.session.add(sub)
            db.session.flush()
            ga = GradeAppeal(submission_id=sub.id, student_id=uid, reason="Wrong")
            db.session.add(ga)
            db.session.commit()
            reviewer = _make_teacher(app, sid)
            result = review_appeal(ga.id, "rejected", "Correct", reviewer)
            assert result.status == "rejected"

    def test_review_appeal_reviewing_direct(self, app):
        from app.services.grade_appeals import review_appeal
        from app.extensions import db
        from app.models.gradebook import Assignment, GradeAppeal, Submission
        sid = make_school(app)
        cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
        with app.app_context():
            uid = _make_student(app)
            a = Assignment(class_id=cid, title="HW1", max_mark=100)
            db.session.add(a)
            db.session.flush()
            sub = Submission(assignment_id=a.id, student_id=uid)
            db.session.add(sub)
            db.session.flush()
            ga = GradeAppeal(submission_id=sub.id, student_id=uid, reason="Wrong")
            db.session.add(ga)
            db.session.commit()
            reviewer = _make_teacher(app, sid)
            result = review_appeal(ga.id, "reviewing", None, reviewer)
            assert result.status == "reviewing"

    def test_get_student_appeals_direct(self, app):
        from app.services.grade_appeals import get_student_appeals
        from app.extensions import db
        from app.models.gradebook import Assignment, GradeAppeal, Submission
        sid = make_school(app)
        cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
        with app.app_context():
            uid = _make_student(app)
            a1 = Assignment(class_id=cid, title="HW1", max_mark=100)
            a2 = Assignment(class_id=cid, title="HW2", max_mark=100)
            db.session.add_all([a1, a2])
            db.session.flush()
            s1 = Submission(assignment_id=a1.id, student_id=uid)
            s2 = Submission(assignment_id=a2.id, student_id=uid)
            db.session.add_all([s1, s2])
            db.session.flush()
            ga1 = GradeAppeal(submission_id=s1.id, student_id=uid, reason="A1")
            ga2 = GradeAppeal(submission_id=s2.id, student_id=uid, reason="A2")
            db.session.add_all([ga1, ga2])
            db.session.commit()
            appeals = get_student_appeals(uid)
            assert len(appeals) >= 2

    def test_get_pending_appeals_direct(self, app):
        from app.services.grade_appeals import get_pending_appeals
        from app.extensions import db
        from app.models.gradebook import Assignment, GradeAppeal, Submission
        sid = make_school(app)
        cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
        with app.app_context():
            uid = _make_student(app)
            a = Assignment(class_id=cid, title="HW1", max_mark=100)
            db.session.add(a)
            db.session.flush()
            sub = Submission(assignment_id=a.id, student_id=uid)
            db.session.add(sub)
            db.session.flush()
            ga = GradeAppeal(submission_id=sub.id, student_id=uid, reason="Pending")
            db.session.add(ga)
            db.session.commit()
            pending = get_pending_appeals()
            assert len(pending) >= 1


# ===========================================================================
# PROGRESS — class_progress_overview with students having progress
# ===========================================================================

class TestProgressEdgeCases:
    """progress.py — class_progress_overview with populated data."""

    def test_class_progress_overview_with_data(self, app):
        from app.services.progress import class_progress_overview, record_lesson_view
        from app.extensions import db
        from app.models.progress import StudentProgress
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            cid = make_class(app, sid, gid, sub_id)
            lid1 = make_lesson(app, cid)
            lid2 = make_lesson(app, cid)
            uid = _make_student(app)
            make_class_member(app, cid, uid)
            record_lesson_view(uid, lid1, cid)
            record_lesson_view(uid, lid2, cid)
            result = class_progress_overview(cid)
            assert len(result) >= 1

    def test_student_class_progress(self, app):
        from app.services.progress import student_class_progress, record_lesson_view
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            lid = make_lesson(app, cid)
            uid = _make_student(app)
            record_lesson_view(uid, lid, cid)
            result = student_class_progress(uid, cid)
            assert len(result) >= 1

    def test_student_class_progress_empty(self, app):
        from app.services.progress import student_class_progress
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            result = student_class_progress(uid, cid)
            assert len(result) == 0


# ===========================================================================
# FINANCE — accounts_receivable with data
# ===========================================================================

class TestFinanceEdges:
    """finance.py — accounts_receivable with populated data."""

    def test_accounts_receivable_with_data(self, app):
        from app.services.finance import accounts_receivable
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            plan_id = make_subscription_plan(app, sid, cid, price=100)
            sub_id = make_subscription(app, uid, plan_id, cid, status="active")
            make_payment(app, sub_id, amount=30, status="approved")
            result = accounts_receivable(sid)
            assert len(result) >= 1
            assert result[0]["balance"] == 70.0

    def test_accounts_receivable_fully_paid(self, app):
        from app.services.finance import accounts_receivable
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            plan_id = make_subscription_plan(app, sid, cid, price=100)
            sub_id = make_subscription(app, uid, plan_id, cid, status="active")
            make_payment(app, sub_id, amount=100, status="approved")
            result = accounts_receivable(sid)
            # Fully paid — balance = 0, not included
            assert len(result) == 0

    def test_school_revenue_with_pending(self, app):
        from app.services.finance import school_revenue_summary
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            plan_id = make_subscription_plan(app, sid, cid, price=100)
            sub_id = make_subscription(app, uid, plan_id, cid, status="active")
            make_payment(app, sub_id, amount=50, status="approved")
            make_payment(app, sub_id, amount=25, status="pending")
            result = school_revenue_summary(sid)
            assert float(result["total_revenue"]) == 50
            assert float(result["pending_amount"]) == 25


# Need db and User for some tests
from app.extensions import db
from app.models.user import User
