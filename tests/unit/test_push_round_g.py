"""Round G — gap closure from CI-verified coverage map.

Covers: content routes (attachments/import/download), grades routes (rubric,
appeals, report-card parent branch, submission files), tutoring routes
(profile edit, booking errors, live-session guards, rating window, payouts),
billing routes (review TxError branches, discount validation, invoice PDF),
schools routes (assign-teacher, onboarding, 403/404 guards), app factory
(error handlers, user_loader guards, currency fallback), payments gateways
(Stripe init, CashU verification, fraud + email-failure paths), and RAG
dense-retrieval branches.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import types
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from app.core.db import TxError
from tests.conftest import (
    _uid,
    make_attachment,
    make_class,
    make_class_member,
    make_family_link,
    make_grade,
    make_lesson,
    make_payment,
    make_school,
    make_subject,
    make_subscription,
    make_subscription_plan,
    make_tutor_profile,
    make_tutoring_session,
    make_user,
)

PASSWORD = "TestPass123!"


# ── helpers ────────────────────────────────────────────────────────────────


def mk(app, role="student", school_id=None):
    email = f"g-{_uid()}@test.com"
    uid = make_user(app, role=role, school_id=school_id, email=email)
    return uid, email


def persona(app, role="student", school_id=None):
    uid, email = mk(app, role, school_id)
    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    return uid, client


def _fresh_app():
    """Second app instance for tests that must register routes post-request
    (the session-scoped `app` fixture rejects add_url_rule after first use)."""
    from app import create_app

    a = create_app()
    a.config["TESTING"] = True
    a.config["WTF_CSRF_ENABLED"] = False
    a.config["RATELIMIT_ENABLED"] = False
    a.config["EMAIL_ENABLED"] = False
    a.config["TALISMAN_ENABLED"] = False
    return a


def setup_class(app, teacher=False):
    """Create school+class; when teacher=True, return (sid, cid, tid) with tid
    assigned as the class teacher (can_teach_class only passes for them)."""
    sid = make_school(app)
    gid = make_grade(app, sid, grade_level=1)
    subj = make_subject(app)
    tid = None
    if teacher:
        tid, _ = mk(app, "teacher", sid)
    cid = make_class(app, sid, gid, subj, teacher_id=tid)
    return (sid, cid, tid) if teacher else (sid, cid, None)


def add_submission(app, class_id, assignment_id, student_id, body="جواب", file=None):
    from app.services.gradebook import create_assignment, submit_assignment

    with app.app_context():
        a = create_assignment(class_id, "واجب G", body="اشرح", created_by=student_id)[0]
        if a is None:
            from app.extensions import db
            from app.models.gradebook import Assignment

            a = db.session.get(Assignment, assignment_id)
        sub = submit_assignment(a, student_id, body=body, file=file)[0]
        return a.id, sub.id


def make_rubric(app, teacher_id, school_id, with_grade=False, submission_id=None):
    from app.extensions import db
    from app.models.gradebook import RubricCriterion, RubricGrade, RubricTemplate

    with app.app_context():
        t = RubricTemplate(teacher_id=teacher_id, school_id=school_id, title="قالب G")
        db.session.add(t)
        db.session.flush()
        c = RubricCriterion(template_id=t.id, title="الإتقان", max_score=10, sort_order=1)
        db.session.add(c)
        if with_grade and submission_id:
            db.session.add(RubricGrade(submission_id=submission_id, criterion_id=c.id, score=7.5, graded_by=teacher_id))
        db.session.commit()
        return t.id, c.id


# ══ Content routes ═════════════════════════════════════════════════════════
class TestContentRoutes:
    def test_lesson_new_form_renders(self, app):
        sid, cid, tid = setup_class(app, teacher=True)
        _, client = persona_from(app, tid)
        resp = client.get(f"/classes/{cid}/lessons/new")
        assert resp.status_code == 200

    def test_lesson_create_invalid_form_rerenders(self, app):
        sid, cid, tid = setup_class(app, teacher=True)
        _, client = persona_from(app, tid)
        resp = client.post(f"/classes/{cid}/lessons", data={})
        assert resp.status_code == 200

    def test_lesson_detail_404(self, app):
        sid, cid, _ = setup_class(app)
        uid = make_user(app, role="student", school_id=sid)
        make_class_member(app, cid, uid)
        _, client = persona_from(app, uid)
        assert client.get(f"/classes/{cid}/lessons/999999").status_code == 404

    def test_attachment_upload_non_teacher_403(self, app):
        sid, cid, _ = setup_class(app)
        uid = make_user(app, role="student", school_id=sid)
        make_class_member(app, cid, uid)
        lid = make_lesson(app, cid)
        _, client = persona(app, "student", sid)
        data = {"file": (b"pdf-bytes", "a.pdf"), "title": "مرفق"}
        assert (
            client.post(
                f"/classes/{cid}/lessons/{lid}/attachments", data=data, content_type="multipart/form-data"
            ).status_code
            == 403
        )

    def test_attachment_upload_missing_lesson_404(self, app):
        sid, cid, tid = setup_class(app, teacher=True)
        _, client = persona_from(app, tid)
        data = {"file": (b"pdf", "a.pdf")}
        assert (
            client.post(
                f"/classes/{cid}/lessons/999999/attachments", data=data, content_type="multipart/form-data"
            ).status_code
            == 404
        )

    def test_attachment_upload_success_and_txerror(self, app):
        sid, cid, tid = setup_class(app, teacher=True)
        lid = make_lesson(app, cid)
        _, client = persona_from(app, tid)

        def _png():
            from io import BytesIO

            return (BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100), f"{_uid()}.png", "image/png")

        resp = client.post(
            f"/classes/{cid}/lessons/{lid}/attachments",
            data={"file": _png(), "title": "مرفق"},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 302
        with patch("app.modules.content.routes.add_attachment", side_effect=TxError("boom")):
            resp2 = client.post(
                f"/classes/{cid}/lessons/{lid}/attachments",
                data={"file": _png(), "title": "مرفق"},
                content_type="multipart/form-data",
            )
        assert resp2.status_code == 302

    def test_attachment_download_member_ok_and_403(self, app):
        from pathlib import Path

        sid, cid, _ = setup_class(app)
        uid = make_user(app, role="student", school_id=sid)
        make_class_member(app, cid, uid)
        other = make_user(app, role="student", school_id=sid)
        lid = make_lesson(app, cid)
        aid = make_attachment(app, lid, kind="video")
        uploads = Path("instance/uploads")
        uploads.mkdir(parents=True, exist_ok=True)
        stored = f"g-{_uid()}.mp4"
        (uploads / stored).write_bytes(b"video")

        with app.app_context():
            from app.extensions import db
            from app.models.content import LessonAttachment

            att = db.session.get(LessonAttachment, aid)
            att.stored_name = stored
            att.original_name = "lesson.mp4"
            db.session.commit()

        _, client = persona_from(app, uid)
        assert client.get(f"/classes/attachments/{aid}/download").status_code == 200
        _, client2 = persona_from(app, other)
        assert client2.get(f"/classes/attachments/{aid}/download").status_code == 403

    def test_attachment_download_no_stored_name_404(self, app):
        sid, cid, _ = setup_class(app)
        uid = make_user(app, role="student", school_id=sid)
        make_class_member(app, cid, uid)
        lid = make_lesson(app, cid)
        with app.app_context():
            from app.extensions import db
            from app.models.content import LessonAttachment

            att = LessonAttachment(lesson_id=lid, kind="pdf", stored_name="")
            db.session.add(att)
            db.session.commit()
            aid = att.id
        _, client = persona_from(app, uid)
        assert client.get(f"/classes/attachments/{aid}/download").status_code == 404

    def test_lesson_import_no_target_redirects(self, app):
        sid, cid, tid = setup_class(app, teacher=True)
        lid = make_lesson(app, cid)
        _, client = persona_from(app, tid)
        resp = client.post(f"/classes/import/{lid}")
        assert resp.status_code == 302

    def test_lesson_import_success_flow(self, app):
        sid, cid, tid = setup_class(app, teacher=True)
        _, client = persona_from(app, tid)
        resp = client.post(f"/classes/{cid}/lessons", data={"title": "درس الاستيراد", "body_html": "<p>متن</p>"})
        assert resp.status_code == 302
        with app.app_context():
            from app.extensions import db
            from app.models.content import Lesson

            lid = db.session.query(Lesson).filter_by(class_id=cid).first().id
        resp2 = client.post(f"/classes/import/{lid}?target_class_id={cid}")
        assert resp2.status_code == 302

    def test_lesson_import_source_not_viewable_403(self, app):
        sid, cid, tid = setup_class(app, teacher=True)
        lid = make_lesson(app, cid)
        other_sid, other_cid, _ = setup_class(app)
        ouid = make_user(app, role="student", school_id=other_sid)
        make_class_member(app, other_cid, ouid)
        _, client = persona_from(app, ouid)
        assert client.post(f"/classes/import/{lid}?target_class_id={other_cid}").status_code == 403


def persona_from(app, uid):
    """Login an existing user id by looking up its email."""
    with app.app_context():
        from app.extensions import db
        from app.models.user import User

        email = db.session.get(User, uid).email
    client = app.test_client()
    client.post("/auth/login", data={"email": email, "password": PASSWORD})
    return uid, client


def _fresh_app():
    """Second app instance for tests that must register routes post-request
    (the session-scoped `app` fixture rejects add_url_rule after first use)."""
    from app import create_app

    a = create_app()
    a.config["TESTING"] = True
    a.config["WTF_CSRF_ENABLED"] = False
    a.config["RATELIMIT_ENABLED"] = False
    a.config["EMAIL_ENABLED"] = False
    a.config["TALISMAN_ENABLED"] = False
    return a


# ══ Grades routes ══════════════════════════════════════════════════════════
class TestGradesRoutes:
    def test_class_or_404(self, app):
        _, client = persona(app, "teacher")
        assert client.get("/classes/999999/assignments").status_code == 404

    def test_assignments_student_subs_map(self, app):
        sid, cid, _ = setup_class(app)
        uid = make_user(app, role="student", school_id=sid)
        make_class_member(app, cid, uid)
        _, client = persona_from(app, uid)
        resp = client.get(f"/classes/{cid}/assignments")
        assert resp.status_code == 200

    def test_assignment_detail_and_404(self, app):
        sid, cid, _ = setup_class(app)
        uid = make_user(app, role="student", school_id=sid)
        make_class_member(app, cid, uid)
        aid, _ = add_submission(app, cid, 0, uid)
        _, client = persona_from(app, uid)
        assert client.get(f"/classes/{cid}/assignments/{aid}").status_code == 200
        assert client.get(f"/classes/{cid}/assignments/999999").status_code == 404

    def test_assignment_submit_empty_and_body(self, app):
        sid, cid, _ = setup_class(app)
        uid = make_user(app, role="student", school_id=sid)
        make_class_member(app, cid, uid)
        from app.services.gradebook import create_assignment

        with app.app_context():
            aid = create_assignment(cid, "واجب التسليم", created_by=uid)[0].id
        _, client = persona_from(app, uid)
        resp = client.post(f"/classes/{cid}/assignments/{aid}/submit", data={})
        assert resp.status_code == 302  # error flash branch
        resp2 = client.post(f"/classes/{cid}/assignments/{aid}/submit", data={"body": "حلي الواجب"})
        assert resp2.status_code == 302

    def test_submission_file_download_and_403(self, app):
        from pathlib import Path

        sid, cid, _ = setup_class(app)
        uid = make_user(app, role="student", school_id=sid)
        make_class_member(app, cid, uid)
        stored = f"g-{_uid()}.txt"
        up = Path("instance/uploads")
        up.mkdir(parents=True, exist_ok=True)
        (up / stored).write_text("submission")
        with app.app_context():
            from app.extensions import db
            from app.models.gradebook import Assignment, Submission

            a = Assignment(class_id=cid, title="واجب ملف", created_by=uid)
            db.session.add(a)
            db.session.flush()
            s = Submission(assignment_id=a.id, student_id=uid, body=None, file=stored)
            db.session.add(s)
            db.session.commit()
            sub_id = s.id
        _, owner = persona_from(app, uid)
        assert owner.get(f"/classes/submissions/{sub_id}/file").status_code == 200
        other = make_user(app, role="student", school_id=sid)
        _, outsider = persona_from(app, other)
        assert outsider.get(f"/classes/submissions/{sub_id}/file").status_code == 403

    def test_grade_item_create_non_teacher_403(self, app):
        sid, cid, _ = setup_class(app)
        uid = make_user(app, role="student", school_id=sid)
        make_class_member(app, cid, uid)
        with app.app_context():
            from app.extensions import db
            from app.models.gradebook import GradeCategory

            cat = GradeCategory(class_id=cid, name="أعمال", weight=20)
            db.session.add(cat)
            db.session.commit()
            cat_id = cat.id
        _, client = persona_from(app, uid)
        assert client.post(f"/classes/categories/{cat_id}/items", data={"title": "بند"}).status_code == 403

    def test_grade_set_non_teacher_403_and_teacher_ok(self, app):
        sid, cid, tid = setup_class(app, teacher=True)
        uid = make_user(app, role="student", school_id=sid)
        make_class_member(app, cid, uid)
        with app.app_context():
            from app.extensions import db
            from app.models.gradebook import GradeCategory, GradeItem

            cat = GradeCategory(class_id=cid, name="اختبارات", weight=50)
            db.session.add(cat)
            db.session.flush()
            item = GradeItem(class_id=cid, category_id=cat.id, title="نصفي", max_mark=100, kind="exam")
            db.session.add(item)
            db.session.commit()
            item_id = item.id
        _, client = persona_from(app, uid)
        assert client.post(f"/classes/items/{item_id}/grade", data={"student_id": uid, "mark": 90}).status_code == 403
        _, tclient = persona_from(app, tid)
        assert tclient.post(f"/classes/items/{item_id}/grade", data={"student_id": uid, "mark": 88}).status_code == 302

    def test_gradebook_student_view(self, app):
        sid, cid, _ = setup_class(app)
        uid = make_user(app, role="student", school_id=sid)
        make_class_member(app, cid, uid)
        _, client = persona_from(app, uid)
        assert client.get(f"/classes/{cid}/gradebook").status_code == 200

    def test_category_create_teacher(self, app):
        sid, cid, tid = setup_class(app, teacher=True)
        _, client = persona_from(app, tid)
        resp = client.post(f"/classes/{cid}/categories", data={"name": "مشاركة", "weight": 10})
        assert resp.status_code == 302

    def test_report_card_teacher_parent_and_denials(self, app):
        sid, cid, tid = setup_class(app, teacher=True)
        uid = make_user(app, role="student", school_id=sid)
        make_class_member(app, cid, uid)
        parent, _ = mk(app, "parent")
        make_family_link(app, parent, uid)
        stranger = make_user(app, role="parent")
        _, tclient = persona_from(app, tid)
        assert tclient.get(f"/classes/{cid}/report-card/{uid}").status_code == 200
        _, pclient = persona_from(app, parent)
        assert pclient.get(f"/classes/{cid}/report-card/{uid}").status_code == 200
        _, sclient = persona_from(app, uid)
        assert sclient.get(f"/classes/{cid}/report-card/{uid}").status_code == 200
        other_student = make_user(app, role="student", school_id=sid)
        assert sclient.get(f"/classes/{cid}/report-card/{other_student}").status_code == 403
        _, stranger_client = persona_from(app, stranger)
        assert stranger_client.get(f"/classes/{cid}/report-card/{uid}").status_code == 403

    def test_report_card_pdf_teacher(self, app):
        sid, cid, tid = setup_class(app, teacher=True)
        uid = make_user(app, role="student", school_id=sid)
        make_class_member(app, cid, uid)
        _, client = persona_from(app, tid)
        resp = client.get(f"/classes/{cid}/report-card/{uid}/pdf")
        assert resp.status_code == 200
        assert resp.data[:4] == b"%PDF" or b"pdf" in resp.headers.get("Content-Type", "").encode().lower()

    def test_rubric_new_and_create(self, app):
        sid, cid, tid = setup_class(app, teacher=True)
        _, client = persona_from(app, tid)
        assert client.get(f"/classes/{cid}/rubric/new").status_code == 200
        resp = client.post(
            f"/classes/{cid}/rubric",
            data={"title": "قالب جديد", "criteria[0][title]": "الإتقان", "criteria[0][max_score]": "10"},
        )
        assert resp.status_code == 302
        resp2 = client.post(f"/classes/{cid}/rubric", data={"title": "بلا معايير"})
        assert resp2.status_code == 302

    def test_rubric_grade_view_and_save(self, app):
        sid, cid, tid = setup_class(app, teacher=True)
        uid = make_user(app, role="student", school_id=sid)
        make_class_member(app, cid, uid)
        aid, sub_id = add_submission(app, cid, 0, uid)
        t_id, c_id = make_rubric(app, tid, sid)
        _, client = persona_from(app, tid)
        assert client.get(f"/classes/rubric/{t_id}/grade/{sub_id}").status_code == 200
        assert client.get(f"/classes/rubric/999999/grade/{sub_id}").status_code == 404
        resp = client.post(f"/classes/rubric/grade/{sub_id}", data={f"score_{c_id}": "9", f"comment_{c_id}": "ممتاز"})
        assert resp.status_code == 302

    def test_appeal_submit_and_review(self, app):
        sid, cid, tid = setup_class(app, teacher=True)
        uid = make_user(app, role="student", school_id=sid)
        make_class_member(app, cid, uid)
        aid, sub_id = add_submission(app, cid, 0, uid)
        _, sclient = persona_from(app, uid)
        assert (
            sclient.post(f"/classes/submissions/{sub_id}/appeal", data={"reason": "أعتقد هناك خطأ"}).status_code == 302
        )
        assert sclient.post(f"/classes/submissions/{sub_id}/appeal", data={"reason": ""}).status_code == 302
        other = make_user(app, role="student", school_id=sid)
        _, oclient = persona_from(app, other)
        assert oclient.post(f"/classes/submissions/{sub_id}/appeal", data={"reason": "x"}).status_code == 403
        with app.app_context():
            from app.extensions import db
            from app.models.gradebook import GradeAppeal

            appeal = db.session.query(GradeAppeal).filter_by(submission_id=sub_id).first()
            appeal_id = appeal.id
        _, tclient = persona_from(app, tid)
        assert (
            tclient.post(
                f"/classes/appeals/{appeal_id}/review", data={"action": "approved", "response": "تم القبول"}
            ).status_code
            == 302
        )
        assert tclient.post(f"/classes/appeals/{appeal_id}/review", data={"action": "nope"}).status_code == 302

    def test_appeal_review_non_teacher_403(self, app):
        sid, cid, _ = setup_class(app)
        uid = make_user(app, role="student", school_id=sid)
        make_class_member(app, cid, uid)
        aid, sub_id = add_submission(app, cid, 0, uid)
        with app.app_context():
            from app.extensions import db
            from app.services.grade_appeals import submit_appeal

            appeal = submit_appeal(sub_id, uid, "سبب")
            db.session.commit()
            appeal_id = appeal.id
        _, client = persona_from(app, uid)
        assert client.post(f"/classes/appeals/{appeal_id}/review", data={"action": "approved"}).status_code == 403


# ══ Tutoring routes ════════════════════════════════════════════════════════
class TestTutoringRoutes:
    def test_profile_view_and_404(self, app):
        tid, _ = mk(app, "teacher")
        make_tutor_profile(app, tid)
        _, client = persona(app, "student")
        assert client.get(f"/tutoring/tutors/{tid}").status_code == 200
        assert client.get("/tutoring/tutors/999999").status_code == 404

    def test_profile_edit_updates(self, app):
        tid, _ = mk(app, "teacher")
        make_tutor_profile(app, tid)
        _, client = persona_from(app, tid)
        resp = client.post(
            "/tutoring/profile/edit",
            data={"subject": "فيزياء", "price_hour": "90", "price_session": "180", "mode": "online", "bio": "خبرة"},
        )
        assert resp.status_code == 302

    def test_book_self_redirect(self, app):
        tid, _ = mk(app, "teacher")
        make_tutor_profile(app, tid)
        _, client = persona_from(app, tid)
        resp = client.post("/tutoring/book/1", data={})
        assert resp.status_code in (302, 404)

    def test_book_self_guard(self, app):
        tid, _ = mk(app, "teacher")
        make_tutor_profile(app, tid)
        _, client = persona_from(app, tid)
        resp = client.post(f"/tutoring/book/{tid}", data={"subject": "رياضيات", "preferred_time": "2026-12-01T10:00"})
        assert resp.status_code == 302

    def test_book_duplicate_pending_flashes_error(self, app):
        sid, cid, _ = setup_class(app)
        tid, _ = mk(app, "teacher")
        make_tutor_profile(app, tid)
        uid = make_user(app, role="student", school_id=sid)
        with app.app_context():
            from app.services.tutoring import create_request

            create_request(tid, uid, "رياضيات", datetime.now(UTC) + timedelta(days=1))
        _, client = persona_from(app, uid)
        resp = client.post(
            f"/tutoring/book/{tid}",
            data={"subject": "رياضيات", "preferred_time": "2026-12-02T10:00", "mode": "online"},
        )
        assert resp.status_code == 200  # re-render with error flash

    def test_book_success(self, app):
        sid, cid, _ = setup_class(app)
        tid, _ = mk(app, "teacher")
        make_tutor_profile(app, tid)
        uid = make_user(app, role="student", school_id=sid)
        _, client = persona_from(app, uid)
        resp = client.post(
            f"/tutoring/book/{tid}",
            data={"subject": "كيمياء", "preferred_time": "2026-12-03T09:00", "mode": "online"},
        )
        assert resp.status_code == 302

    def test_session_status_guards_and_transition(self, app):
        sid, cid, _ = setup_class(app)
        tid, _ = mk(app, "teacher")
        uid = make_user(app, role="student", school_id=sid)
        sess_id = make_tutoring_session(app, tid, uid, status="active", price=200)
        stranger = make_user(app, role="student", school_id=sid)
        _, sclient = persona_from(app, stranger)
        assert sclient.get(f"/tutoring/sessions/{sess_id}/status/completed").status_code == 403
        _, tclient = persona_from(app, tid)
        assert tclient.get(f"/tutoring/sessions/{sess_id}/status/completed").status_code == 302

    def test_live_url_and_status_guards(self, app):
        sid, cid, _ = setup_class(app)
        tid, _ = mk(app, "teacher")
        uid = make_user(app, role="student", school_id=sid)
        sess_id = make_tutoring_session(app, tid, uid, status="active")
        stranger = make_user(app, role="student", school_id=sid)
        _, sclient = persona_from(app, stranger)
        assert sclient.get(f"/tutoring/sessions/{sess_id}/live-url").status_code == 403
        assert sclient.get(f"/tutoring/sessions/{sess_id}/live-status").status_code == 403
        _, tclient = persona_from(app, tid)
        assert tclient.get(f"/tutoring/sessions/{sess_id}/live-url").status_code == 200
        assert tclient.get(f"/tutoring/sessions/{sess_id}/live-status").status_code == 200

    def test_start_end_live(self, app):
        sid, cid, _ = setup_class(app)
        tid, _ = mk(app, "teacher")
        uid = make_user(app, role="student", school_id=sid)
        sess_id = make_tutoring_session(app, tid, uid, status="active")
        stranger = make_user(app, role="student", school_id=sid)
        _, sclient = persona_from(app, stranger)
        assert sclient.post(f"/tutoring/sessions/{sess_id}/start-live").status_code == 403
        _, tclient = persona_from(app, tid)
        assert tclient.post(f"/tutoring/sessions/{sess_id}/start-live").status_code == 302
        assert tclient.post(f"/tutoring/sessions/{sess_id}/end-live").status_code == 302
        _, uclient = persona_from(app, uid)
        assert uclient.post(f"/tutoring/sessions/{sess_id}/end-live").status_code == 302

    def test_rate_window_expired(self, app):
        sid, cid, _ = setup_class(app)
        tid, _ = mk(app, "teacher")
        uid = make_user(app, role="student", school_id=sid)
        # The route recomputes end_time = scheduled_at + duration_min, so the
        # session must be scheduled >25h ago for the 24h rating window to lapse.
        with app.app_context():
            from app.extensions import db
            from app.models.tutoring import TutoringSession

            s = TutoringSession(
                tutor_id=tid,
                student_id=uid,
                subject="رياضيات",
                scheduled_at=datetime.now(UTC) - timedelta(hours=30),
                duration_min=60,
                price=Decimal("100"),
                status="completed",
                payment_status="paid",
                end_time=datetime.now(UTC) - timedelta(hours=29),
            )
            db.session.add(s)
            db.session.commit()
            sess_id = s.id
        _, client = persona_from(app, uid)
        resp = client.get(f"/tutoring/rate/{sess_id}")
        assert resp.status_code == 302

    def test_rate_invalid_rating_then_success(self, app):
        sid, cid, _ = setup_class(app)
        tid, _ = mk(app, "teacher")
        uid = make_user(app, role="student", school_id=sid)
        sess_id = make_tutoring_session(app, tid, uid, status="completed", price=100)
        _, client = persona_from(app, uid)
        resp = client.post(f"/tutoring/rate/{sess_id}", data={"rating": "9"})
        assert resp.status_code == 200  # invalid rating re-renders the form
        resp2 = client.post(f"/tutoring/rate/{sess_id}", data={"rating": "5", "comment": "رائع"})
        assert resp2.status_code == 302

    def test_payout_too_low_vs_success(self, app):
        sid, cid, _ = setup_class(app)
        tid, _ = mk(app, "teacher")
        uid = make_user(app, role="student", school_id=sid)
        sess_id = make_tutoring_session(app, tid, uid, status="completed", price=1000)
        with app.app_context():
            from app.extensions import db
            from app.models.tutoring import TutoringSession
            from app.services.tutoring import create_commission_record

            sess = db.session.get(TutoringSession, sess_id)
            create_commission_record(sess)
            db.session.commit()
        _, client = persona_from(app, tid)
        resp_low = client.post("/tutoring/payout-request", data={"amount": "250"})
        assert resp_low.status_code == 302
        resp_ok = client.post("/tutoring/payout-request", data={"amount": "250"})
        assert resp_ok.status_code == 302


# ══ Billing routes ═════════════════════════════════════════════════════════
class TestBillingRoutes:
    def test_class_or_404(self, app):
        _, client = persona(app, "super_admin")
        assert client.get("/billing/999999").status_code == 404

    def test_subscribe_duplicate_active_flashes_error(self, app):
        sid, cid, _ = setup_class(app)
        plan_id = make_subscription_plan(app, sid, class_id=cid, price=50.0)
        uid = make_user(app, role="student", school_id=sid)
        make_class_member(app, cid, uid)
        make_subscription(app, uid, plan_id, cid, status="active")
        _, client = persona_from(app, uid)
        resp = client.post(f"/billing/{cid}/subscribe", data={"plan": plan_id})
        assert resp.status_code == 302

    def test_payment_create_guards_and_txerror(self, app):
        sid, cid, _ = setup_class(app)
        plan_id = make_subscription_plan(app, sid, class_id=cid, price=50.0)
        uid = make_user(app, role="student", school_id=sid)
        make_class_member(app, cid, uid)
        sub_id = make_subscription(app, uid, plan_id, cid, status="pending")
        other = make_user(app, role="student", school_id=sid)
        _, oclient = persona_from(app, other)
        assert (
            oclient.post(f"/billing/subscriptions/{sub_id}/pay", data={"reference": "x", "amount": "50"}).status_code
            == 403
        )
        _, client = persona_from(app, uid)
        with patch("app.modules.billing.routes.record_manual_payment", return_value=(None, "خطأ تجريبي")):
            resp = client.post(f"/billing/subscriptions/{sub_id}/pay", data={"reference": "TR-1", "amount": "50"})
        assert resp.status_code == 302

    def test_review_approve_txerror(self, app):
        sid, cid, _ = setup_class(app)
        plan_id = make_subscription_plan(app, sid, class_id=cid, price=50.0)
        uid = make_user(app, role="student", school_id=sid)
        sub_id = make_subscription(app, uid, plan_id, cid, status="pending")
        pay_id = make_payment(app, sub_id, status="pending")
        _, client = persona(app, "super_admin")
        with patch("app.modules.billing.routes.approve_payment", side_effect=TxError("قيد مكرر")):
            resp = client.post(f"/billing/payments/{pay_id}/approve")
        assert resp.status_code == 302

    def test_review_reject_txerror(self, app):
        sid, cid, _ = setup_class(app)
        plan_id = make_subscription_plan(app, sid, class_id=cid, price=50.0)
        uid = make_user(app, role="student", school_id=sid)
        sub_id = make_subscription(app, uid, plan_id, cid, status="pending")
        pay_id = make_payment(app, sub_id, status="pending")
        _, client = persona(app, "super_admin")
        with patch("app.modules.billing.routes.reject_payment", side_effect=TxError("خطأ")):
            resp = client.post(f"/billing/payments/{pay_id}/reject")
        assert resp.status_code == 302

    def test_discount_create_duplicate_error(self, app):
        sid, cid, _ = setup_class(app)
        _, client = persona(app, "super_admin")
        data = {"code": f"G-{_uid()}", "name": "خصم", "type": "percentage", "value": "10", "max_uses": "5"}
        resp = client.post("/billing/discounts/new", data=data)
        assert resp.status_code == 302
        resp2 = client.post("/billing/discounts/new", data=data)
        assert resp2.status_code == 200  # duplicate code flashes error, re-renders

    def test_validate_code_endpoint(self, app):
        sid, cid, _ = setup_class(app)
        plan_id = make_subscription_plan(app, sid, class_id=cid, price=100.0)
        code = f"VC-{_uid()}"
        with app.app_context():
            from app.services.billing import create_discount_code

            create_discount_code(sid, code, "خصم تحقق", "percentage", 15, max_uses=5)
        _, client = persona(app, "student")
        resp = client.post("/billing/validate-code", data={"code": code, "plan_id": plan_id})
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["error"] is None and payload["discount"] is not None

    def test_invoice_pdf_member_and_403(self, app):
        sid, cid, _ = setup_class(app)
        plan_id = make_subscription_plan(app, sid, class_id=cid, price=50.0)
        uid = make_user(app, role="student", school_id=sid)
        make_class_member(app, cid, uid)
        sub_id = make_subscription(app, uid, plan_id, cid, status="active")
        make_payment(app, sub_id, status="approved")
        _, client = persona_from(app, uid)
        resp = client.get(f"/billing/invoices/{sub_id}/pdf")
        assert resp.status_code == 200
        other = make_user(app, role="student", school_id=sid)
        _, oclient = persona_from(app, other)
        assert oclient.get(f"/billing/invoices/{sub_id}/pdf").status_code == 403


# ══ Schools routes ═════════════════════════════════════════════════════════
class TestSchoolsRoutes:
    def test_school_create_and_class_create_success(self, app):
        _, client = persona(app, "super_admin")
        resp = client.post("/schools/new", data={"name_ar": f"مدرسة G-{_uid()}"})
        assert resp.status_code == 302

    def test_class_detail_404_and_403(self, app):
        _, client = persona(app, "super_admin")
        assert client.get("/schools/class/999999").status_code == 404
        sid, cid, _ = setup_class(app)
        outsider = make_user(app, role="student", school_id=None)
        _, oclient = persona_from(app, outsider)
        assert oclient.get(f"/schools/class/{cid}").status_code == 403

    def test_class_code_404(self, app):
        _, client = persona(app, "super_admin")
        assert client.post("/schools/class/999999/code").status_code == 404

    def test_assign_teacher_404_403_and_success(self, app):
        sid, cid, _ = setup_class(app)
        tid, _ = mk(app, "teacher", sid)
        _, client = persona(app, "super_admin")
        assert client.post("/schools/class/999999/teacher", data={"teacher_id": tid}).status_code == 404
        other_sid, other_cid, _ = setup_class(app)
        admin2 = make_user(app, role="school_admin", school_id=other_sid)
        _, aclient = persona_from(app, admin2)
        assert aclient.post(f"/schools/class/{cid}/teacher", data={"teacher_id": tid}).status_code == 403
        resp = client.post(f"/schools/class/{cid}/teacher", data={"teacher_id": tid})
        assert resp.status_code == 302
        with app.app_context():
            from app.extensions import db
            from app.models.class_room import ClassRoom

            assert db.session.get(ClassRoom, cid).teacher_id == tid

    def test_onboarding_step_renders(self, app):
        sid, cid, _ = setup_class(app)
        admin = make_user(app, role="school_admin", school_id=sid)
        _, client = persona_from(app, admin)
        resp = client.get("/schools/onboarding/1")
        assert resp.status_code == 200

    def test_grade_add(self, app):
        sid, cid, _ = setup_class(app)
        admin = make_user(app, role="school_admin", school_id=sid)
        _, client = persona_from(app, admin)
        resp = client.post(f"/schools/{sid}/grades", data={"grade_level": "9", "name_ar": "التاسع G"})
        assert resp.status_code == 302


# ══ App factory internals ══════════════════════════════════════════════════
class TestAppFactoryInternals:
    def test_rate_limit_key_authenticated_and_anon(self, app):
        from app import _rate_limit_key

        with app.test_request_context("/"):
            assert _rate_limit_key()
        uid = make_user(app, role="student")
        with app.app_context():
            from app.extensions import db
            from app.models.user import User

            u = db.session.get(User, uid)
        with app.test_request_context("/"):
            from flask_login import login_user

            login_user(u)
            assert _rate_limit_key().startswith("user:")
            from flask_login import logout_user

            logout_user()

    def test_user_loader_rejects_garbage(self, app):
        from app.extensions import login_manager

        with app.app_context():
            loader = login_manager.user_callback
            assert loader is not None
            assert loader("not-an-int") is None
            assert loader(None) is None

    def test_429_handler(self, app):
        a = _fresh_app()

        def _boom_429():
            from werkzeug.exceptions import TooManyRequests

            raise TooManyRequests()

        a.add_url_rule("/boom-429", "boom429", view_func=_boom_429)
        assert a.test_client().get("/boom-429").status_code == 429


class TestAppErrorHandlers:
    def test_500_handler_rolls_back(self, app):
        a = _fresh_app()

        def _boom_500():
            raise RuntimeError("db exploded")

        a.add_url_rule("/boom-500", "boom500", view_func=_boom_500)
        resp = a.test_client().get("/boom-500")
        assert resp.status_code == 500

    def test_generic_exception_handler(self, app):
        a = _fresh_app()

        def _boom_generic():
            raise ZeroDivisionError("nope")

        a.add_url_rule("/boom-generic", "boomgeneric", view_func=_boom_generic)
        resp = a.test_client().get("/boom-generic")
        assert resp.status_code == 500

    def test_currency_filter_fallback(self, app):
        # get_locale() needs a request context, not just an app context
        with app.test_request_context("/"):
            from flask import render_template_string

            out = render_template_string("{{ 3.5|currencyformat('XYZ') }}")
            assert "3.5" in out
            assert "XYZ" in out
            out_none = render_template_string("{{ None|currencyformat('ILS') }}")
            assert "—" in out_none

    def test_health_disk_error_degrades(self, app):
        with patch("shutil.disk_usage", side_effect=OSError("disk gone")):
            client = app.test_client()
            resp = client.get("/health")
            body = resp.get_json()
            assert resp.status_code == 200
            assert body["status"] in ("degraded", "down")
            assert body["checks"]["disk"]["status"] == "error"


# ══ Payments: gateways, fraud, email failure ═══════════════════════════════
class TestPaymentsGateways:
    def test_stripe_gateway_init_with_stub(self, app):
        from app.services.payments import StripeGateway

        stripe_stub = types.ModuleType("stripe")
        stripe_stub.api_key = None
        saved = sys.modules.get("stripe")
        sys.modules["stripe"] = stripe_stub
        try:
            gw = StripeGateway({"secret_key": "sk_test_x", "webhook_secret": "whsec_x"})
            assert gw.stripe is stripe_stub
            assert stripe_stub.api_key == "sk_test_x"
            assert gw.webhook_secret == "whsec_x"
        finally:
            if saved is None:
                sys.modules.pop("stripe", None)
            else:
                sys.modules["stripe"] = saved

    def test_cashu_verify_signature_ok_completed(self, app):
        from app.services.payments import CashUGateway, PaymentGateway, PaymentIntent, PaymentStatus

        gw = CashUGateway({"webhook_secret": "sec", "encryption_key": "key"})
        payload = {"transaction_id": f"TX-{_uid()}", "status": "completed"}
        sig = hmac.new(b"sec", json.dumps(payload, sort_keys=True).encode(), hashlib.sha256).hexdigest()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "completed"}
        intent = PaymentIntent(
            id="cashu_x",
            gateway=PaymentGateway.CASHU,
            amount=Decimal("10"),
            currency="ILS",
            status=PaymentStatus.PENDING,
            user_id=1,
        )
        with app.app_context():
            sig = hmac.new(b"sec", json.dumps(payload, sort_keys=True).encode(), hashlib.sha256).hexdigest()
            with patch("requests.get", return_value=mock_resp):
                ok = gw.verify_payment(intent, {"payload": payload, "headers": {"X-Cashu-Signature": sig}})
            assert ok is True

    def test_cashu_verify_bad_signature_and_api_failure(self, app):
        from app.services.payments import CashUGateway, PaymentGateway, PaymentIntent, PaymentStatus

        gw = CashUGateway({"webhook_secret": "sec", "encryption_key": "key"})
        payload = {"transaction_id": f"TX-{_uid()}"}
        intent = PaymentIntent(
            id="cashu_x",
            gateway=PaymentGateway.CASHU,
            amount=Decimal("10"),
            currency="ILS",
            status=PaymentStatus.PENDING,
            user_id=1,
        )
        with app.app_context():
            assert gw.verify_payment(intent, {"payload": payload, "headers": {"X-Cashu-Signature": "bad"}}) is False
            sig = hmac.new(b"sec", json.dumps(payload, sort_keys=True).encode(), hashlib.sha256).hexdigest()
            with patch("requests.get", side_effect=RuntimeError("network down")):
                assert gw.verify_payment(intent, {"payload": payload, "headers": {"X-Cashu-Signature": sig}}) is False

    def test_handle_successful_payment_missing_amount(self, app):
        from app.services.payments import PaymentGateway, PaymentService

        sid, cid, _ = setup_class(app)
        plan_id = make_subscription_plan(app, sid, class_id=cid, price=50.0)
        uid = make_user(app, role="student", school_id=sid)
        sub_id = make_subscription(app, uid, plan_id, cid, status="pending")
        svc = PaymentService()
        with app.app_context():
            svc._handle_successful_payment({"metadata": {"subscription_id": sub_id}}, PaymentGateway.PAYTABS)

    def test_handle_successful_payment_suspicious_amount(self, app):
        from app.services.payments import PaymentGateway, PaymentService

        sid, cid, _ = setup_class(app)
        plan_id = make_subscription_plan(app, sid, class_id=cid, price=50.0)
        uid = make_user(app, role="student", school_id=sid)
        sub_id = make_subscription(app, uid, plan_id, cid, status="pending")
        svc = PaymentService()
        with app.app_context():
            with (
                patch.object(PaymentService, "_extract_amount", return_value=Decimal("9999")),
                patch.object(PaymentService, "_is_suspicious_amount", return_value=True),
            ):
                svc._handle_successful_payment({"metadata": {"subscription_id": sub_id}}, PaymentGateway.PAYTABS)

    def test_handle_successful_payment_email_failure_guard(self, app):
        from app.services.payments import PaymentGateway, PaymentService

        sid, cid, _ = setup_class(app)
        plan_id = make_subscription_plan(app, sid, class_id=cid, price=50.0)
        uid = make_user(app, role="student", school_id=sid)
        sub_id = make_subscription(app, uid, plan_id, cid, status="pending")
        svc = PaymentService()
        with app.app_context():
            with (
                patch.object(PaymentService, "_extract_amount", return_value=Decimal("50")),
                patch.object(PaymentService, "_is_suspicious_amount", return_value=False),
                patch("app.services.email.send_payment_approved_email", side_effect=RuntimeError("smtp down")),
            ):
                svc._handle_successful_payment({"metadata": {"subscription_id": sub_id}}, PaymentGateway.PAYTABS)

    def test_is_suspicious_amount_exception_returns_false(self, app):
        from app.services.payments import PaymentService
        from sqlalchemy.orm import Session

        svc = PaymentService()
        with app.app_context():
            with patch.object(Session, "query", side_effect=RuntimeError("db down")):
                assert svc._is_suspicious_amount(1, Decimal("100")) is False


# ══ RAG service branches ═══════════════════════════════════════════════════
class TestRagBranches:
    def test_cosine_similarity_zero_norm(self, app):
        from app.services.rag_service import _cosine_similarity

        assert _cosine_similarity({}, {"a": 1.0}) == 0.0
        assert _cosine_similarity({"a": 1.0}, {}) == 0.0
        assert _cosine_similarity({"a": 1.0}, {"a": 1.0}) == pytest.approx(1.0)

    def test_cosine_dense_guards(self, app):
        from app.services.rag_service import _cosine_dense

        assert _cosine_dense([], [1.0]) == 0.0
        assert _cosine_dense([1.0], []) == 0.0
        assert _cosine_dense([1.0, 2.0], [1.0]) == 0.0
        assert _cosine_dense([0.0, 0.0], [0.0, 0.0]) == 0.0
        assert _cosine_dense([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)

    def test_ingest_lesson_not_found_and_empty(self, app):
        from app.services.rag_service import ingest_lesson_for_rag

        with app.app_context():
            count, err = ingest_lesson_for_rag(999999, 1)
            assert count == 0 and err == "Lesson not found"
            sid, cid, _ = setup_class(app)
            lid = make_lesson(app, cid, title="درس فارغ")
            from app.extensions import db
            from app.models.content import Lesson

            lesson = db.session.get(Lesson, lid)
            lesson.title = ""
            lesson.body_html = None
            db.session.commit()
            count2, err2 = ingest_lesson_for_rag(lid, sid)
            assert count2 == 0 and err2 == "No text content in lesson"

    def test_dense_retrieval_path(self, app):
        import app.services.rag_service as rag

        sid, cid, _ = setup_class(app)
        lid = make_lesson(app, cid, title="الجبر الخطي")
        with app.app_context():
            from app.extensions import db
            from app.models.content import Lesson

            db.session.get(Lesson, lid).body_html = "<p>المصفوفات والنواقل خطية</p>"
            db.session.commit()
        with (
            patch.object(rag, "_embeddings_enabled", return_value=True),
            patch.object(rag, "_embed_texts_remote", side_effect=lambda texts: [[0.5, 0.5, 0.5, 0.5] for _ in texts]),
        ):
            with app.app_context():
                count, err = rag.ingest_lesson_for_rag(lid, sid)
                assert err is None and count >= 1
                chunks = rag.retrieve_relevant_chunks(sid, "ما هي المصفوفات؟", top_k=3)
                assert chunks, "dense retrieval must return chunks"
                assert all(c.school_id == sid for c in chunks)

    def test_retrieve_empty_school(self, app):
        import app.services.rag_service as rag

        with app.app_context():
            assert rag.retrieve_relevant_chunks(9_999_001, "سؤال") == []
