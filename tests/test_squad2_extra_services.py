"""SQUAD 2 EXTRA: Tests for family, health, onboarding, school_approvals, grade_appeals, rubric."""

import pytest
from datetime import UTC, datetime, timedelta
from app.extensions import db
from app.models.user import User, UserRole, UserApprovalStatus, UserRoleLink
from app.models.family import FamilyLink, FamilyLinkCode
from app.models.gradebook import GradeAppeal, Submission, Assignment, RubricTemplate, RubricCriterion, RubricGrade
from app.models.system import HealthCheck, OnboardingProgress
from app.services.family import (
    generate_link_code, link_parent, list_children, remove_link,
    is_parent_of, get_parent,
)
from app.services.health import (
    check_database, check_disk, record_health, get_system_status,
)
from app.services.onboarding import (
    get_wizard_steps, get_onboarding, start_onboarding, complete_step, get_onboarding_status,
)
from app.services.school_approvals import (
    get_pending_approvals_for_school, get_school_admins,
    approve_user_role_link, reject_user_role_link, can_user_approve,
)
from app.services.grade_appeals import (
    submit_appeal, review_appeal, get_student_appeals, get_pending_appeals,
)
from app.services.rubric import (
    create_rubric_template, get_rubric_template, list_rubric_templates,
    grade_with_rubric, get_rubric_grades, rubric_total_score,
)
from tests.conftest import make_school, make_user


# ── Family ──
class TestFamilyServices:
    def test_generate_link_code(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "student", school_id=sid)
            code, err = generate_link_code(uid)
            assert err is None
            assert len(code) == 8

    def test_generate_code_non_student(self, app):
        with app.app_context():
            sid = make_school(app)
            uid = make_user(app, "teacher", school_id=sid)
            code, err = generate_link_code(uid)
            assert code is None
            assert err is not None

    def test_link_parent_success(self, app):
        with app.app_context():
            sid = make_school(app)
            student_uid = make_user(app, "student", school_id=sid)
            parent_uid = make_user(app, "parent", school_id=sid)
            code, _ = generate_link_code(student_uid)
            link, err = link_parent(parent_uid, code)
            assert err is None
            assert link is not None

    def test_link_parent_empty_code(self, app):
        with app.app_context():
            sid = make_school(app)
            parent_uid = make_user(app, "parent", school_id=sid)
            link, err = link_parent(parent_uid, "")
            assert link is None

    def test_link_parent_invalid_code(self, app):
        with app.app_context():
            sid = make_school(app)
            parent_uid = make_user(app, "parent", school_id=sid)
            link, err = link_parent(parent_uid, "INVALIDCODE")
            assert link is None

    def test_link_parent_not_parent_role(self, app):
        with app.app_context():
            sid = make_school(app)
            student_uid = make_user(app, "student", school_id=sid)
            teacher_uid = make_user(app, "teacher", school_id=sid)
            code, _ = generate_link_code(student_uid)
            link, err = link_parent(teacher_uid, code)
            assert link is None

    def test_list_children(self, app):
        with app.app_context():
            sid = make_school(app)
            student_uid = make_user(app, "student", school_id=sid)
            parent_uid = make_user(app, "parent", school_id=sid)
            code, _ = generate_link_code(student_uid)
            link_parent(parent_uid, code)
            children = list_children(parent_uid)
            assert len(children) == 1

    def test_remove_link(self, app):
        with app.app_context():
            sid = make_school(app)
            student_uid = make_user(app, "student", school_id=sid)
            parent_uid = make_user(app, "parent", school_id=sid)
            code, _ = generate_link_code(student_uid)
            link, _ = link_parent(parent_uid, code)
            ok, err = remove_link(link.id, parent_uid)
            assert ok is True

    def test_is_parent_of(self, app):
        with app.app_context():
            sid = make_school(app)
            student_uid = make_user(app, "student", school_id=sid)
            parent_uid = make_user(app, "parent", school_id=sid)
            code, _ = generate_link_code(student_uid)
            link_parent(parent_uid, code)
            assert is_parent_of(parent_uid, student_uid) is True
            assert is_parent_of(parent_uid, student_uid + 999) is False

    def test_get_parent(self, app):
        with app.app_context():
            sid = make_school(app)
            student_uid = make_user(app, "student", school_id=sid)
            parent_uid = make_user(app, "parent", school_id=sid)
            code, _ = generate_link_code(student_uid)
            link_parent(parent_uid, code)
            parent = get_parent(student_uid)
            assert parent is not None
            assert parent.id == parent_uid


# ── Health ──
class TestHealthServices:
    def test_check_database(self, app):
        with app.app_context():
            result = check_database()
            assert result["status"] == "healthy"
            assert result["latency_ms"] >= 0

    def test_check_disk(self, app):
        with app.app_context():
            result = check_disk()
            assert result["status"] in ("healthy", "degraded", "down")

    def test_record_health(self, app):
        with app.app_context():
            hc = record_health({"component": "test", "status": "healthy", "latency_ms": 5, "message": None})
            assert hc.id is not None

    def test_get_system_status(self, app):
        with app.app_context():
            status = get_system_status()
            assert "overall" in status
            assert "components" in status

    def test_get_system_status_empty(self, app):
        with app.app_context():
            status = get_system_status()
            assert status["overall"] in ("unknown", "healthy", "down", "degraded")


# ── Onboarding ──
class TestOnboardingServices:
    def test_wizard_steps(self, app):
        with app.app_context():
            steps = get_wizard_steps()
            assert len(steps) == 5

    def test_start_onboarding(self, app):
        with app.app_context():
            sid = make_school(app)
            p = start_onboarding(sid)
            assert p.current_step == 1
            assert p.total_steps == 5

    def test_start_idempotent(self, app):
        with app.app_context():
            sid = make_school(app)
            p1 = start_onboarding(sid)
            p2 = start_onboarding(sid)
            assert p1.id == p2.id

    def test_complete_steps(self, app):
        with app.app_context():
            sid = make_school(app)
            start_onboarding(sid)
            for step in range(1, 6):
                p = complete_step(sid, step)
            assert p.is_complete is True
            assert p.completed_at is not None

    def test_complete_invalid_step(self, app):
        with app.app_context():
            sid = make_school(app)
            start_onboarding(sid)
            p = complete_step(sid, 0)
            assert p is None
            p = complete_step(sid, 6)
            assert p is None

    def test_get_status(self, app):
        with app.app_context():
            sid = make_school(app)
            status = get_onboarding_status(sid)
            assert status["started"] is False

    def test_get_status_started(self, app):
        with app.app_context():
            sid = make_school(app)
            start_onboarding(sid)
            status = get_onboarding_status(sid)
            assert status["started"] is True


# ── School Approvals ──
class TestSchoolApprovals:
    def test_approve_user_role_link(self, app):
        with app.app_context():
            sid = make_school(app)
            admin_uid = make_user(app, "school_admin", school_id=sid)
            student_uid = make_user(app, "student", school_id=sid, approved=False)
            # Create role link
            rl = UserRoleLink(user_id=student_uid, school_id=sid, role=UserRole.student)
            db.session.add(rl)
            db.session.commit()
            ok, err = approve_user_role_link(rl.id, admin_uid)
            assert ok is True

    def test_reject_user_role_link(self, app):
        with app.app_context():
            sid = make_school(app)
            admin_uid = make_user(app, "school_admin", school_id=sid)
            student_uid = make_user(app, "student", school_id=sid, approved=False)
            rl = UserRoleLink(user_id=student_uid, school_id=sid, role=UserRole.student)
            db.session.add(rl)
            db.session.commit()
            ok, err = reject_user_role_link(rl.id, admin_uid)
            assert ok is True

    def test_get_school_admins(self, app):
        with app.app_context():
            sid = make_school(app)
            admin_uid = make_user(app, "school_admin", school_id=sid)
            admins = get_school_admins(sid)
            assert len(admins) >= 1

    def test_can_user_approve(self, app):
        with app.app_context():
            sid = make_school(app)
            admin_uid = make_user(app, "school_admin", school_id=sid)
            student_uid = make_user(app, "student", school_id=sid, approved=False)
            rl = UserRoleLink(user_id=student_uid, school_id=sid, role=UserRole.student)
            db.session.add(rl)
            db.session.commit()
            assert can_user_approve(admin_uid, rl.id) is True

    def test_can_user_approve_wrong_role(self, app):
        with app.app_context():
            sid = make_school(app)
            teacher_uid = make_user(app, "teacher", school_id=sid)
            student_uid = make_user(app, "student", school_id=sid, approved=False)
            rl = UserRoleLink(user_id=student_uid, school_id=sid, role=UserRole.student)
            db.session.add(rl)
            db.session.commit()
            assert can_user_approve(teacher_uid, rl.id) is False


# ── Grade Appeals ──
class TestGradeAppeals:
    def test_submit_appeal(self, app):
        with app.app_context():
            a = submit_appeal(1, 1, "I think this is wrong")
            assert a is not None

    def test_submit_empty_reason(self, app):
        with app.app_context():
            a = submit_appeal(1, 1, "")
            assert a is None

    def test_submit_duplicate(self, app):
        with app.app_context():
            submit_appeal(1, 1, "First appeal")
            a = submit_appeal(1, 1, "Second appeal")
            assert a is None

    def test_review_appeal(self, app):
        with app.app_context():
            a = submit_appeal(2, 2, "Wrong grade")
            reviewed = review_appeal(a.id, "approved", "Fixed", 1)
            assert reviewed.status == "approved"

    def test_review_invalid_status(self, app):
        with app.app_context():
            a = submit_appeal(3, 3, "Wrong")
            reviewed = review_appeal(a.id, "invalid", None, 1)
            assert reviewed is None

    def test_pending_appeals(self, app):
        with app.app_context():
            submit_appeal(10, 10, "Fix this")
            pending = get_pending_appeals()
            assert len(pending) >= 1


# ── Rubric ──
class TestRubricServices:
    def test_create_template(self, app):
        with app.app_context():
            sid = make_school(app)
            tid = make_user(app, "teacher", school_id=sid)
            t = create_rubric_template(tid, sid, "Essay Rubric", criteria=[
                {"title": "Content", "max_score": 10},
                {"title": "Grammar", "max_score": 5},
            ])
            assert len(t.criteria) == 2

    def test_get_template(self, app):
        with app.app_context():
            sid = make_school(app)
            tid = make_user(app, "teacher", school_id=sid)
            t = create_rubric_template(tid, sid, "Test")
            fetched = get_rubric_template(t.id)
            assert fetched is not None

    def test_list_templates(self, app):
        with app.app_context():
            sid = make_school(app)
            tid = make_user(app, "teacher", school_id=sid)
            create_rubric_template(tid, sid, "R1")
            create_rubric_template(tid, sid, "R2")
            templates = list_rubric_templates(tid)
            assert len(templates) == 2

    def test_grade_with_rubric(self, app):
        with app.app_context():
            sid = make_school(app)
            tid = make_user(app, "teacher", school_id=sid)
            t = create_rubric_template(tid, sid, "R", criteria=[{"title": "C1", "max_score": 10}])
            c = t.criteria[0]
            grades = grade_with_rubric(1, [{"criterion_id": c.id, "score": 8, "comment": "Good"}], tid)
            assert len(grades) == 1

    def test_rubric_total_score(self, app):
        with app.app_context():
            sid = make_school(app)
            tid = make_user(app, "teacher", school_id=sid)
            t = create_rubric_template(tid, sid, "R", criteria=[
                {"title": "C1", "max_score": 10},
                {"title": "C2", "max_score": 5},
            ])
            grades = grade_with_rubric(5, [
                {"criterion_id": t.criteria[0].id, "score": 8},
                {"criterion_id": t.criteria[1].id, "score": 4},
            ], tid)
            total = rubric_total_score(5)
            assert total == 12.0
