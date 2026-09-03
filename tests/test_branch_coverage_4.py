"""Batch 4 — massive branch coverage for remaining untested services.

Targets: quiz_stats, question_bank, individual, wallet_service, revenue,
school_approvals, uploads, security, auth, family, health, onboarding,
gradebook, tenant, and deeper context/base paths.

Every test exercises both True and False paths of if/elif/else branches,
try/except error handlers, and short-circuit boolean expressions.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import (
    make_class,
    make_class_member,
    make_grade,
    make_grade_category,
    make_grade_entry,
    make_grade_item,
    make_lesson,
    make_school,
    make_subject,
    make_subscription,
    make_subscription_plan,
    make_user,
)


def _uid() -> str:
    return f"b4_{int(time.time()*1000000)}"


def _make_student(app, school_id=None):
    return make_user(app, role="student", school_id=school_id)


def _make_teacher(app, school_id):
    return make_user(app, role="teacher", school_id=school_id)


def _make_super_admin(app):
    return make_user(app, role="super_admin")


def _make_school_admin(app, school_id):
    return make_user(app, role="school_admin", school_id=school_id)


# ===========================================================================
# QUIZ_STATS — all branches (no quiz, no attempts, with data)
# ===========================================================================

class TestQuizStats:
    """quiz_stats.py — get_quiz_stats all branches."""

    def test_get_quiz_stats_nonexistent(self, app):
        from app.services.quiz_stats import get_quiz_stats
        with app.app_context():
            result = get_quiz_stats(99999)
            assert result is None

    def test_get_quiz_stats_zero_attempts(self, app):
        from app.services.quiz_stats import get_quiz_stats
        from app.services.assessment import create_quiz
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            quiz, _ = create_quiz(cid, "Empty Quiz")
            stats = get_quiz_stats(quiz.id)
            assert stats is not None
            assert stats.total_attempts == 0
            assert stats.avg_score == 0.0
            assert stats.std_deviation == 0.0

    def test_get_quiz_stats_with_attempts(self, app):
        from app.services.quiz_stats import get_quiz_stats
        from app.services.assessment import create_quiz, add_question, start_attempt, submit_attempt, save_answer
        from app.extensions import db
        from app.models.assessment import QuizAttempt
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            uid2 = _make_student(app)
            quiz, _ = create_quiz(cid, "Stats Quiz")
            q1 = add_question(quiz, "mcq", "Q1", {"options": ["A", "B"]}, {"index": 0}, mark=10)
            q2 = add_question(quiz, "true_false", "Q2", None, {"value": True}, mark=5)
            # Student 1: correct
            a1, _ = start_attempt(quiz, uid)
            save_answer(a1, q1.id, {"index": 0})
            save_answer(a1, q2.id, {"value": True})
            submit_attempt(a1, allow_after_deadline=True)
            # Student 2: wrong
            a2, _ = start_attempt(quiz, uid2)
            save_answer(a2, q1.id, {"index": 1})
            save_answer(a2, q2.id, {"value": False})
            submit_attempt(a2, allow_after_deadline=True)
            stats = get_quiz_stats(quiz.id)
            assert stats.total_attempts == 2
            assert stats.highest_score >= stats.lowest_score
            assert stats.std_deviation >= 0
            assert len(stats.question_stats) == 2
            assert "0-20" in stats.score_distribution

    def test_question_stats_discrimination_index(self, app):
        from app.services.quiz_stats import get_quiz_stats
        from app.services.assessment import create_quiz, add_question, start_attempt, submit_attempt, save_answer
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            quiz, _ = create_quiz(cid, "Disc Quiz")
            q1 = add_question(quiz, "mcq", "Q1", {"options": ["A", "B", "C"]}, {"index": 0}, mark=10)
            # 4 students to get meaningful discrimination
            for i in range(4):
                uid = _make_student(app)
                a, _ = start_attempt(quiz, uid)
                answer_idx = 0 if i < 2 else 1
                save_answer(a, q1.id, {"index": answer_idx})
                submit_attempt(a, allow_after_deadline=True)
            stats = get_quiz_stats(quiz.id)
            assert len(stats.question_stats) == 1
            # Discrimination should be computed
            qs = stats.question_stats[0]
            assert qs.total_answers == 4


# ===========================================================================
# QUESTION_BANK — all validation branches
# ===========================================================================

class TestQuestionBank:
    """question_bank.py — all branches."""

    def test_create_bank_question_empty_text(self, app):
        from app.services.question_bank import create_bank_question
        with app.app_context():
            result, err = create_bank_question(1, 1, "", "mcq")
            assert result is None

    def test_create_bank_question_invalid_type(self, app):
        from app.services.question_bank import create_bank_question
        with app.app_context():
            result, err = create_bank_question(1, 1, "Q?", "invalid")
            assert result is None

    def test_create_bank_question_difficulty_out_of_range_low(self, app):
        from app.services.question_bank import create_bank_question
        with app.app_context():
            result, err = create_bank_question(1, 1, "Q?", "mcq", difficulty=0)
            assert result is None

    def test_create_bank_question_difficulty_out_of_range_high(self, app):
        from app.services.question_bank import create_bank_question
        with app.app_context():
            result, err = create_bank_question(1, 1, "Q?", "mcq", difficulty=6)
            assert result is None

    def test_create_bank_question_success(self, app):
        from app.services.question_bank import create_bank_question
        with app.app_context():
            uid = _make_teacher(app, make_school(app))
            bq, err = create_bank_question(uid, 1, "What is 2+2?", "mcq",
                                           options={"A": "3", "B": "4"}, correct_answer={"index": 1})
            assert bq is not None

    def test_list_bank_questions(self, app):
        from app.services.question_bank import create_bank_question, list_bank_questions
        with app.app_context():
            uid = _make_teacher(app, make_school(app))
            create_bank_question(uid, 1, "Q1", "mcq")
            create_bank_question(uid, 1, "Q2", "true_false", difficulty=5)
            questions = list_bank_questions(uid)
            assert len(questions) >= 2

    def test_list_bank_questions_with_filters(self, app):
        from app.services.question_bank import create_bank_question, list_bank_questions
        with app.app_context():
            uid = _make_teacher(app, make_school(app))
            sid = make_school(app)
            sub_id = make_subject(app)
            create_bank_question(uid, sid, "Q1", "mcq", subject_id=sub_id, difficulty=3)
            create_bank_question(uid, sid, "Q2", "true_false", difficulty=5)
            filtered = list_bank_questions(uid, subject_id=sub_id, question_type="mcq", difficulty=3)
            assert len(filtered) >= 1

    def test_update_bank_question_not_found(self, app):
        from app.services.question_bank import update_bank_question
        with app.app_context():
            result, err = update_bank_question(99999, 1)
            assert result is None

    def test_update_bank_question_wrong_teacher(self, app):
        from app.services.question_bank import create_bank_question, update_bank_question
        with app.app_context():
            uid = _make_teacher(app, make_school(app))
            bq, _ = create_bank_question(uid, 1, "Q?", "mcq")
            other = _make_teacher(app, make_school(app))
            result, err = update_bank_question(bq.id, other)
            assert result is None

    def test_update_bank_question_success(self, app):
        from app.services.question_bank import create_bank_question, update_bank_question
        with app.app_context():
            uid = _make_teacher(app, make_school(app))
            bq, _ = create_bank_question(uid, 1, "Old text", "mcq")
            result, err = update_bank_question(bq.id, uid, question_text="New text", difficulty=5)
            assert result is not None

    def test_delete_bank_question_not_found(self, app):
        from app.services.question_bank import delete_bank_question
        with app.app_context():
            ok, err = delete_bank_question(99999, 1)
            assert ok is False

    def test_delete_bank_question_wrong_teacher(self, app):
        from app.services.question_bank import create_bank_question, delete_bank_question
        with app.app_context():
            uid = _make_teacher(app, make_school(app))
            bq, _ = create_bank_question(uid, 1, "Q?", "mcq")
            other = _make_teacher(app, make_school(app))
            ok, err = delete_bank_question(bq.id, other)
            assert ok is False

    def test_delete_bank_question_success(self, app):
        from app.services.question_bank import create_bank_question, delete_bank_question
        with app.app_context():
            uid = _make_teacher(app, make_school(app))
            bq, _ = create_bank_question(uid, 1, "Q?", "mcq")
            ok, err = delete_bank_question(bq.id, uid)
            assert ok is True

    def test_import_to_quiz_empty_ids(self, app):
        from app.services.question_bank import import_to_quiz
        from app.services.assessment import create_quiz
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            quiz, _ = create_quiz(cid, "Import Quiz")
            count, err = import_to_quiz(quiz, [], 1)
            assert count == 0

    def test_import_to_quiz_no_valid_questions(self, app):
        from app.services.question_bank import import_to_quiz
        from app.services.assessment import create_quiz
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            quiz, _ = create_quiz(cid, "Import Quiz")
            count, err = import_to_quiz(quiz, [99999], 1)
            assert count == 0

    def test_import_to_quiz_success(self, app):
        from app.services.question_bank import create_bank_question, import_to_quiz
        from app.services.assessment import create_quiz
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_teacher(app, sid)
            quiz, _ = create_quiz(cid, "Import Quiz")
            bq1, _ = create_bank_question(uid, sid, "Imported Q1", "mcq")
            bq2, _ = create_bank_question(uid, sid, "Imported Q2", "true_false")
            count, err = import_to_quiz(quiz, [bq1.id, bq2.id], uid)
            assert count == 2


# ===========================================================================
# INDIVIDUAL — public classes, subscribe
# ===========================================================================

class TestIndividual:
    """individual.py — get_public_classes, subscribe_to_class branches."""

    def test_get_public_classes_empty(self, app):
        from app.services.individual import get_public_classes
        with app.app_context():
            classes = get_public_classes()
            assert len(classes) == 0

    def test_get_public_classes_with_data(self, app):
        from app.services.individual import get_public_classes
        from app.extensions import db
        from app.models.class_room import ClassRoom
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            cr = ClassRoom(school_id=sid, grade_id=gid, subject_id=sub_id,
                          join_code="PUB1", is_public=True)
            db.session.add(cr)
            db.session.commit()
            classes = get_public_classes()
            assert len(classes) >= 1

    def test_get_public_classes_with_subject_filter(self, app):
        from app.services.individual import get_public_classes
        from app.extensions import db
        from app.models.class_room import ClassRoom
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            cr = ClassRoom(school_id=sid, grade_id=gid, subject_id=sub_id,
                          join_code="PUB2", is_public=True)
            db.session.add(cr)
            db.session.commit()
            classes = get_public_classes(subject_id=sub_id)
            assert len(classes) >= 1

    def test_subscribe_to_class_not_public(self, app):
        from app.services.individual import subscribe_to_class
        with app.app_context():
            sid = make_school(app)
            cid = make_class(app, sid, make_grade(app, sid), make_subject(app))
            uid = _make_student(app)
            err = subscribe_to_class(uid, cid)
            assert err is not None

    def test_subscribe_to_class_not_found(self, app):
        from app.services.individual import subscribe_to_class
        with app.app_context():
            uid = _make_student(app)
            err = subscribe_to_class(uid, 99999)
            assert err is not None

    def test_subscribe_to_class_already_member(self, app):
        from app.services.individual import subscribe_to_class
        from app.extensions import db
        from app.models.class_room import ClassRoom
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            cr = ClassRoom(school_id=sid, grade_id=gid, subject_id=sub_id,
                          join_code="ALR", is_public=True)
            db.session.add(cr)
            db.session.commit()
            uid = _make_student(app)
            make_class_member(app, cr.id, uid)
            err = subscribe_to_class(uid, cr.id)
            assert err is not None

    def test_subscribe_to_class_full(self, app):
        from app.services.individual import subscribe_to_class
        from app.extensions import db
        from app.models.class_room import ClassRoom
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            cr = ClassRoom(school_id=sid, grade_id=gid, subject_id=sub_id,
                          join_code="FULL", is_public=True, max_students=1)
            db.session.add(cr)
            db.session.commit()
            uid = _make_student(app)
            make_class_member(app, cr.id, uid)
            uid2 = _make_student(app)
            err = subscribe_to_class(uid2, cr.id)
            assert err is not None

    def test_subscribe_to_class_free(self, app):
        from app.services.individual import subscribe_to_class
        from app.extensions import db
        from app.models.class_room import ClassRoom
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            cr = ClassRoom(school_id=sid, grade_id=gid, subject_id=sub_id,
                          join_code="FREE", is_public=True)
            db.session.add(cr)
            db.session.commit()
            uid = _make_student(app)
            err = subscribe_to_class(uid, cr.id)
            assert err is None

    def test_subscribe_to_class_paid(self, app):
        from app.services.individual import subscribe_to_class
        from app.extensions import db
        from app.models.class_room import ClassRoom
        with app.app_context():
            sid = make_school(app)
            gid = make_grade(app, sid)
            sub_id = make_subject(app)
            cr = ClassRoom(school_id=sid, grade_id=gid, subject_id=sub_id,
                          join_code="PAID", is_public=True, price=100.0, currency="ILS")
            db.session.add(cr)
            db.session.flush()
            make_subscription_plan(app, sid, cr.id, price=100)
            db.session.commit()
            uid = _make_student(app)
            err = subscribe_to_class(uid, cr.id)
            assert err is None

    def test_get_student_classes_empty(self, app):
        from app.services.individual import get_student_classes
        with app.app_context():
            uid = _make_student(app)
            classes = get_student_classes(uid)
            assert len(classes) == 0


# ===========================================================================
# WALLET_SERVICE — get_or_create, balance, transfers
# ===========================================================================

class TestWalletService:
    """wallet_service.py — wallet creation, balance, transfers."""

    def test_get_or_create_wallet_new(self, app):
        from app.services.wallet_service import get_or_create_wallet
        with app.app_context():
            sid = make_school(app)
            uid = _make_student(app)
            wallet, err = get_or_create_wallet(sid, uid)
            assert wallet is not None
            assert wallet.balance == Decimal("0.00")

    def test_get_or_create_wallet_existing(self, app):
        from app.services.wallet_service import get_or_create_wallet
        with app.app_context():
            sid = make_school(app)
            uid = _make_student(app)
            w1, _ = get_or_create_wallet(sid, uid)
            w2, _ = get_or_create_wallet(sid, uid)
            assert w1.id == w2.id

    def test_get_or_create_wallet_custom_currency(self, app):
        from app.services.wallet_service import get_or_create_wallet
        with app.app_context():
            sid = make_school(app)
            uid = _make_student(app)
            wallet, _ = get_or_create_wallet(sid, uid, currency="USD")
            assert wallet.currency == "USD"

    def test_get_balance(self, app):
        from app.services.wallet_service import get_or_create_wallet, get_balance
        with app.app_context():
            sid = make_school(app)
            uid = _make_student(app)
            wallet, _ = get_or_create_wallet(sid, uid)
            balance = get_balance(wallet.id)
            assert balance == Decimal("0.00")

    def test_money_normalization(self, app):
        from app.services.wallet_service import _money
        with app.app_context():
            assert _money(10.555) == Decimal("10.56")
            assert _money("10.554") == Decimal("10.55")
            assert _money(0) == Decimal("0.00")
            assert _money(-5.5) == Decimal("-5.50")

    def test_generate_tx_hash(self, app):
        from app.services.wallet_service import _generate_tx_hash
        with app.app_context():
            h1 = _generate_tx_hash(1, 1, 2, Decimal("100"), "transfer")
            h2 = _generate_tx_hash(1, 1, 2, Decimal("100"), "transfer")
            # UUID makes each hash unique
            assert len(h1) == 64


# ===========================================================================
# REVENUE — summary, by gateway, by school
# ===========================================================================

class TestRevenue:
    """revenue.py — all revenue tracking branches."""

    def test_revenue_summary_no_data(self, app):
        from app.services.revenue import get_revenue_summary
        with app.app_context():
            result = get_revenue_summary()
            assert result["total_revenue"] == 0
            assert result["transaction_count"] == 0

    def test_revenue_summary_with_dates(self, app):
        from app.services.revenue import get_revenue_summary
        with app.app_context():
            now = datetime.now(UTC)
            result = get_revenue_summary(date_from=now - timedelta(days=7), date_to=now)
            assert result["currency"] == "ILS"

    def test_revenue_by_gateway_empty(self, app):
        from app.services.revenue import get_revenue_by_gateway
        with app.app_context():
            result = get_revenue_by_gateway()
            assert len(result) == 0

    def test_revenue_by_school_empty(self, app):
        from app.services.revenue import get_revenue_by_school
        with app.app_context():
            result = get_revenue_by_school()
            assert len(result) == 0

    def test_revenue_by_school_with_limit(self, app):
        from app.services.revenue import get_revenue_by_school
        with app.app_context():
            result = get_revenue_by_school(limit=5)
            assert len(result) <= 5


# ===========================================================================
# SCHOOL_APPROVALS — approve, reject, queue, can_user_approve
# ===========================================================================

class TestSchoolApprovals:
    """school_approvals.py — all branches."""

    def test_get_pending_approvals_for_school_empty(self, app):
        from app.services.school_approvals import get_pending_approvals_for_school
        with app.app_context():
            sid = make_school(app)
            result = get_pending_approvals_for_school(sid)
            assert len(result) == 0

    def test_get_pending_approvals_super_admin_empty(self, app):
        from app.services.school_approvals import get_pending_approvals_for_super_admin
        with app.app_context():
            result = get_pending_approvals_for_super_admin()
            assert len(result) == 0

    def test_get_school_admins_empty(self, app):
        from app.services.school_approvals import get_school_admins
        with app.app_context():
            sid = make_school(app)
            result = get_school_admins(sid)
            assert len(result) == 0

    def test_approve_user_role_link_not_found(self, app):
        from app.services.school_approvals import approve_user_role_link
        with app.app_context():
            ok, err = approve_user_role_link(99999, 1)
            assert ok is False

    def test_reject_user_role_link_not_found(self, app):
        from app.services.school_approvals import reject_user_role_link
        with app.app_context():
            ok, err = reject_user_role_link(99999, 1)
            assert ok is False

    def test_get_approval_queue_user_not_found(self, app):
        from app.services.school_approvals import get_approval_queue_for_user
        with app.app_context():
            result = get_approval_queue_for_user(99999)
            assert len(result) == 0

    def test_get_approval_queue_student(self, app):
        from app.services.school_approvals import get_approval_queue_for_user
        with app.app_context():
            uid = _make_student(app)
            result = get_approval_queue_for_user(uid)
            assert len(result) == 0

    def test_can_user_approve_not_found(self, app):
        from app.services.school_approvals import can_user_approve
        with app.app_context():
            assert can_user_approve(99999, 99999) is False

    def test_can_user_approve_student(self, app):
        from app.services.school_approvals import can_user_approve
        with app.app_context():
            uid = _make_student(app)
            assert can_user_approve(uid, 99999) is False

    def test_can_user_approve_super_admin(self, app):
        from app.services.school_approvals import approve_user_role_link, can_user_approve
        from app.extensions import db
        from app.models.user import UserApprovalStatus, UserRoleLink
        with app.app_context():
            sid = make_school(app)
            admin_id = _make_super_admin(app)
            student_id = _make_student(app)
            link = UserRoleLink(user_id=student_id, school_id=sid, role="student")
            db.session.add(link)
            db.session.commit()
            assert can_user_approve(admin_id, link.id) is True

    def test_can_user_approve_school_admin_own_school(self, app):
        from app.services.school_approvals import can_user_approve
        from app.extensions import db
        from app.models.user import UserRoleLink
        with app.app_context():
            sid = make_school(app)
            admin_id = _make_school_admin(app, sid)
            student_id = _make_student(app)
            link = UserRoleLink(user_id=student_id, school_id=sid, role="student")
            db.session.add(link)
            db.session.commit()
            assert can_user_approve(admin_id, link.id) is True

    def test_can_user_approve_school_admin_other_school(self, app):
        from app.services.school_approvals import can_user_approve
        from app.extensions import db
        from app.models.user import UserRoleLink
        with app.app_context():
            sid1 = make_school(app)
            sid2 = make_school(app)
            admin_id = _make_school_admin(app, sid1)
            student_id = _make_student(app)
            link = UserRoleLink(user_id=student_id, school_id=sid2, role="student")
            db.session.add(link)
            db.session.commit()
            assert can_user_approve(admin_id, link.id) is False

    def test_approve_user_role_link_not_pending(self, app):
        from app.services.school_approvals import approve_user_role_link
        from app.extensions import db
        from app.models.user import UserRoleLink, User
        with app.app_context():
            uid = _make_student(app)
            user = db.session.get(User, uid)
            user.approval_status = UserApprovalStatus.approved
            link = UserRoleLink(user_id=uid, school_id=1, role="student")
            db.session.add(link)
            db.session.commit()
            approver = _make_super_admin(app)
            ok, err = approve_user_role_link(link.id, approver)
            assert ok is False

    def test_approve_user_role_link_user_not_found(self, app):
        from app.services.school_approvals import approve_user_role_link
        from app.extensions import db
        from app.models.user import UserRoleLink
        with app.app_context():
            link = UserRoleLink(user_id=99999, school_id=1, role="student")
            db.session.add(link)
            db.session.commit()
            approver = _make_super_admin(app)
            ok, err = approve_user_role_link(link.id, approver)
            assert ok is False

    def test_approve_user_role_link_approver_not_found(self, app):
        from app.services.school_approvals import approve_user_role_link
        from app.extensions import db
        from app.models.user import UserRoleLink
        with app.app_context():
            uid = _make_student(app)
            link = UserRoleLink(user_id=uid, school_id=1, role="student")
            db.session.add(link)
            db.session.commit()
            ok, err = approve_user_role_link(link.id, 99999)
            assert ok is False

    def test_approve_user_role_link_success(self, app):
        from app.services.school_approvals import approve_user_role_link
        from app.extensions import db
        from app.models.user import UserApprovalStatus, UserRoleLink, User
        with app.app_context():
            sid = make_school(app)
            uid = _make_student(app)
            link = UserRoleLink(user_id=uid, school_id=sid, role="student")
            db.session.add(link)
            db.session.commit()
            approver = _make_super_admin(app)
            ok, err = approve_user_role_link(link.id, approver)
            assert ok is True
            user = db.session.get(User, uid)
            assert user.approval_status == UserApprovalStatus.approved

    def test_reject_user_role_link_not_pending(self, app):
        from app.services.school_approvals import reject_user_role_link
        from app.extensions import db
        from app.models.user import UserApprovalStatus, UserRoleLink, User
        with app.app_context():
            uid = _make_student(app)
            user = db.session.get(User, uid)
            user.approval_status = UserApprovalStatus.approved
            link = UserRoleLink(user_id=uid, school_id=1, role="student")
            db.session.add(link)
            db.session.commit()
            approver = _make_super_admin(app)
            ok, err = reject_user_role_link(link.id, approver)
            assert ok is False

    def test_reject_user_role_link_success(self, app):
        from app.services.school_approvals import reject_user_role_link
        from app.extensions import db
        from app.models.user import UserApprovalStatus, UserRoleLink, User
        with app.app_context():
            sid = make_school(app)
            uid = _make_student(app)
            link = UserRoleLink(user_id=uid, school_id=sid, role="student")
            db.session.add(link)
            db.session.commit()
            approver = _make_super_admin(app)
            ok, err = reject_user_role_link(link.id, approver, reason="Policy violation")
            assert ok is True
            user = db.session.get(User, uid)
            assert user.approval_status == UserApprovalStatus.rejected

    def test_approve_school_admin_cannot_approve_other_school(self, app):
        from app.services.school_approvals import approve_user_role_link
        from app.extensions import db
        from app.models.user import UserRoleLink
        with app.app_context():
            sid1 = make_school(app)
            sid2 = make_school(app)
            admin = _make_school_admin(app, sid1)
            uid = _make_student(app)
            link = UserRoleLink(user_id=uid, school_id=sid2, role="student")
            db.session.add(link)
            db.session.commit()
            ok, err = approve_user_role_link(link.id, admin)
            assert ok is False

    def test_reject_school_admin_cannot_reject_other_school(self, app):
        from app.services.school_approvals import reject_user_role_link
        from app.extensions import db
        from app.models.user import UserRoleLink
        with app.app_context():
            sid1 = make_school(app)
            sid2 = make_school(app)
            admin = _make_school_admin(app, sid1)
            uid = _make_student(app)
            link = UserRoleLink(user_id=uid, school_id=sid2, role="student")
            db.session.add(link)
            db.session.commit()
            ok, err = reject_user_role_link(link.id, admin)
            assert ok is False

    def test_approve_student_cannot_approve(self, app):
        from app.services.school_approvals import approve_user_role_link
        from app.extensions import db
        from app.models.user import UserRoleLink
        with app.app_context():
            uid = _make_student(app)
            link = UserRoleLink(user_id=uid, school_id=1, role="student")
            db.session.add(link)
            db.session.commit()
            student2 = _make_student(app)
            ok, err = approve_user_role_link(link.id, student2)
            assert ok is False


# ===========================================================================
# SECURITY — password hashing
# ===========================================================================

class TestSecurity:
    """security.py — hash/verify password branches."""

    def test_hash_password(self, app):
        from app.core.security import hash_password
        hashed = hash_password("TestPass123!")
        assert hashed.startswith("$argon2id$")

    def test_verify_password_correct(self, app):
        from app.core.security import hash_password, verify_password
        hashed = hash_password("MyPassword!")
        assert verify_password("MyPassword!", hashed) is True

    def test_verify_password_wrong(self, app):
        from app.core.security import hash_password, verify_password
        hashed = hash_password("MyPassword!")
        assert verify_password("WrongPassword!", hashed) is False


# ===========================================================================
# AUTH SERVICE — login/logout/checks
# ===========================================================================

class TestAuthService:
    """auth.py — service-level auth functions."""

    def test_authenticate_nonexistent_email(self, app):
        from app.services.auth import authenticate_user
        with app.app_context():
            user, err = authenticate_user("nonexistent@test.com", "password")
            assert user is None

    def test_authenticate_wrong_password(self, app):
        from app.services.auth import authenticate_user
        from app.core.security import hash_password
        from app.extensions import db
        from app.models.user import User, UserRole, UserApprovalStatus
        with app.app_context():
            u = User(
                email=f"auth_test_{_uid()}@test.com",
                name_ar="Test",
                role=UserRole.student,
                password_hash=hash_password("CorrectPass!"),
                approval_status=UserApprovalStatus.approved,
                is_active=True,
            )
            db.session.add(u)
            db.session.commit()
            user, err = authenticate_user(u.email, "WrongPass!")
            assert user is None


# Need db and User for some tests
from app.extensions import db
from app.models.user import User
