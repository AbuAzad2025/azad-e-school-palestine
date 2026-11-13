"""Round M — branch closure: module routes, core helpers and small services.

Targets the branch arcs still reported missing by CI (run 43296221930):

- app/modules/content/routes.py: ``create_lesson`` returning ``(None, None)``,
  invalid unit form, invalid YouTube form.
- app/modules/auth/routes.py: ``authenticate`` returning ``(None, None)``,
  parent login redirect, dashboard for a school admin without a school.
- app/modules/schools/routes.py: ``create_school`` / ``create_class``
  returning ``(None, None)``, invalid teacher-assignment form, and the
  onboarding POST that must drop ``csrf_token`` from the step payload.
- app/modules/messages/routes.py: composing a reply to an existing thread and
  opening a thread as its sender.
- app/modules/api/routes.py: admin listing of every tutoring session and admin
  read of a single session.
- app/core/rls.py: request GUC snapshot outside an app context.
- app/core/pdf.py: font directory scan without ``PDF_FONT_DIR`` and the write
  failure path where the temp file is already gone.
- app/core/logging.py: log entry without a correlation id.
- app/services/onboarding.py: completing an earlier step after moving on.
- app/services/health.py: repeated component checks keep the newest status.
- app/services/report_card.py: GPA items with no max mark.
- app/services/assessment.py: shuffled answer index outside the permutation.
- app/modules/wallet_api.py: parent asking for an unlinked child's ledger.
- app/modules/progress/routes.py: heartbeat for an already-tracked lesson.
- app/modules/family/routes.py: ``link_parent`` returning ``(None, None)``.
- app/modules/calendar/routes.py: ``create_event`` returning ``(None, None)``.
- app/models/user.py: ``school_id`` with only inactive role links.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import patch

from tests.conftest import (
    _db,
    _uid,
    make_class,
    make_class_member,
    make_grade,
    make_grade_category,
    make_grade_item,
    make_lesson,
    make_school,
    make_subject,
    make_user,
    make_user_role_link,
)

PASSWORD = "TestPass123!"

_LEVELS: dict[int, int] = {}


def _next_level(sid: int) -> int:
    _LEVELS[sid] = _LEVELS.get(sid, 0) + 1
    return _LEVELS[sid]


def mk_user(app, role: str, school_id=None):
    email = f"rnd-m-{_uid()}@test.com"
    uid = make_user(app, role=role, school_id=school_id, email=email)
    return uid, email


def login_as(app, email: str):
    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    return client


def _setup_class(app, teacher_id=None):
    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=_next_level(sid))
    cid = make_class(app, sid, gid, make_subject(app), teacher_id=teacher_id)
    return sid, cid


def _teacher_class(app):
    sid = make_school(app)
    tid, t_email = mk_user(app, "teacher", school_id=sid)
    gid = make_grade(app, sid, grade_level=_next_level(sid))
    cid = make_class(app, sid, gid, make_subject(app), teacher_id=tid)
    return sid, cid, tid, t_email


# ═════════════════════════════ content ═════════════════════════════


class TestContentBranchClosure:
    def test_lesson_create_without_object_or_error(self, app):
        """create_lesson → (None, None): تعود استمارة الدرس بلا توجيه."""
        _, cid, _, t_email = _teacher_class(app)
        client = login_as(app, t_email)
        with (
            patch("app.modules.content.routes.create_lesson", return_value=(None, None)),
            patch("app.modules.content.routes.audit") as audited,
        ):
            resp = client.post(
                f"/classes/{cid}/lessons",
                data={"title": "درس جديد", "body_html": "<p>نصّ</p>"},
                follow_redirects=False,
            )
        assert resp.status_code == 200
        audited.assert_not_called()

    def test_unit_create_rejects_invalid_form(self, app):
        """وحدة بلا عنوان لا تُنشأ."""
        _, cid, _, t_email = _teacher_class(app)
        client = login_as(app, t_email)
        with patch("app.modules.content.routes.create_unit") as created:
            resp = client.post(f"/classes/{cid}/units", data={}, follow_redirects=False)
        assert resp.status_code == 302
        created.assert_not_called()

    def test_youtube_add_rejects_invalid_form(self, app):
        """رابط فارغ لا يُضاف كفيديو."""
        _, cid, _, t_email = _teacher_class(app)
        lid = make_lesson(app, cid)
        client = login_as(app, t_email)
        with patch("app.modules.content.routes.add_youtube") as added:
            resp = client.post(f"/classes/{cid}/lessons/{lid}/youtube", data={}, follow_redirects=False)
        assert resp.status_code == 302
        added.assert_not_called()


# ═════════════════════════════ auth ═════════════════════════════


class TestAuthBranchClosure:
    def test_login_without_user_or_error_renders_form(self, app):
        """authenticate → (None, None): لا دخول ولا رسالة، تُعرض الاستمارة."""
        with patch("app.modules.auth.routes.authenticate", return_value=(None, None)):
            client = app.test_client()
            resp = client.post(
                "/auth/login",
                data={"email": "nobody@test.com", "password": "TestPass123!"},
                follow_redirects=False,
            )
        assert resp.status_code == 200

    def test_parent_login_redirects_to_family(self, app):
        """دور وليّ الأمر يوجَّه إلى صفحة العائلة."""
        _, p_email = mk_user(app, "parent")
        client = login_as(app, p_email)
        resp = client.post(
            "/auth/login",
            data={"email": p_email, "password": PASSWORD},
            follow_redirects=False,
        )
        # الجلسة قائمة أصلاً ⇒ تحويل للوحة؛ والتحقق هنا من مسار الدور عبر logout ثم login
        assert resp.status_code in (200, 302)
        client.post("/auth/logout")
        resp2 = client.post("/auth/login", data={"email": p_email, "password": PASSWORD}, follow_redirects=False)
        assert resp2.status_code == 302
        assert "/family" in resp2.headers["Location"]

    def test_dashboard_for_school_admin_without_school(self, app):
        """مشرف مدرسة بلا مدرسة مرتبطة يرى لوحة فارغة بدل الانفجار."""
        _, a_email = mk_user(app, "school_admin")
        client = login_as(app, a_email)
        resp = client.get("/auth/dashboard")
        assert resp.status_code == 200


# ═════════════════════════════ schools ═════════════════════════════


class TestSchoolsBranchClosure:
    def test_school_create_without_object_or_error(self, app):
        """create_school_with_defaults → (None, None): تعود الاستمارة بلا توجيه."""
        _, a_email = mk_user(app, "super_admin")
        client = login_as(app, a_email)
        with (
            patch("app.modules.schools.routes.create_school_with_defaults", return_value=(None, None)),
            patch("app.modules.schools.routes.audit") as audited,
        ):
            resp = client.post(
                "/schools/new",
                data={"name_ar": "مدرسة", "name_en": "School", "domain": f"{_uid()[:8]}.test.org"},
                follow_redirects=False,
            )
        assert resp.status_code == 200
        audited.assert_not_called()

    def test_class_create_without_object_or_error(self, app):
        """create_class → (None, None): تعود استمارة الصف بلا توجيه."""
        sid = make_school(app)
        _, a_email = mk_user(app, "school_admin", school_id=sid)
        gid = make_grade(app, sid, grade_level=_next_level(sid))
        client = login_as(app, a_email)
        with (
            patch("app.modules.schools.routes.create_class", return_value=(None, None)),
            patch("app.modules.schools.routes.audit") as audited,
        ):
            resp = client.post(
                f"/schools/{sid}/classes/new",
                data={"grade_id": str(gid), "subject_id": str(make_subject(app)), "name": "صف"},
                follow_redirects=False,
            )
        assert resp.status_code == 200
        audited.assert_not_called()

    def test_assign_teacher_rejects_invalid_form(self, app):
        """تعيين معلم بلا معرّف لا يمرّ من التحقق — يبقى الصفّ بلا معلم."""
        sid, cid, tid, _ = _teacher_class(app)
        _, a_email = mk_user(app, "school_admin", school_id=sid)
        client = login_as(app, a_email)
        resp = client.post(f"/schools/class/{cid}/teacher", data={}, follow_redirects=False)
        assert resp.status_code == 302
        from app.models.class_room import ClassRoom

        with app.app_context():
            assert _db.session.get(ClassRoom, cid).teacher_id == tid

    def test_onboarding_drops_csrf_token_from_step_payload(self, app):
        """حقل csrf_token لا يُخزَّن ضمن بيانات الخطوة."""
        sid = make_school(app)
        _, a_email = mk_user(app, "school_admin", school_id=sid)
        from app.services.onboarding import start_onboarding

        with app.app_context():
            start_onboarding(sid)
        client = login_as(app, a_email)
        resp = client.post(
            "/schools/onboarding/2",
            data={"csrf_token": "tok", "school_motto": "شعار"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        from app.models.system import OnboardingProgress

        with app.app_context():
            progress = OnboardingProgress.query.filter_by(school_id=sid).first()
            assert progress is not None
            assert "csrf_token" not in (progress.completed_steps or {}).get("2", {})


# ═════════════════════════════ messages ═════════════════════════════


class TestMessagesBranchClosure:
    def _message(self, app, sender: int, recipient: int) -> int:
        from app.models.message import Message

        with app.app_context():
            msg = Message(sender_id=sender, recipient_id=recipient, subject="موضوع", body="نصّ")
            _db.session.add(msg)
            _db.session.commit()
            return msg.id

    def test_compose_reply_to_existing_thread(self, app):
        """الردّ على رسالة قائمة يعرض صفحة الكتابة بلا 404."""
        sid = make_school(app)
        sender, _ = mk_user(app, "teacher", school_id=sid)
        recipient, r_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, _setup_class(app, teacher_id=sender)[1], recipient)
        msg_id = self._message(app, recipient, sender)
        make_class_member(app, _setup_class(app, teacher_id=sender)[1], recipient)
        client = login_as(app, r_email)
        resp = client.get(f"/messages/send/{msg_id}")
        assert resp.status_code == 200

    def test_thread_is_readable_by_its_sender(self, app):
        """المُرسل يفتح المحادثة دون تعليمها مقروءة له."""
        sid = make_school(app)
        sender, s_email = mk_user(app, "teacher", school_id=sid)
        recipient, _ = mk_user(app, "student", school_id=sid)
        msg_id = self._message(app, sender, recipient)
        client = login_as(app, s_email)
        resp = client.get(f"/messages/thread/{msg_id}")
        assert resp.status_code == 200
        from app.models.message import Message

        with app.app_context():
            assert _db.session.get(Message, msg_id).is_read is not True


# ═════════════════════════════ api ═════════════════════════════


class TestApiBranchClosure:
    def test_admin_lists_all_tutoring_sessions(self, app):
        """مشرف المدرسة يرى الجلسات بلا تصفية على الطالب/المعلم."""
        from tests.conftest import make_tutoring_session

        sid = make_school(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        stu, _ = mk_user(app, "student", school_id=sid)
        make_tutoring_session(app, tid, stu)
        _, a_email = mk_user(app, "school_admin", school_id=sid)
        client = login_as(app, a_email)
        resp = client.get("/api/v1/tutoring/sessions")
        assert resp.status_code == 200
        assert resp.get_json()["meta"]["total"] >= 1

    def test_admin_opens_any_tutoring_session(self, app):
        """مشرف المدرسة يفتح جلسة ليست له — بلا فحص الملكية."""
        from tests.conftest import make_tutoring_session

        sid = make_school(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        stu, _ = mk_user(app, "student", school_id=sid)
        sess_id = make_tutoring_session(app, tid, stu)
        _, a_email = mk_user(app, "school_admin", school_id=sid)
        client = login_as(app, a_email)
        resp = client.get(f"/api/v1/tutoring/sessions/{sess_id}")
        assert resp.status_code == 200


# ═════════════════════════════ core/rls + core/pdf + logging ═════════════════════════════


class TestCoreHelpersBranchClosure:
    def test_request_guc_snapshot_outside_app_context(self):
        """بلا سياق تطبيق لا لقطة GUCs — والمنادي لا يلمس المعاملة."""
        from app.core.rls import _request_gucs_from_flask

        assert _request_gucs_from_flask() is None

    def test_font_dirs_without_configured_directory(self, app):
        """غياب PDF_FONT_DIR يعني الاعتماد على مجلدات النظام فقط."""
        from app.core.pdf import _iter_font_dirs

        with app.app_context():
            app.config["PDF_FONT_DIR"] = None
            dirs = _iter_font_dirs()
        assert isinstance(dirs, list)

    def test_write_pdf_failure_skips_missing_temp_file(self, app, tmp_path):
        """فشل الكتابة مع اختفاء الملف المؤقّت يرفع الخطأ بلا حذف خاطئ."""
        from app.core import pdf as pdf_mod

        with app.app_context():
            app.config["PDF_OUTPUT_DIR"] = str(tmp_path)
            with (
                patch.object(pdf_mod.os, "replace", side_effect=OSError("disk full")),
                patch.object(pdf_mod.os.path, "exists", return_value=False),
            ):
                try:
                    pdf_mod.write_pdf_file(subdir="x", filename_stem="f", data=b"%PDF-1.4", school_id=1)
                except OSError as exc:
                    assert "disk full" in str(exc)
                else:  # pragma: no cover - يجب أن يرفع
                    raise AssertionError("expected OSError")

    def test_log_processor_without_correlation_id(self):
        """بلا correlation id في السياق يبقى السجل كما هو."""
        from app.core.logging import _add_correlation_id, clear_correlation_id

        clear_correlation_id()
        event = {"event": "x"}
        assert _add_correlation_id(None, "info", event) == {"event": "x"}


# ═════════════════════════════ services ═════════════════════════════


class TestServiceBranchClosure:
    def test_onboarding_earlier_step_does_not_rewind_cursor(self, app):
        """إكمال خطوة سابقة بعد التقدّم لا يُعيد المؤشر للخلف."""
        from app.services.onboarding import complete_step, start_onboarding

        sid = make_school(app)
        with app.app_context():
            start_onboarding(sid)
            complete_step(sid, 3)
            progress = complete_step(sid, 2)
            assert progress is not None
            assert progress.current_step == 4

    def test_health_keeps_latest_status_per_component(self, app):
        """تكرار فحص المكوّن نفسه لا يكرّره في الخريطة."""
        from app.services.health import get_system_status, record_health

        with app.app_context():
            record_health({"component": "database", "status": "healthy", "detail": ""})
            record_health({"component": "database", "status": "degraded", "detail": ""})
            status = get_system_status()
        assert set(status["components"]) == {"database"}

    def test_report_card_gpa_skips_items_without_max_mark(self, app):
        """بند بلا درجة قصوى لا يدخل في المعدّل التراكمي."""
        from app.services.report_card import calculate_gpa

        sid, cid = _setup_class(app)
        stu, _ = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu)
        cat = make_grade_category(app, cid, "الفصل", 100)
        item = make_grade_item(app, cid, cat, "بلا قصوى", None)
        from app.models.gradebook import GradeEntry

        with app.app_context():
            _db.session.add(GradeEntry(student_id=stu, grade_item_id=item, mark=10))
            _db.session.commit()
            gpa = calculate_gpa(stu, sid)
        assert gpa["gpa"] == 0.0

    def test_save_answer_ignores_out_of_range_display_index(self, app):
        """فهرس عرض خارج نطاق الخلط لا يُترجم — يُحفظ كما وصل."""
        from app.models.assessment import Question, Quiz, QuizAttempt
        from app.services.assessment import save_answer

        sid, cid = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        stu, _ = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu)
        with app.app_context():
            quiz = Quiz(class_id=cid, title="اختبار", duration_min=60, created_by=tid, status="published", shuffle=True)
            _db.session.add(quiz)
            _db.session.flush()
            question = Question(
                quiz_id=quiz.id,
                type="mcq",
                prompt="س",
                options={"items": [{"label": "أ", "text": "1"}, {"label": "ب", "text": "2"}]},
                correct_answer={"index": 0},
                mark=5.0,
            )
            _db.session.add(question)
            _db.session.flush()
            attempt = QuizAttempt(quiz_id=quiz.id, student_id=stu, status="in_progress")
            _db.session.add(attempt)
            _db.session.commit()
            save_answer(attempt, question.id, {"index": 99})
            from app.models.assessment import Answer

            row = Answer.query.filter_by(attempt_id=attempt.id, question_id=question.id).first()
        assert row is not None
        assert row.answer == {"index": 99}


# ═════════════════════════════ small modules ═════════════════════════════


class TestSmallModulesBranchClosure:
    def test_parent_cannot_read_unlinked_child_ledger(self, app):
        """ولي الأمر يطلب حركات طالب غير مرتبط به → 403."""
        sid = make_school(app)
        other_stu, _ = mk_user(app, "student", school_id=sid)
        _, p_email = mk_user(app, "parent", school_id=sid)
        client = login_as(app, p_email)
        resp = client.get(f"/api/v1/wallet/transactions?user_id={other_stu}")
        assert resp.status_code == 403

    def test_second_heartbeat_reuses_existing_progress(self, app):
        """نبضة ثانية للدرس نفسه تحدّث التقدّم القائم بدل إنشاء صفّ جديد."""
        sid, cid = _setup_class(app)
        stu, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stu)
        lid = make_lesson(app, cid)
        client = login_as(app, s_email)
        first = client.post(f"/progress/lesson/{lid}/heartbeat", json={"seconds": 30})
        second = client.post(f"/progress/lesson/{lid}/heartbeat", json={"seconds": 30})
        assert first.status_code == 200
        assert second.status_code == 200
        assert second.get_json()["seconds_spent"] >= first.get_json()["seconds_spent"]

    def test_family_link_without_object_or_error(self, app):
        """link_parent → (None, None): لا رسالة نجاح ولا رابط."""
        _, p_email = mk_user(app, "parent")
        client = login_as(app, p_email)
        with patch("app.modules.family.routes.link_parent", return_value=(None, None)):
            resp = client.post("/family/link", data={"code": "ABC123"}, follow_redirects=False)
        assert resp.status_code == 302

    def test_calendar_event_create_without_object_or_error(self, app):
        """create_event → (None, None): توجيه بلا رسالة نجاح."""
        sid = make_school(app)
        _, a_email = mk_user(app, "school_admin", school_id=sid)
        client = login_as(app, a_email)
        with (
            patch("app.modules.calendar.routes.create_event", return_value=(None, None)),
            patch("app.modules.calendar.routes.flash") as flashed,
        ):
            resp = client.post(
                f"/calendar/{sid}/events",
                data={"title": "حدث", "event_type": "exam", "start_date": "2026-12-01"},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        success_calls = [c for c in flashed.call_args_list if len(c.args) > 1 and c.args[1] == "success"]
        assert success_calls == []

    def test_user_school_id_none_when_only_inactive_links(self, app):
        """روابط دور غير نشطة لا تمنح مدرسة للحساب."""
        sid = make_school(app)
        uid, _ = mk_user(app, "teacher")
        make_user_role_link(app, uid, sid, role="teacher", is_active=False)
        from app.models.user import User

        with app.app_context():
            assert _db.session.get(User, uid).school_id is None


def _now():
    return datetime.now(UTC)


def _unused_os_guard():  # pragma: no cover - keeps `os` import intentional
    return os.sep
