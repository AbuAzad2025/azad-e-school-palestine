"""Tests for services that had 0% coverage: health, gamification, rubric,
grade_appeals, grade_calc, finance, notification_preferences, tenant,
analytics, offline, onboarding, export."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app import create_app
from app.core.security import hash_password
from app.extensions import db as _db
from app.models.class_room import ClassMember, ClassRoom
from app.models.content import Lesson, LessonAttachment
from app.models.gamification import Badge, BadgeCriteriaType
from app.models.gradebook import (
    Assignment,
    GradeCategory,
    GradeEntry,
    GradeItem,
    Submission,
)
from app.models.school import Grade, School, Subject
from app.models.user import User, UserApprovalStatus, UserRole


# ---- Fixtures ----
@pytest.fixture(scope="module")
def app():
    a = create_app()
    a.config["TESTING"] = True
    a.config["WTF_CSRF_ENABLED"] = False
    a.config["EMAIL_ENABLED"] = False
    a.config["TALISMAN_ENABLED"] = False
    a.config["SESSION_COOKIE_SECURE"] = False
    with a.app_context():
        from sqlalchemy import text

        _db.session.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
        _db.session.commit()
        _db.create_all()
    yield a


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def _clean(app):
    yield
    with app.app_context():
        from sqlalchemy import inspect, text

        inspector = inspect(_db.engine)
        tables = inspector.get_table_names(schema="public")
        tables = [t for t in tables if t != "alembic_version"]
        if tables:
            _db.session.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
            _db.session.commit()


def _uid():
    import uuid

    return uuid.uuid4().hex[:10]


def _email():
    return f"u-{_uid()}@test.com"


def _make_user(app, role="student", **kw):
    with app.app_context():
        u = User(
            email=kw.get("email", _email()),
            name_ar=kw.get("name_ar", f"مستخدم {_uid()}"),
            role=UserRole(role),
            password_hash=hash_password("TestPass123!"),
            approval_status=UserApprovalStatus.approved,
            is_active=True,
        )
        _db.session.add(u)
        _db.session.commit()
        return u.id


def _make_school(app, **kw):
    with app.app_context():
        s = School(
            name_ar=kw.get("name_ar", f"مدرسة {_uid()}"),
            name_en=kw.get("name_en", f"School {_uid()}"),
            domain=f"{_uid()}.test.org",
        )
        _db.session.add(s)
        _db.session.commit()
        return s.id


def _make_class(app, school_id, grade_id, subject_id, teacher_id=None):
    with app.app_context():
        c = ClassRoom(
            school_id=school_id,
            grade_id=grade_id,
            subject_id=subject_id,
            teacher_id=teacher_id,
            join_code=f"C-{_uid()[:6]}",
            name=f"صف {_uid()}",
        )
        _db.session.add(c)
        _db.session.commit()
        return c.id


def _make_grade(app, school_id, grade_level=1):
    with app.app_context():
        g = Grade(school_id=school_id, grade_level=grade_level, name_ar=f"صف {grade_level}")
        _db.session.add(g)
        _db.session.commit()
        return g.id


def _make_subject(app):
    with app.app_context():
        s = Subject(name_ar=f"مادة {_uid()}")
        _db.session.add(s)
        _db.session.commit()
        return s.id


# ======================================================================
# health.py tests
# ======================================================================
class TestHealthService:
    def test_check_database_healthy(self, app):
        from app.services.health import check_database

        with app.app_context():
            result = check_database()
            assert result["component"] == "database"
            assert result["status"] == "healthy"
            assert "latency_ms" in result
            assert result["latency_ms"] >= 0

    def test_check_disk_healthy(self, app):
        from app.services.health import check_disk

        with app.app_context():
            result = check_disk()
            assert result["component"] == "disk"
            assert result["status"] in ("healthy", "degraded", "down")
            assert "message" in result

    def test_record_health(self, app):
        from app.services.health import record_health

        with app.app_context():
            hc = record_health({"component": "test", "status": "healthy", "latency_ms": 5, "message": None})
            assert hc.id is not None
            assert hc.component == "test"

    def test_run_all_checks(self, app):
        from app.services.health import run_all_checks

        with app.app_context():
            results = run_all_checks()
            assert len(results) == 2
            assert results[0]["component"] == "database"
            assert results[1]["component"] == "disk"

    def test_get_recent_checks(self, app):
        from app.services.health import get_recent_checks, record_health

        with app.app_context():
            record_health({"component": "db", "status": "healthy", "latency_ms": 1})
            checks = get_recent_checks(hours=24)
            assert len(checks) >= 1

    def test_get_system_status_empty(self, app):
        from app.services.health import get_system_status

        with app.app_context():
            status = get_system_status()
            assert status["overall"] == "unknown"
            assert status["components"] == {}

    def test_get_system_status_healthy(self, app):
        from app.services.health import get_system_status, record_health

        with app.app_context():
            record_health({"component": "db", "status": "healthy", "latency_ms": 1})
            record_health({"component": "disk", "status": "healthy", "latency_ms": 0})
            status = get_system_status()
            assert status["overall"] == "healthy"

    def test_get_system_status_degraded(self, app):
        from app.services.health import get_system_status, record_health

        with app.app_context():
            record_health({"component": "db", "status": "healthy", "latency_ms": 1})
            record_health({"component": "cache", "status": "degraded", "latency_ms": 50})
            status = get_system_status()
            assert status["overall"] == "degraded"

    def test_get_system_status_down(self, app):
        from app.services.health import get_system_status, record_health

        with app.app_context():
            record_health({"component": "db", "status": "down", "latency_ms": 1})
            status = get_system_status()
            assert status["overall"] == "down"


# ======================================================================
# gamification.py tests
# ======================================================================
class TestGamificationService:
    def _make_badge(self, app, criteria_type=BadgeCriteriaType.first_quiz, **kw):
        with app.app_context():
            b = Badge(
                name=kw.get("name", f"شارة {_uid()}"),
                description=kw.get("desc", "اختبار"),
                icon_name=kw.get("icon", "star"),
                criteria_type=criteria_type,
                criteria_value=kw.get("value"),
                is_active=kw.get("is_active", True),
            )
            _db.session.add(b)
            _db.session.commit()
            return b.id

    def test_get_active_badges(self, app):
        from app.services.gamification import get_active_badges

        with app.app_context():
            self._make_badge(app)
            badges = get_active_badges()
            assert len(badges) >= 1

    def test_get_student_badges_empty(self, app):
        from app.services.gamification import get_student_badges

        with app.app_context():
            uid = _make_user(app)
            badges = get_student_badges(uid)
            assert len(badges) == 0

    def test_has_badge_false(self, app):
        from app.services.gamification import has_badge

        with app.app_context():
            uid = _make_user(app)
            bid = self._make_badge(app)
            assert has_badge(uid, bid) is False

    def test_award_badge(self, app):
        from app.services.gamification import award_badge, has_badge

        with app.app_context():
            uid = _make_user(app)
            bid = self._make_badge(app)
            result = award_badge(uid, bid)
            assert result is not None
            assert has_badge(uid, bid) is True

    def test_award_badge_duplicate_returns_none(self, app):
        from app.services.gamification import award_badge

        with app.app_context():
            uid = _make_user(app)
            bid = self._make_badge(app)
            award_badge(uid, bid)
            result = award_badge(uid, bid)
            assert result is None

    def test_check_and_award_first_quiz(self, app):
        from app.services.gamification import check_and_award_badges

        with app.app_context():
            uid = _make_user(app)
            self._make_badge(app, criteria_type=BadgeCriteriaType.first_quiz)
            new_badges = check_and_award_badges(uid, "quiz_submitted")
            assert len(new_badges) >= 1

    def test_check_and_award_perfect_score(self, app):
        from app.services.gamification import check_and_award_badges

        with app.app_context():
            uid = _make_user(app)
            self._make_badge(app, criteria_type=BadgeCriteriaType.perfect_score)
            new_badges = check_and_award_badges(uid, "quiz_submitted", {"score": 100, "max_score": 100})
            assert len(new_badges) >= 1

    def test_check_and_award_perfect_score_not_perfect(self, app):
        from app.services.gamification import check_and_award_badges

        with app.app_context():
            uid = _make_user(app)
            self._make_badge(app, criteria_type=BadgeCriteriaType.perfect_score)
            new_badges = check_and_award_badges(uid, "quiz_submitted", {"score": 80, "max_score": 100})
            assert len(new_badges) == 0

    def test_check_and_award_no_new_event_type(self, app):
        from app.services.gamification import check_and_award_badges

        with app.app_context():
            uid = _make_user(app)
            self._make_badge(app, criteria_type=BadgeCriteriaType.first_quiz)
            new_badges = check_and_award_badges(uid, "daily_login")
            assert len(new_badges) == 0

    def test_check_and_award_early_bird(self, app):
        from app.services.gamification import check_and_award_badges

        with app.app_context():
            uid = _make_user(app)
            self._make_badge(app, criteria_type=BadgeCriteriaType.early_bird)
            future = (datetime.now(UTC) + timedelta(days=2)).isoformat()
            past = datetime.now(UTC).isoformat()
            new_badges = check_and_award_badges(uid, "assignment_submitted", {"deadline": future, "submitted_at": past})
            assert len(new_badges) >= 1

    def test_check_and_award_early_bird_too_late(self, app):
        from app.services.gamification import check_and_award_badges

        with app.app_context():
            uid = _make_user(app)
            self._make_badge(app, criteria_type=BadgeCriteriaType.early_bird)
            now = datetime.now(UTC).isoformat()
            past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
            new_badges = check_and_award_badges(uid, "assignment_submitted", {"deadline": now, "submitted_at": past})
            assert len(new_badges) == 0


# ======================================================================
# rubric.py tests
# ======================================================================
class TestRubricService:
    def test_create_rubric_template(self, app):
        from app.services.rubric import create_rubric_template

        with app.app_context():
            tid = _make_user(app, "teacher")
            sid = _make_school(app)
            t = create_rubric_template(
                tid,
                sid,
                "قالب الاختبار",
                criteria=[{"title": "معيار 1", "max_score": 10}, {"title": "معيار 2", "max_score": 5}],
            )
            assert t.id is not None
            assert len(t.criteria) == 2

    def test_create_rubric_template_no_criteria(self, app):
        from app.services.rubric import create_rubric_template

        with app.app_context():
            tid = _make_user(app, "teacher")
            sid = _make_school(app)
            t = create_rubric_template(tid, sid, "قالب بسيط")
            assert t.id is not None

    def test_get_rubric_template(self, app):
        from app.services.rubric import create_rubric_template, get_rubric_template

        with app.app_context():
            tid = _make_user(app, "teacher")
            sid = _make_school(app)
            t = create_rubric_template(tid, sid, "قالب")
            found = get_rubric_template(t.id)
            assert found is not None

    def test_list_rubric_templates(self, app):
        from app.services.rubric import create_rubric_template, list_rubric_templates

        with app.app_context():
            tid = _make_user(app, "teacher")
            sid = _make_school(app)
            create_rubric_template(tid, sid, "قالب 1")
            create_rubric_template(tid, sid, "قالب 2")
            result = list_rubric_templates(tid)
            assert len(result) == 2

    def test_grade_with_rubric(self, app):
        from app.services.rubric import create_rubric_template, get_rubric_grades, grade_with_rubric, rubric_total_score

        with app.app_context():
            tid = _make_user(app, "teacher")
            sid = _make_school(app)
            gid = _make_grade(app, sid)
            subjid = _make_subject(app)
            cid = _make_class(app, sid, gid, subjid, tid)
            aid_obj = Assignment(class_id=cid, title="واجب")
            _db.session.add(aid_obj)
            _db.session.commit()
            sid2 = _make_user(app)
            sub = Submission(assignment_id=aid_obj.id, student_id=sid2, body="جواب")
            _db.session.add(sub)
            _db.session.commit()
            t = create_rubric_template(tid, sid, "قالب", criteria=[{"title": "م1", "max_score": 10}])
            criterion = t.criteria[0]
            result = grade_with_rubric(sub.id, [{"criterion_id": criterion.id, "score": 8.5, "comment": "جيد"}], tid)
            assert len(result) == 1
            grades = get_rubric_grades(sub.id)
            assert len(grades) == 1
            assert rubric_total_score(sub.id) == 8.5

    def test_grade_with_rubric_update_existing(self, app):
        from app.services.rubric import create_rubric_template, grade_with_rubric

        with app.app_context():
            tid = _make_user(app, "teacher")
            sid = _make_school(app)
            gid = _make_grade(app, sid)
            subjid = _make_subject(app)
            cid = _make_class(app, sid, gid, subjid, tid)
            aid_obj = Assignment(class_id=cid, title="واجب")
            _db.session.add(aid_obj)
            _db.session.commit()
            sid2 = _make_user(app)
            sub = Submission(assignment_id=aid_obj.id, student_id=sid2, body="جواب")
            _db.session.add(sub)
            _db.session.commit()
            t = create_rubric_template(tid, sid, "ق", criteria=[{"title": "م1", "max_score": 10}])
            c = t.criteria[0]
            grade_with_rubric(sub.id, [{"criterion_id": c.id, "score": 5, "comment": None}], tid)
            result = grade_with_rubric(sub.id, [{"criterion_id": c.id, "score": 9, "comment": "تحسن"}], tid)
            assert result[0].score == 9


# ======================================================================
# grade_appeals.py tests
# ======================================================================
class TestGradeAppealsService:
    def _make_submission(self, app):
        tid = _make_user(app, "teacher")
        sid = _make_school(app)
        gid = _make_grade(app, sid)
        subjid = _make_subject(app)
        cid = _make_class(app, sid, gid, subjid, tid)
        a = Assignment(class_id=cid, title="واجب")
        _db.session.add(a)
        _db.session.commit()
        student_id = _make_user(app)
        sub = Submission(assignment_id=a.id, student_id=student_id, body="جواب")
        _db.session.add(sub)
        _db.session.commit()
        return sub.id, student_id, cid

    def test_submit_appeal(self, app):
        from app.services.grade_appeals import submit_appeal

        with app.app_context():
            sub_id, student_id, _ = self._make_submission(app)
            appeal = submit_appeal(sub_id, student_id, "الدرجة غير صحيحة")
            assert appeal is not None
            assert appeal.status == "pending"

    def test_submit_appeal_empty_reason_returns_none(self, app):
        from app.services.grade_appeals import submit_appeal

        with app.app_context():
            sub_id, student_id, _ = self._make_submission(app)
            assert submit_appeal(sub_id, student_id, "") is None
            assert submit_appeal(sub_id, student_id, None) is None

    def test_submit_appeal_duplicate_returns_none(self, app):
        from app.services.grade_appeals import submit_appeal

        with app.app_context():
            sub_id, student_id, _ = self._make_submission(app)
            submit_appeal(sub_id, student_id, "أول")
            assert submit_appeal(sub_id, student_id, "ثاني") is None

    def test_review_appeal_approve(self, app):
        from app.services.grade_appeals import review_appeal, submit_appeal

        with app.app_context():
            sub_id, student_id, _ = self._make_submission(app)
            appeal = submit_appeal(sub_id, student_id, "خطأ")
            reviewer = _make_user(app, "teacher")
            result = review_appeal(appeal.id, "approved", "تمت المراجعة", reviewer)
            assert result.status == "approved"

    def test_review_appeal_reject(self, app):
        from app.services.grade_appeals import review_appeal, submit_appeal

        with app.app_context():
            sub_id, student_id, _ = self._make_submission(app)
            appeal = submit_appeal(sub_id, student_id, "خطأ")
            reviewer = _make_user(app, "teacher")
            result = review_appeal(appeal.id, "rejected", "مرفوض", reviewer)
            assert result.status == "rejected"

    def test_review_appeal_invalid_status(self, app):
        from app.services.grade_appeals import review_appeal, submit_appeal

        with app.app_context():
            sub_id, student_id, _ = self._make_submission(app)
            appeal = submit_appeal(sub_id, student_id, "خطأ")
            reviewer = _make_user(app, "teacher")
            assert review_appeal(appeal.id, "invalid", None, reviewer) is None

    def test_review_appeal_nonexistent(self, app):
        from app.services.grade_appeals import review_appeal

        with app.app_context():
            reviewer = _make_user(app, "teacher")
            assert review_appeal(99999, "approved", None, reviewer) is None

    def test_get_student_appeals(self, app):
        from app.services.grade_appeals import get_student_appeals, submit_appeal

        with app.app_context():
            sub_id, student_id, _ = self._make_submission(app)
            submit_appeal(sub_id, student_id, "سبب")
            appeals = get_student_appeals(student_id)
            assert len(appeals) == 1

    def test_get_pending_appeals(self, app):
        from app.services.grade_appeals import get_pending_appeals, submit_appeal

        with app.app_context():
            sub_id, student_id, _ = self._make_submission(app)
            submit_appeal(sub_id, student_id, "سبب")
            pending = get_pending_appeals()
            assert len(pending) == 1


# ======================================================================
# grade_calc.py tests
# ======================================================================
class TestGradeCalcService:
    def _setup_grades(self, app):
        tid = _make_user(app, "teacher")
        sid = _make_school(app)
        gid = _make_grade(app, sid)
        subjid = _make_subject(app)
        cid = _make_class(app, sid, gid, subjid, tid)
        cat = GradeCategory(class_id=cid, name="الفصل الأول", weight=Decimal("0.60"))
        _db.session.add(cat)
        _db.session.commit()
        item = GradeItem(class_id=cid, category_id=cat.id, title="اختبار 1", max_mark=Decimal("20"))
        _db.session.add(item)
        _db.session.commit()
        student = _make_user(app)
        cm = ClassMember(class_id=cid, user_id=student, status="active")
        _db.session.add(cm)
        _db.session.commit()
        entry = GradeEntry(student_id=student, grade_item_id=item.id, mark=Decimal("16"))
        _db.session.add(entry)
        _db.session.commit()
        return cid, student

    def test_calculate_student_grade(self, app):
        from app.services.grade_calc import calculate_student_grade

        with app.app_context():
            cid, student = self._setup_grades(app)
            result = calculate_student_grade(student, cid)
            assert result["final_grade"] > 0
            assert result["letter_grade"] in ["ممتاز", "جيد جداً", "جيد", "مقبول", "راسب"]
            assert len(result["categories"]) == 1

    def test_calculate_student_grade_no_grades(self, app):
        from app.services.grade_calc import calculate_student_grade

        with app.app_context():
            tid = _make_user(app, "teacher")
            sid = _make_school(app)
            gid = _make_grade(app, sid)
            subjid = _make_subject(app)
            cid = _make_class(app, sid, gid, subjid, tid)
            student = _make_user(app)
            result = calculate_student_grade(student, cid)
            assert result["final_grade"] == 0

    def test_class_grades_summary(self, app):
        from app.services.grade_calc import class_grades_summary

        with app.app_context():
            cid, student = self._setup_grades(app)
            result = class_grades_summary(cid)
            assert len(result) >= 1
            assert result[0]["student_id"] == student


# ======================================================================
# finance.py tests
# ======================================================================
class TestFinanceService:
    def test_school_revenue_summary_empty(self, app):
        from app.services.finance import school_revenue_summary

        with app.app_context():
            sid = _make_school(app)
            result = school_revenue_summary(sid)
            assert result["total_revenue"] == Decimal("0")
            assert result["active_count"] == 0

    def test_student_balance_no_subscription(self, app):
        from app.services.finance import student_balance

        with app.app_context():
            uid = _make_user(app)
            result = student_balance(uid, 999)
            assert result["has_subscription"] is False

    def test_accounts_receivable_empty(self, app):
        from app.services.finance import accounts_receivable

        with app.app_context():
            sid = _make_school(app)
            result = accounts_receivable(sid)
            assert len(result) == 0


# ======================================================================
# notification_preferences.py tests
# ======================================================================
class TestNotificationPreferencesService:
    def test_get_preferences_empty(self, app):
        from app.services.notification_preferences import get_preferences

        with app.app_context():
            uid = _make_user(app)
            prefs = get_preferences(uid)
            assert len(prefs) == 0

    def test_update_preference_create(self, app):
        from app.services.notification_preferences import get_preference, update_preference

        with app.app_context():
            uid = _make_user(app)
            pref = update_preference(uid, "result", True, False)
            assert pref.email_enabled is True
            assert pref.in_app_enabled is False
            found = get_preference(uid, "result")
            assert found is not None

    def test_update_preference_update(self, app):
        from app.services.notification_preferences import get_preference, update_preference

        with app.app_context():
            uid = _make_user(app)
            update_preference(uid, "result", True, True)
            update_preference(uid, "result", False, True)
            found = get_preference(uid, "result")
            assert found.email_enabled is False

    def test_should_notify_default(self, app):
        from app.services.notification_preferences import should_notify

        with app.app_context():
            uid = _make_user(app)
            assert should_notify(uid, "result", "in_app") is True
            assert should_notify(uid, "result", "email") is True

    def test_should_notify_disabled(self, app):
        from app.services.notification_preferences import should_notify, update_preference

        with app.app_context():
            uid = _make_user(app)
            update_preference(uid, "result", False, False)
            assert should_notify(uid, "result", "in_app") is False
            assert should_notify(uid, "result", "email") is False


# ======================================================================
# tenant.py tests
# ======================================================================
class TestTenantService:
    def test_get_quota_creates_default(self, app):
        from app.services.tenant import get_quota

        with app.app_context():
            sid = _make_school(app)
            q = get_quota(sid)
            assert q.tier == "free"
            assert q.max_students == 50

    def test_check_quota_students_ok(self, app):
        from app.services.tenant import check_quota

        with app.app_context():
            sid = _make_school(app)
            ok, msg = check_quota(sid, "students")
            assert ok is True

    def test_check_quota_ai_disabled(self, app):
        from app.services.tenant import check_quota

        with app.app_context():
            sid = _make_school(app)
            ok, msg = check_quota(sid, "ai")
            assert ok is False

    def test_check_quota_classes_ok(self, app):
        from app.services.tenant import check_quota

        with app.app_context():
            sid = _make_school(app)
            ok, msg = check_quota(sid, "classes")
            assert ok is True

    def test_set_tier(self, app):
        from app.services.tenant import set_tier

        with app.app_context():
            sid = _make_school(app)
            q, err = set_tier(sid, "pro")
            assert err is None
            assert q.tier == "pro"
            assert q.ai_enabled is True

    def test_set_tier_invalid(self, app):
        from app.services.tenant import set_tier

        with app.app_context():
            sid = _make_school(app)
            q, err = set_tier(sid, "nonexistent")
            assert q is None
            assert err is not None


# ======================================================================
# analytics.py tests
# ======================================================================
class TestAnalyticsService:
    def test_get_analytics_data(self, app):
        from app.services.analytics import get_analytics_data

        with app.app_context():
            data = get_analytics_data(days=30)
            assert "dau" in data
            assert "new_users" in data
            assert "role_distribution" in data
            assert "total_lessons" in data
            assert "tutoring_sessions" in data
            assert "family_links" in data


# ======================================================================
# offline.py tests
# ======================================================================
class TestOfflineService:
    def _make_attachment(self, app):
        sid = _make_school(app)
        gid = _make_grade(app, sid)
        subjid = _make_subject(app)
        cid = _make_class(app, sid, gid, subjid)
        lesson = Lesson(class_id=cid, title="درس", status="published", sort_order=1)
        _db.session.add(lesson)
        _db.session.commit()
        att = LessonAttachment(lesson_id=lesson.id, kind="video", stored_name="test.mp4")
        _db.session.add(att)
        _db.session.commit()
        return att.id, lesson.id

    def test_mark_for_download(self, app):
        from app.services.offline import mark_for_download

        with app.app_context():
            uid = _make_user(app)
            att_id, lesson_id = self._make_attachment(app)
            result = mark_for_download(uid, att_id, lesson_id)
            assert result is not None
            assert result.status == "ready"

    def test_mark_for_download_duplicate(self, app):
        from app.services.offline import mark_for_download

        with app.app_context():
            uid = _make_user(app)
            att_id, lesson_id = self._make_attachment(app)
            mark_for_download(uid, att_id, lesson_id)
            result = mark_for_download(uid, att_id, lesson_id)
            assert result is None

    def test_get_offline_items(self, app):
        from app.services.offline import get_offline_items, mark_for_download

        with app.app_context():
            uid = _make_user(app)
            att_id, lesson_id = self._make_attachment(app)
            mark_for_download(uid, att_id, lesson_id)
            items = get_offline_items(uid)
            assert len(items) == 1

    def test_remove_offline(self, app):
        from app.services.offline import get_offline_items, mark_for_download, remove_offline

        with app.app_context():
            uid = _make_user(app)
            att_id, lesson_id = self._make_attachment(app)
            dl = mark_for_download(uid, att_id, lesson_id)
            remove_offline(dl.id)
            items = get_offline_items(uid)
            assert len(items) == 0

    def test_expire_old_downloads(self, app):
        from app.services.offline import expire_old_downloads

        with app.app_context():
            count = expire_old_downloads()
            assert count == 0


# ======================================================================
# onboarding.py tests
# ======================================================================
class TestOnboardingService:
    def test_get_wizard_steps(self, app):
        from app.services.onboarding import get_wizard_steps

        steps = get_wizard_steps()
        assert len(steps) == 5

    def test_start_onboarding(self, app):
        from app.services.onboarding import start_onboarding

        with app.app_context():
            sid = _make_school(app)
            p = start_onboarding(sid)
            assert p.current_step == 1
            assert p.is_complete is False

    def test_start_onboarding_existing(self, app):
        from app.services.onboarding import start_onboarding

        with app.app_context():
            sid = _make_school(app)
            p1 = start_onboarding(sid)
            p2 = start_onboarding(sid)
            assert p1.id == p2.id

    def test_complete_step(self, app):
        from app.services.onboarding import complete_step, start_onboarding

        with app.app_context():
            sid = _make_school(app)
            start_onboarding(sid)
            result = complete_step(sid, 1, {"name": "مدرسة"})
            assert result is not None
            assert result.current_step == 2

    def test_complete_step_invalid(self, app):
        from app.services.onboarding import complete_step

        with app.app_context():
            sid = _make_school(app)
            assert complete_step(sid, 0) is None
            assert complete_step(sid, 6) is None

    def test_complete_step_not_started(self, app):
        from app.services.onboarding import complete_step

        with app.app_context():
            sid = _make_school(app)
            assert complete_step(sid, 1) is None

    def test_complete_all_steps(self, app):
        from app.services.onboarding import complete_step, start_onboarding

        with app.app_context():
            sid = _make_school(app)
            start_onboarding(sid)
            for i in range(1, 6):
                complete_step(sid, i)
            from app.services.onboarding import get_onboarding

            p = get_onboarding(sid)
            assert p.is_complete is True
            assert p.completed_at is not None

    def test_get_onboarding_status_not_started(self, app):
        from app.services.onboarding import get_onboarding_status

        with app.app_context():
            sid = _make_school(app)
            status = get_onboarding_status(sid)
            assert status["started"] is False

    def test_get_onboarding_status_started(self, app):
        from app.services.onboarding import get_onboarding_status, start_onboarding

        with app.app_context():
            sid = _make_school(app)
            start_onboarding(sid)
            status = get_onboarding_status(sid)
            assert status["started"] is True
            assert status["current_step"] == 1


# ======================================================================
# export.py tests
# ======================================================================
class TestExportService:
    def _setup_class_with_members(self, app):
        sid = _make_school(app)
        gid = _make_grade(app, sid)
        subjid = _make_subject(app)
        tid = _make_user(app, "teacher")
        cid = _make_class(app, sid, gid, subjid, tid)
        student = _make_user(app)
        cm = ClassMember(class_id=cid, user_id=student, status="active")
        _db.session.add(cm)
        _db.session.commit()
        return cid, student, sid

    def test_export_students_excel(self, app):
        from app.services.export import export_students_excel

        with app.app_context():
            cid, _, _ = self._setup_class_with_members(app)
            data = export_students_excel(cid)
            assert len(data) > 0

    def test_export_grades_excel(self, app):
        from app.services.export import export_grades_excel

        with app.app_context():
            cid, _, _ = self._setup_class_with_members(app)
            data = export_grades_excel(cid)
            assert len(data) > 0

    def test_export_progress_excel(self, app):
        from app.services.export import export_progress_excel

        with app.app_context():
            cid, _, _ = self._setup_class_with_members(app)
            data = export_progress_excel(cid)
            assert len(data) > 0

    def test_export_moe_format(self, app):
        from app.services.export import export_moe_format

        with app.app_context():
            data = export_moe_format()
            assert len(data) > 0


# ======================================================================
# report_card.py tests
# ======================================================================
class TestReportCardService:
    def test_calculate_gpa_no_memberships(self, app):
        from app.services.report_card import calculate_gpa

        with app.app_context():
            uid = _make_user(app)
            sid = _make_school(app)
            result = calculate_gpa(uid, sid)
            assert result["gpa"] == 0
            assert result["classes"] == []

    def test_generate_report_card(self, app):
        from app.services.report_card import generate_report_card

        with app.app_context():
            sid = _make_school(app)
            gid = _make_grade(app, sid)
            subjid = _make_subject(app)
            tid = _make_user(app, "teacher")
            cid = _make_class(app, sid, gid, subjid, tid)
            student = _make_user(app)
            cm = ClassMember(class_id=cid, user_id=student, status="active")
            _db.session.add(cm)
            _db.session.commit()
            result = generate_report_card(student, cid)
            assert result["student"] is not None
            assert result["class_room"] is not None
            assert "grade_data" in result

    def test_letter_grade(self, app):
        from app.services.report_card import _letter_grade

        assert _letter_grade(95) == "ممتاز"
        assert _letter_grade(85) == "جيد جداً"
        assert _letter_grade(75) == "جيد"
        assert _letter_grade(65) == "مقبول"
        assert _letter_grade(50) == "راسب"
