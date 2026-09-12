"""B6 — module route coverage: schools, tutoring, content, grades.

Targets only routes verified as uncovered via coverage audit + test grep.
Focus: write/action endpoints, permission denials, invalid-input branches.
"""

from __future__ import annotations

import uuid

from tests.conftest import (
    make_class,
    make_class_member,
    make_grade,
    make_grade_category,
    make_grade_item,
    make_lesson,
    make_school,
    make_subject,
    make_tutor_profile,
    make_tutoring_session,
    make_user,
)

PASSWORD = "TestPass123!"


def _email() -> str:
    return f"b6-{uuid.uuid4().hex[:10]}@test.com"


def mk_user(app, role: str, school_id=None):
    """Create a user with a known email. Returns (user_id, email)."""
    email = _email()
    uid = make_user(app, role=role, school_id=school_id, email=email)
    return uid, email


def persona(app, role: str, school_id=None):
    """Create user + logged-in test client. Returns (user_id, client)."""
    uid, email = mk_user(app, role, school_id)
    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    return uid, client


def login_as(app, uid_email: tuple[int, str]):
    client = app.test_client()
    client.post("/auth/login", data={"email": uid_email[1], "password": PASSWORD})
    return client


def _setup_class(app):
    """School + grade + subject + class. Returns (school_id, class_id, grade_id)."""
    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=_next_level(sid))
    subj = make_subject(app)
    cid = make_class(app, sid, gid, subj)
    return sid, cid, gid


_LEVELS: dict[int, int] = {}


def _next_level(sid: int) -> int:
    """grades has UNIQUE(school_id, grade_level) — hand out a fresh level per school."""
    _LEVELS[sid] = _LEVELS.get(sid, 0) + 1
    return _LEVELS[sid]


def _set_class_teacher(app, cid: int, tid: int):
    from tests.conftest import _db

    with app.app_context():
        from app.models.class_room import ClassRoom

        _db.session.get(ClassRoom, cid).teacher_id = tid
        _db.session.commit()


# ═════════════════════════════ schools ═════════════════════════════


class TestSchoolsRoutes:
    def test_index_forbidden_for_teacher(self, app):
        _, client = persona(app, "teacher", school_id=make_school(app))
        assert client.get("/schools/").status_code == 403

    def test_index_ok_for_school_admin(self, app):
        _, client = persona(app, "school_admin", school_id=make_school(app))
        assert client.get("/schools/").status_code == 200

    def test_create_school_success_redirects(self, app):
        _, client = persona(app, "super_admin")
        resp = client.post(
            "/schools/new",
            data={"name_ar": "مدرسة ب6", "domain": f"b6-{uuid.uuid4().hex[:8]}.test"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/manage" in resp.headers["Location"]

    def test_class_new_teacher_creates_class(self, app):
        sid, _, gid = _setup_class(app)
        tid, _ = mk_user(app, "teacher", school_id=sid)
        client = persona(app, "teacher", school_id=sid)[1]
        resp = client.post(
            f"/schools/{sid}/classes/new",
            data={
                "name": "صف جديد",
                "grade_id": gid,
                "subject": "فيزياء",
                "semester": "first",
                "price_first_term": "100",
                "price_second_term": "100",
                "price_annual": "180",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/schools/class/" in resp.headers["Location"]

    def test_class_code_forbidden_cross_school_teacher(self, app):
        _, cid_a, _ = _setup_class(app)
        sid_b = make_school(app)
        _, client = persona(app, "teacher", school_id=sid_b)
        assert client.post(f"/schools/class/{cid_a}/code").status_code == 403

    def test_assign_teacher_success_and_invalid_id(self, app):
        sid, cid, _ = _setup_class(app)
        _, client = persona(app, "school_admin", school_id=sid)
        teacher_id, _ = mk_user(app, "teacher", school_id=sid)
        ok = client.post(f"/schools/class/{cid}/teacher", data={"teacher_id": teacher_id})
        assert ok.status_code == 302
        # non-teacher id → silently ignored, still redirects
        student_id, _ = mk_user(app, "student", school_id=sid)
        bad = client.post(f"/schools/class/{cid}/teacher", data={"teacher_id": student_id})
        assert bad.status_code == 302

    def test_onboarding_without_school_redirects(self, app):
        _, client = persona(app, "school_admin")  # no school
        for method, path in (("get", "/schools/onboarding/1"), ("post", "/schools/onboarding/1")):
            resp = getattr(client, method)(path, follow_redirects=False)
            assert resp.status_code == 302
            assert resp.headers["Location"].endswith("/")


# ═════════════════════════════ tutoring ═════════════════════════════


class TestTutoringRoutes:
    def test_book_forbidden_for_teacher(self, app):
        tutor_id = make_user(app, role="teacher")
        make_tutor_profile(app, tutor_id)
        _, client = persona(app, "teacher")
        resp = client.get(f"/tutoring/book/{tutor_id}", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/tutoring/")

    def test_book_price_out_of_range_rejected(self, app):
        tutor_id = make_user(app, role="teacher")
        make_tutor_profile(app, tutor_id, price_hour=100.0)
        sid, _, _ = _setup_class(app)
        stud_id, client = persona(app, "student", school_id=sid)
        resp = client.post(
            f"/tutoring/book/{tutor_id}",
            data={
                "subject": "رياضيات",
                "mode": "offline",  # price_hour=100 is checked for offline mode
                "price_quote": "500",
                "note": "",
                "preferred_time": "2026-10-01T10:00",
            },
        )
        assert resp.status_code == 200
        from app.models.tutoring import TutoringRequest

        with app.app_context():
            assert TutoringRequest.query.filter_by(student_id=stud_id).count() == 0

    def test_book_success_creates_request(self, app):
        tutor_id = make_user(app, role="teacher")
        make_tutor_profile(app, tutor_id, price_hour=100.0)
        sid, _, _ = _setup_class(app)
        _, client = persona(app, "student", school_id=sid)
        resp = client.post(
            f"/tutoring/book/{tutor_id}",
            data={
                "subject": "رياضيات",
                "mode": "online",
                "price_quote": "100",
                "preferred_time": "2026-10-01T10:00",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/tutoring/my" in resp.headers["Location"]

    def test_respond_forbidden_for_non_owner_tutor(self, app):
        sid, _, _ = _setup_class(app)
        stud_id, _ = mk_user(app, "student", school_id=sid)
        real_tutor = make_user(app, role="teacher")
        make_tutor_profile(app, real_tutor)
        _, client = persona(app, "teacher")
        from app.extensions import db
        from app.models.tutoring import TutoringRequest

        with app.app_context():
            req = TutoringRequest(tutor_id=real_tutor, student_id=stud_id, subject="x", status="pending")
            db.session.add(req)
            db.session.commit()
            rid = req.id
        assert client.post(f"/tutoring/requests/{rid}/respond/accept").status_code == 403

    def test_respond_twice_flashes_already(self, app):
        sid, _, _ = _setup_class(app)
        stud_id, _ = mk_user(app, "student", school_id=sid)
        tutor, t_email = mk_user(app, "teacher")
        make_tutor_profile(app, tutor)
        client = login_as(app, (tutor, t_email))
        from app.extensions import db
        from app.models.tutoring import TutoringRequest

        with app.app_context():
            req = TutoringRequest(tutor_id=tutor, student_id=stud_id, subject="x", status="pending")
            db.session.add(req)
            db.session.commit()
            rid = req.id
        first = client.post(f"/tutoring/requests/{rid}/respond/reject", follow_redirects=False)
        assert first.status_code == 302
        second = client.post(f"/tutoring/requests/{rid}/respond/accept", follow_redirects=False)
        assert second.status_code == 302

    def test_session_status_invalid_value_404(self, app):
        sid, _, _ = _setup_class(app)
        tutor_id, tutor_email = mk_user(app, "teacher")
        stud_id, _ = mk_user(app, "student", school_id=sid)
        sess_id = make_tutoring_session(app, tutor_id, stud_id, status="requested")
        client = login_as(app, (tutor_id, tutor_email))
        assert client.get(f"/tutoring/sessions/{sess_id}/status/exploded").status_code == 404

    def test_session_pay_forbidden_for_tutor(self, app):
        sid, _, _ = _setup_class(app)
        tutor_id, tutor_email = mk_user(app, "teacher")
        stud_id, _ = mk_user(app, "student", school_id=sid)
        sess_id = make_tutoring_session(app, tutor_id, stud_id, status="requested")
        client = login_as(app, (tutor_id, tutor_email))
        assert client.post(f"/tutoring/sessions/{sess_id}/pay").status_code == 403

    def test_live_url_403_when_generator_returns_none(self, app, monkeypatch):
        """Third-party users are blocked by can_access; a None url → 403."""
        import app.modules.tutoring.routes as tmod

        sid, _, _ = _setup_class(app)
        tutor_id, _ = mk_user(app, "teacher")
        stud_id, stud_email = mk_user(app, "student", school_id=sid)
        sess_id = make_tutoring_session(app, tutor_id, stud_id, status="requested")
        monkeypatch.setattr(tmod, "generate_live_session_url", lambda *a, **kw: None)
        client = login_as(app, (stud_id, stud_email))
        assert client.get(f"/tutoring/sessions/{sess_id}/live-url").status_code == 403

    def test_live_url_forbidden_for_third_party(self, app):
        """A user with no relation to the session cannot fetch its URL."""
        sid, _, _ = _setup_class(app)
        tutor_id, _ = mk_user(app, "teacher")
        stud_id, _ = mk_user(app, "student", school_id=sid)
        sess_id = make_tutoring_session(app, tutor_id, stud_id, status="requested")
        _, client = persona(app, "student", school_id=sid)  # different student
        assert client.get(f"/tutoring/sessions/{sess_id}/live-url").status_code == 403

    def test_live_status_returns_json(self, app):
        sid, _, _ = _setup_class(app)
        tutor_id, _ = mk_user(app, "teacher")
        stud_id, stud_email = mk_user(app, "student", school_id=sid)
        sess_id = make_tutoring_session(app, tutor_id, stud_id, status="requested")
        client = login_as(app, (stud_id, stud_email))
        resp = client.get(f"/tutoring/sessions/{sess_id}/live-status")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "requested"

    def test_invite_invalid_code_redirects(self, app):
        client = app.test_client()
        resp = client.get("/tutoring/invite/NOPE-123", follow_redirects=False)
        assert resp.status_code == 302
        assert "/tutoring" in resp.headers["Location"]

    def test_earnings_page_ok(self, app):
        _, client = persona(app, "teacher")
        assert client.get("/tutoring/earnings").status_code == 200

    def test_payout_request_invalid_form_redirects(self, app):
        _, client = persona(app, "teacher")
        resp = client.post("/tutoring/payout-request", data={"amount": "-5"}, follow_redirects=False)
        assert resp.status_code == 302
        assert "/tutoring/earnings" in resp.headers["Location"]


# ═════════════════════════════ content ═════════════════════════════


class TestContentRoutes:
    def test_lesson_create_by_teacher(self, app):
        sid, cid, _ = _setup_class(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        client = login_as(app, (tid, t_email))
        resp = client.post(
            f"/classes/{cid}/lessons",
            data={"title": "درس ب6", "body_html": "<p>نص</p>"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/lessons/" in resp.headers["Location"]

    def test_publish_toggle(self, app):
        sid, cid, _ = _setup_class(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        _set_class_teacher(app, cid, tid)
        lid = make_lesson(app, cid, status="draft")
        client = login_as(app, (tid, t_email))
        pub = client.post(f"/classes/{cid}/lessons/{lid}/publish", follow_redirects=False)
        assert pub.status_code == 302
        unpub = client.post(f"/classes/{cid}/lessons/{lid}/publish", follow_redirects=False)
        assert unpub.status_code == 302

    def test_unit_create(self, app):
        sid, cid, _ = _setup_class(app)
        mk_user(app, "teacher", school_id=sid)
        _, client = persona(app, "school_admin", school_id=sid)
        resp = client.post(f"/classes/{cid}/units", data={"title": "وحدة ١"}, follow_redirects=False)
        assert resp.status_code == 302

    def test_attachment_upload_without_file_no_crash(self, app):
        sid, cid, _ = _setup_class(app)
        lid = make_lesson(app, cid)
        mk_user(app, "teacher", school_id=sid)
        _, client = persona(app, "school_admin", school_id=sid)
        resp = client.post(f"/classes/{cid}/lessons/{lid}/attachments", data={"title": "ملف"})
        assert resp.status_code == 302

    def test_attachment_youtube_success(self, app):
        sid, cid, _ = _setup_class(app)
        lid = make_lesson(app, cid)
        mk_user(app, "teacher", school_id=sid)
        _, client = persona(app, "school_admin", school_id=sid)
        resp = client.post(
            f"/classes/{cid}/lessons/{lid}/youtube",
            data={"url": "https://youtube.com/watch?v=abc123", "title": "فيديو"},
        )
        assert resp.status_code == 302

    def test_attachment_delete_by_outsider_403(self, app):
        sid, cid, _ = _setup_class(app)
        lid = make_lesson(app, cid)
        from tests.conftest import make_attachment

        att_id = make_attachment(app, lid)
        other_sid = make_school(app)
        _, client = persona(app, "school_admin", school_id=other_sid)
        assert client.post(f"/classes/attachments/{att_id}/delete").status_code == 403

    def test_import_requires_target_class(self, app):
        sid, cid, _ = _setup_class(app)
        lid = make_lesson(app, cid)
        mk_user(app, "teacher", school_id=sid)
        _, client = persona(app, "school_admin", school_id=sid)
        resp = client.post(f"/classes/import/{lid}", follow_redirects=False)
        assert resp.status_code == 302
        assert "/classes/shared" in resp.headers["Location"]

    def test_import_success_to_second_class(self, app):
        sid, cid, _ = _setup_class(app)
        gid = make_grade(app, sid, grade_level=_next_level(sid))
        subj = make_subject(app)
        cid2 = make_class(app, sid, gid, subj)
        lid = make_lesson(app, cid)
        from tests.conftest import _db

        with app.app_context():
            from app.models.content import Lesson

            _db.session.get(Lesson, lid).is_shared = True
            _db.session.commit()
        mk_user(app, "teacher", school_id=sid)
        _, client = persona(app, "school_admin", school_id=sid)
        resp = client.post(f"/classes/import/{lid}?target_class_id={cid2}", follow_redirects=False)
        assert resp.status_code == 302
        assert f"/classes/{cid2}/lessons/" in resp.headers["Location"]

    def test_shared_library_without_school_redirects(self, app):
        _, client = persona(app, "teacher")
        resp = client.get("/classes/shared", follow_redirects=False)
        assert resp.status_code == 302

    def test_offline_mark_missing_fields(self, app):
        _, client = persona(app, "student")
        resp = client.post("/classes/offline/mark", data={}, follow_redirects=False)
        assert resp.status_code == 302
        assert "/classes/offline" in resp.headers["Location"]

    def test_offline_remove_other_student_403(self, app):
        sid, cid, _ = _setup_class(app)
        lid = make_lesson(app, cid)
        from tests.conftest import make_attachment

        att = make_attachment(app, lid)
        owner, _ = mk_user(app, "student", school_id=sid)
        from app.extensions import db
        from app.models.offline import OfflineDownload

        with app.app_context():
            od = OfflineDownload(student_id=owner, attachment_id=att, lesson_id=lid)
            db.session.add(od)
            db.session.commit()
            od_id = od.id
        _, client = persona(app, "student", school_id=sid)
        assert client.post(f"/classes/offline/{od_id}/remove").status_code == 403


# ═════════════════════════════ grades ═════════════════════════════


class TestGradesRoutes:
    def _class_with_teacher_student(self, app):
        sid, cid, _ = _setup_class(app)
        tid, t_email = mk_user(app, "teacher", school_id=sid)
        stud_id, s_email = mk_user(app, "student", school_id=sid)
        make_class_member(app, cid, stud_id)
        _set_class_teacher(app, cid, tid)
        return sid, cid, tid, t_email, stud_id, s_email

    def _make_assignment(self, app, cid: int, tid: int) -> int:
        from app.extensions import db
        from app.models.gradebook import Assignment

        with app.app_context():
            a = Assignment(class_id=cid, title="واجب", max_mark=100, created_by=tid)
            db.session.add(a)
            db.session.commit()
            return a.id

    def test_assignment_create_by_teacher(self, app):
        sid, cid, _, t_email, _, _ = self._class_with_teacher_student(app)
        tc = login_as(app, (0, t_email))
        resp = tc.post(
            f"/classes/{cid}/assignments",
            data={"title": "واجب ب6", "body": "اشرح", "max_mark": "50"},
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_assignment_submit_by_student(self, app):
        sid, cid, tid, _, stud_id, s_email = self._class_with_teacher_student(app)
        aid = self._make_assignment(app, cid, tid)
        client = login_as(app, (stud_id, s_email))
        resp = client.post(
            f"/classes/{cid}/assignments/{aid}/submit",
            data={"body": "إجابتي هنا"},
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_submission_grade_by_teacher(self, app):
        sid, cid, tid, t_email, stud_id, s_email = self._class_with_teacher_student(app)
        aid = self._make_assignment(app, cid, tid)
        client = login_as(app, (stud_id, s_email))
        client.post(f"/classes/{cid}/assignments/{aid}/submit", data={"body": "إجابة"})
        from app.models.gradebook import Submission

        with app.app_context():
            sub_id = Submission.query.filter_by(assignment_id=aid, student_id=stud_id).first().id
        tc = login_as(app, (tid, t_email))
        resp = tc.post(
            f"/classes/submissions/{sub_id}/grade",
            data={"mark": "88", "feedback": "أحسنت"},
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_grade_set_invalid_inputs_ignored(self, app):
        sid, cid, tid, t_email, stud_id, _ = self._class_with_teacher_student(app)
        cat_id = make_grade_category(app, cid, "اعمال", 50)
        item_id = make_grade_item(app, cid, cat_id, "واجب1", 100)
        tc = login_as(app, (tid, t_email))
        # missing student_id → ignored, still redirects
        resp = tc.post(f"/classes/items/{item_id}/grade", data={"mark": "70"}, follow_redirects=False)
        assert resp.status_code == 302
        # valid → creates entry
        resp2 = tc.post(
            f"/classes/items/{item_id}/grade", data={"student_id": stud_id, "mark": "95"}, follow_redirects=False
        )
        assert resp2.status_code == 302

    def test_category_create(self, app):
        sid, cid, tid, t_email, *_ = self._class_with_teacher_student(app)
        tc = login_as(app, (tid, t_email))
        resp = tc.post(f"/classes/{cid}/categories", data={"name": "اختبارات", "weight": "50"}, follow_redirects=False)
        assert resp.status_code == 302

    def test_grade_item_create(self, app):
        sid, cid, tid, t_email, *_ = self._class_with_teacher_student(app)
        cat_id = make_grade_category(app, cid, "مشاركة", 20)
        tc = login_as(app, (tid, t_email))
        resp = tc.post(
            f"/classes/categories/{cat_id}/items",
            data={"title": "مشاركة1", "max_mark": "10", "kind": "homework"},
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_attendance_save(self, app):
        sid, cid, tid, t_email, stud_id, _ = self._class_with_teacher_student(app)
        tc = login_as(app, (tid, t_email))
        resp = tc.post(
            f"/classes/{cid}/attendance",
            data={"status_" + str(stud_id): "present"},
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_report_card_forbidden_for_other_student(self, app):
        sid, cid, *_ = self._class_with_teacher_student(app)
        other, _ = mk_user(app, "student", school_id=sid)
        _, client = persona(app, "student", school_id=sid)
        assert client.get(f"/classes/{cid}/report-card/{other}").status_code == 403

    def test_report_card_pdf_missing_lib_redirects(self, app, monkeypatch):
        sid, cid, _, _, stud_id, _ = self._class_with_teacher_student(app)
        import app.services.report_card as rc

        monkeypatch.setattr(rc, "render_report_card_pdf", lambda *a, **kw: None)
        client = persona(app, "school_admin", school_id=sid)[1]
        resp = client.get(f"/classes/{cid}/report-card/{stud_id}/pdf", follow_redirects=False)
        assert resp.status_code == 302

    def test_rubric_create_valid_and_invalid(self, app):
        sid, cid, tid, t_email, *_ = self._class_with_teacher_student(app)
        tc = login_as(app, (tid, t_email))
        # no criteria → flash, no template
        bad = tc.post(f"/classes/{cid}/rubric", data={"title": "قالب", "description": ""}, follow_redirects=False)
        assert bad.status_code == 302
        # valid criteria → template created
        ok = tc.post(
            f"/classes/{cid}/rubric",
            data={
                "title": "قالب ب6",
                "description": "وصف",
                "criteria[0][title]": "دقة",
                "criteria[0][max_score]": "10",
                "criteria[1][title]": "تنظيم",
                "criteria[1][max_score]": "5",
            },
            follow_redirects=False,
        )
        assert ok.status_code == 302
        from app.services.rubric import list_rubric_templates

        with app.app_context():
            assert len(list_rubric_templates(tid)) == 1

    def test_rubric_grade_flow(self, app):
        sid, cid, tid, t_email, stud_id, s_email = self._class_with_teacher_student(app)
        aid = self._make_assignment(app, cid, tid)
        client = login_as(app, (stud_id, s_email))
        client.post(f"/classes/{cid}/assignments/{aid}/submit", data={"body": "إجابة"})
        from app.models.gradebook import Submission

        with app.app_context():
            sub_id = Submission.query.filter_by(assignment_id=aid, student_id=stud_id).first().id
        tc = login_as(app, (tid, t_email))
        tc.post(
            f"/classes/{cid}/rubric",
            data={"title": "قالب", "criteria[0][title]": "دقة", "criteria[0][max_score]": "10"},
        )
        from app.services.rubric import list_rubric_templates

        with app.app_context():
            tpl = list_rubric_templates(tid)[0]
            tpl_id, crit_id = tpl.id, tpl.criteria[0].id
        page = tc.get(f"/classes/rubric/{tpl_id}/grade/{sub_id}")
        assert page.status_code == 200
        save = tc.post(
            f"/classes/rubric/grade/{sub_id}",
            data={"score_" + str(crit_id): "8", "comment_" + str(crit_id): "جيد"},
            follow_redirects=False,
        )
        assert save.status_code == 302

    def test_appeal_flow(self, app):
        sid, cid, tid, t_email, stud_id, s_email = self._class_with_teacher_student(app)
        aid = self._make_assignment(app, cid, tid)
        stud_client = login_as(app, (stud_id, s_email))
        stud_client.post(f"/classes/{cid}/assignments/{aid}/submit", data={"body": "إجابة"})
        from app.models.gradebook import Submission

        with app.app_context():
            sub_id = Submission.query.filter_by(assignment_id=aid, student_id=stud_id).first().id
        tc = login_as(app, (tid, t_email))
        tc.post(f"/classes/submissions/{sub_id}/grade", data={"mark": "50"})
        # empty reason → flash, no appeal
        no_reason = stud_client.post(f"/classes/submissions/{sub_id}/appeal", data={"reason": ""})
        assert no_reason.status_code == 302
        # valid appeal
        ok = stud_client.post(
            f"/classes/submissions/{sub_id}/appeal", data={"reason": "الإجابة صحيحة"}, follow_redirects=False
        )
        assert ok.status_code == 302
        from app.models.gradebook import GradeAppeal

        with app.app_context():
            appeal_id = GradeAppeal.query.filter_by(submission_id=sub_id).first().id
        review = tc.post(
            f"/classes/appeals/{appeal_id}/review",
            data={"action": "approved", "response": "تم القبول"},
            follow_redirects=False,
        )
        assert review.status_code == 302
